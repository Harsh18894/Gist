"""Run a validated investigation plan under limits, check the outputs, and write demo findings (Phase 4.2).

No step can run before the whole plan validates. Steps run in order with a per-step timeout
and a total time limit; a failed or timed-out step is recorded and the run ends `partial`.
Demo findings are deterministic statements of what the tools returned, each citing its step.
They make no causal claims: explaining causes is Phase 4.3.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import date

from . import audit, model, tools
from .plan import PlanRejected, rule_plan, validate
from ..errors import GistError

STEP_TIMEOUT_S = 5.0
TOTAL_TIMEOUT_S = 20.0
MAX_RESULT_BYTES = 200_000
MAX_MODEL_CALLS = 2          # one plan, one report; no retries
SMALL_SAMPLE = 30
FUNCTIONS = {"metric_series": tools.metric_series, "compare_periods": tools.compare_periods, "releases": tools.releases,
             "data_quality": tools.data_quality, "search_feedback": tools.search_feedback, "product_docs": tools.product_docs}
LIMITATIONS = [
    "Pulse data is synthetic.",
    "This demo report states what the tools measured. It does not explain causes; a change near a release or a complaint is timing, not proof.",
    "Feedback matches are keyword-based and show what customers experienced, not why a metric moved.",
]


def _plain(args) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in args.model_dump().items() if v is not None}


def _fmt(metric: str, value) -> str:
    if value is None:
        return "no data"
    unit = tools.METRICS[metric][0]
    if unit == "share":
        return f"{value * 100:.1f}%"
    if unit == "milliseconds":
        return f"{value:,.0f} ms"
    if unit == "minutes":
        return f"{value:,.1f} min"
    return f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"


def _delta(metric: str, a, b) -> str:
    if a is None or b is None:
        return ""
    if tools.METRICS[metric][0] == "share":
        return f" ({(b - a) * 100:+.1f} points)"
    return f" ({(b - a) / a * 100:+.0f}%)" if a else ""


def _month(bucket: str) -> str:
    return date.fromisoformat(bucket + "-01").strftime("%b") if len(bucket) == 7 else bucket


def _findings_and_checks(step, args, result, window) -> tuple[list[dict], list[dict]]:
    F, C = [], []
    sid = step.id
    if step.tool == "metric_series":
        rows = [r for r in result["series"] if r["group"] == "all"]
        if rows:
            values = ", ".join(f"{_month(r['bucket'])} {_fmt(args.metric, r['value'])}" for r in rows)
            F.append({"kind": "observed", "step": sid, "text": f"{args.metric} by month: {values}."})
        if result.get("note") and window["to_date"] >= "2025-12-01":
            C.append({"step": sid, "kind": "incomplete_cohort", "message": result["note"]})
    elif step.tool == "compare_periods":
        o = result["overall"]
        F.append({"kind": "observed", "step": sid, "text": (
            f"{args.metric}: {_fmt(args.metric, o['a']['value'])} in {args.a_from}–{args.a_to}, "
            f"{_fmt(args.metric, o['b']['value'])} in {args.b_from}–{args.b_to}{_delta(args.metric, o['a']['value'], o['b']['value'])}.")})
        d = result.get("decomposition")
        if d:
            F.append({"kind": "observed", "step": sid, "text": (
                f"Split by {args.by}: {d['mix_effect'] * 100:+.1f} points from the {args.by} mix changing and "
                f"{d['rate_effect'] * 100:+.1f} points from rates changing within each {args.by}.")})
            if abs(d["mix_effect"]) > abs(d["rate_effect"]) and abs(d["mix_effect"]) >= 0.02:
                C.append({"step": sid, "kind": "mostly_mix", "message": f"Most of the change comes from a shift in {args.by} mix, not from rates within groups."})
        groups = [g for g in result["groups"] if g["share_a"] is not None and g["share_b"] is not None]
        if groups:
            moved = max(groups, key=lambda g: abs(g["share_b"] - g["share_a"]))
            if abs(moved["share_b"] - moved["share_a"]) >= 0.05:
                F.append({"kind": "observed", "step": sid, "text": f"{moved['group']} went from {moved['share_a'] * 100:.0f}% to {moved['share_b'] * 100:.0f}% of the {args.by} mix."})
            measured = [g for g in groups if g["a"]["value"] is not None and g["b"]["value"] is not None
                        and min(g["a"]["n"], g["b"]["n"]) >= SMALL_SAMPLE]   # small groups are flagged, never headlined
            if measured:
                g = max(measured, key=lambda g: abs(g["b"]["value"] - g["a"]["value"]) * min(g["a"]["n"], g["b"]["n"]) ** 0.5)
                F.append({"kind": "observed", "step": sid, "text": (
                    f"Largest within-group change: {g['group']} {_fmt(args.metric, g['a']['value'])} → {_fmt(args.metric, g['b']['value'])}"
                    f"{_delta(args.metric, g['a']['value'], g['b']['value'])} (n = {g['a']['n']} → {g['b']['n']}).")})
            small = [g["group"] for g in groups if min(g["a"]["n"], g["b"]["n"]) < SMALL_SAMPLE]
            if small:
                C.append({"step": sid, "kind": "small_sample", "message": f"Fewer than {SMALL_SAMPLE} records in a period for: {', '.join(small)}. Treat those rates as noisy."})
    elif step.tool == "data_quality":
        days = result["low_volume_days"]
        if days:
            text = ", ".join(f"{d['date']} ({d['ratio'] * 100:.0f}% of usual volume)" for d in days)
            F.append({"kind": "data_quality", "step": sid, "text": f"Low recorded event volume on {text}."})
            C.append({"step": sid, "kind": "tracking_gap", "message": "Event volume dropped sharply on some days in the window. "
                      "Metrics that depend on those events may be under-measured; check before reading them as behaviour changes."})
        else:
            F.append({"kind": "data_quality", "step": sid, "text": "No low-volume days were flagged in the window."})
    elif step.tool == "releases":
        if result["releases"]:
            F.append({"kind": "timing", "step": sid, "text": "Releases in the period: " + "; ".join(
                f"{r['id']} {r['title']} ({r['released_on']})" for r in result["releases"]) + ". Timing only, not evidence of cause."})
    elif step.tool == "product_docs":
        if result["documents"]:
            F.append({"kind": "timing", "step": sid, "text": "Product documents: " + "; ".join(
                f"{d['id']} {d['title']} ({d['published']})" for d in result["documents"]) + "."})
    elif step.tool == "search_feedback":
        if result["dataset_version"] != "v2":
            C.append({"step": sid, "kind": "unaligned_feedback", "message": "The selected feedback dataset is not Pulse v2, so it is not aligned with the product-events data."})
        months = ", ".join(f"{_month(m)} {n}" for m, n in result["by_month"].items()) or "none"
        F.append({"kind": "customer_voice", "step": sid, "text": (
            f"{result['matches']} feedback records mention {', '.join(result['terms'])}"
            f"{' in ' + result['product_area'] if result['product_area'] else ''} ({months}).")})
        for q in result["quotes"][:2]:
            F.append({"kind": "customer_voice", "step": sid, "text": f"“{q['text']}” ({q['id']}, {q['date']}, {q['segment']})"})
    return F, C


def run(raw_plan: dict, *, step_timeout: float = STEP_TIMEOUT_S, total_timeout: float = TOTAL_TIMEOUT_S, log: bool = True) -> dict:
    question = str(raw_plan.get("question", ""))[:500]
    planner = str(raw_plan.get("planner", "unknown"))[:40]
    try:
        plan, parsed = validate(raw_plan)
    except PlanRejected as exc:
        entry = {"question": question, "planner": planner, "status": "rejected", "plan": raw_plan, "trace": [],
                 "results": {}, "checks": [{"step": None, "kind": "plan_rejected", "message": p} for p in exc.problems],
                 "findings": [], "cost_usd": 0.0}
        return audit.append(entry) if log else entry
    started = time.monotonic()
    trace, results, findings, checks = [], {}, [], []
    status = "completed"
    for step, args in zip(plan.steps, parsed):
        elapsed = time.monotonic() - started
        record = {"step": step.id, "tool": step.tool, "args": _plain(args), "purpose": step.purpose}
        if elapsed >= total_timeout:
            trace.append({**record, "status": "skipped_time_limit", "duration_ms": 0})
            status = "partial"
            continue
        token = tools.DEADLINE.set(time.monotonic() + min(step_timeout, total_timeout - elapsed))
        t0 = time.monotonic()
        try:
            result = FUNCTIONS[step.tool](**_plain(args))
            size = len(json.dumps(result, default=str).encode())
            if size > MAX_RESULT_BYTES:
                raise OverflowError(f"result is {size} bytes; the limit is {MAX_RESULT_BYTES}")
            outcome = "ok"
        except sqlite3.OperationalError as exc:
            result, outcome = None, "timeout" if "interrupt" in str(exc).lower() else "error"
            record["error"] = "Stopped at the step time limit." if outcome == "timeout" else "A database error stopped this step."
        except GistError as exc:
            result, outcome, record["error"] = None, "error", exc.public_message
        except OverflowError as exc:
            result, outcome, record["error"] = None, "error", str(exc)
        finally:
            tools.DEADLINE.reset(token)
        duration = round((time.monotonic() - t0) * 1000)
        if outcome != "ok":
            status = "partial"
            trace.append({**record, "status": outcome, "duration_ms": duration})
            continue
        results[step.id] = result
        trace.append({**record, "status": "ok", "duration_ms": duration,
                      "result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:16]})
        f, c = _findings_and_checks(step, args, result, plan.window)
        findings += f
        checks += c
    entry = {"question": plan.question, "planner": plan.planner, "status": status,
             "plan": plan.model_dump(), "trace": trace, "results": results, "checks": checks,
             "findings": findings + [{"kind": "limitation", "step": None, "text": t} for t in LIMITATIONS], "cost_usd": 0.0}
    return audit.append(entry) if log else entry


def investigate(question: str, planner: str = "rules", call=None) -> dict:
    """Run a whole investigation. 'rules' is $0. 'model' makes two guarded paid calls (plan, report) via `call`.

    Raises PaidApiDisabled (before anything is spent) when paid mode is off.
    """
    if planner == "rules":
        return run(rule_plan(question))
    from ..database import connection
    from ..rag import provider
    raw_call = call or provider.investigation_call
    made = []

    def call(db, instructions, payload):   # hard limit: at most MAX_MODEL_CALLS paid calls per investigation
        if len(made) >= MAX_MODEL_CALLS:
            raise provider.PaidRequestRejected(f"An investigation may make at most {MAX_MODEL_CALLS} model calls.")
        made.append(1)
        return raw_call(db, instructions, payload)
    usage, report_block = [], {"prompt_version": model.PROMPT_VERSION}
    with connection() as db:
        plan, plan_usage, plan_problems = model.plan_with_model(db, question, call)   # PaidApiDisabled propagates
        usage.append({"call": "planner", **plan_usage})
        entry = run(plan, log=False)
        report_block["planner_problems"] = plan_problems
        if entry["status"] != "rejected":
            try:
                report, problems, report_usage, raw = model.write_report(db, entry, call)
                usage.append({"call": "report", **report_usage})
                report_block.update({"report": report, "problems": problems, "status": "passed" if report else "failed_checks",
                                     "raw": None if report else raw[:20_000]})   # kept for audit and debugging when withheld
            except provider.ProviderError as exc:
                report_block.update({"report": None, "problems": [str(exc)], "status": "provider_error"})
            except provider.PaidApiDisabled as exc:
                report_block.update({"report": None, "problems": [str(exc)], "status": "not_run"})
    report_block["usage"] = usage
    entry["cost_usd"] = round(sum(u.get("estimated_cost_usd") or 0 for u in usage), 8)
    entry["report"] = report_block
    return audit.append(entry)
