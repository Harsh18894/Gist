"""Phase 4.5 evaluation and observability: versioned benchmark results, runtime cost and reliability,
billing vs ledger, user feedback and the regression registry.

Benchmark numbers are read from result files at request time via locations in evals/registry.json;
nothing here retypes a metric. Runtime numbers are computed with read-only SQL over the spend
ledger and the investigation audit log. Billing figures and feedback are the only writes, to a
small local store (backend/gist-ops.sqlite3).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from .config import ROOT
from .errors import InvalidRequest
from .investigate import audit
from .rag import budget

REGISTRY = ROOT / "evals" / "registry.json"
REGRESSIONS = ROOT / "evals" / "regressions.json"
FEEDBACK_TARGETS = ("investigation", "ask")
COMMENT_LIMIT = 500


# ---------------- Benchmarks

def _number(value):
    """Numbers as-is; 'a/b' fractions as a/b; anything else is not a metric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d+/\d+", value):
        a, b = map(int, value.split("/"))
        return round(a / b, 4) if b else None
    return None


def _json_path(data, path: str):
    for part in path.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(run: dict, cache: dict | None = None) -> dict:
    """Read every metric of one registry run from its files. Unresolvable metrics come back as None with a reason."""
    cache = {} if cache is None else cache
    main = ROOT / run["file"]

    def load(path: Path):
        if path not in cache:
            cache[path] = json.loads(path.read_text()) if path.suffix == ".json" else list(csv.DictReader(path.open()))
        return cache[path]

    metrics, files = [], {run["file"]: _sha(main) if main.exists() else None}
    for metric in run["metrics"]:
        src = metric["source"]
        value, raw, problem, of = None, None, None, None
        if "json" in src:
            if not main.exists():
                problem = "file missing"
            else:
                raw = _json_path(load(main), src["json"])
                value = _number(raw)
                if value is None and raw == "0/0":
                    problem = None            # nothing to measure in this run (e.g. no unanswerable questions); shown as n/a
                else:
                    problem = None if value is not None else f"no number at {src['json']}"
        else:
            spec = src["csv_count"]
            path = ROOT / spec["file"]
            if not path.exists():
                problem = "file missing"
            else:
                files[spec["file"]] = _sha(path)
                rows = load(path)
                if rows and spec["column"] not in rows[0]:
                    problem = f"no column {spec['column']}"
                else:
                    value = sum(1 for r in rows if r[spec["column"]].strip().lower() == spec["equals"])
                    of = len(rows)
        metrics.append({**{k: metric[k] for k in ("key", "label", "unit", "better")}, "value": value, "raw": raw if isinstance(raw, str) else None,
                        "not_applicable": raw == "0/0",
                        "of": of, "problem": problem, "source": src})
    return {**{k: v for k, v in run.items() if k != "metrics"}, "metrics": metrics,
            "files": [{"path": p, "sha256": s} for p, s in files.items()]}


def benchmarks() -> dict:
    registry = json.loads(REGISTRY.read_text())
    cache: dict = {}
    runs = [resolve(r, cache) for r in registry["runs"]]
    families: dict[str, list[str]] = defaultdict(list)
    for r in runs:
        families[r["family"]].append(r["id"])
    return {"judged_by": registry["judged_by"], "runs": runs, "families": families,
            "note": "Values are read from versioned result files at request time (SHA-256 shown). Judged metrics name the document "
                    "that defines their review process. Pulse data is synthetic."}


# ---------------- Runtime: spend ledger and investigation audit log

def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.execute("PRAGMA query_only = ON")
    return db


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(q * (len(values) - 1))))], 1)


def ledger_summary() -> dict:
    db = _ro(budget._path())
    if db is None:
        return {"available": False, "by_day": [], "by_endpoint": [], "totals": {}}
    try:
        rows = db.execute("""SELECT substr(created_at,1,10), endpoint, model, state, reserved_usd, actual_estimated_usd,
            input_tokens, output_tokens, latency_ms FROM spend_requests""").fetchall()
    finally:
        db.close()

    def cost(r):   # completed and reconciled use the recorded actual; uncertain holds its reservation
        return r[5] if r[3] in ("completed", "reconciled") and r[5] is not None else (r[4] if r[3] == "uncertain" else 0.0)

    def group(key):
        out = defaultdict(list)
        for r in rows:
            out[key(r)].append(r)
        return [{"key": k, "requests": len(v), "cost_usd": round(sum(cost(r) for r in v), 6),
                 "input_tokens": sum(r[6] or 0 for r in v), "output_tokens": sum(r[7] or 0 for r in v),
                 "latency_p50_ms": _pct([r[8] for r in v if r[8] is not None], 0.5),
                 "latency_p95_ms": _pct([r[8] for r in v if r[8] is not None], 0.95),
                 "failed_or_uncertain": sum(r[3] not in ("completed", "reconciled") for r in v)} for k, v in sorted(out.items())]
    return {"available": True, "by_day": group(lambda r: r[0]), "by_endpoint": group(lambda r: f"{r[1]} · {r[2]}"),
            "totals": {"requests": len(rows), "cost_usd": round(sum(cost(r) for r in rows), 6),
                       "uncertain": sum(r[3] == "uncertain" for r in rows), "reconciled": sum(r[3] == "reconciled" for r in rows),
                       "cap_usd": budget.MAX_VALIDATION_USD},
            "note": "Ledger costs are estimates from token counts × configured prices; provider billing is the source of truth."}


def investigation_summary(limit: int = 15) -> dict:
    db = _ro(audit.log_path())
    if db is None:
        return {"available": False}
    try:
        cols = [r[1] for r in db.execute("PRAGMA table_info(investigations)")]
        rows = [dict(zip(cols, r)) for r in db.execute("SELECT * FROM investigations ORDER BY seq")]
    finally:
        db.close()
    step_ms, step_status, report_status, problems, costs = defaultdict(list), Counter(), Counter(), Counter(), []
    for r in rows:
        for t in json.loads(r["trace"]):
            step_ms[t["tool"]].append(t.get("duration_ms", 0))
            step_status[t["status"]] += 1
        rep = json.loads(r.get("report") or "null")
        if rep:
            report_status[rep.get("status", "unknown")] += 1
            for p in rep.get("problems") or []:
                problems[re.sub(r"[:(].*", "", p).strip()[:80]] += 1
            costs.append(r["cost_usd"])
    return {"available": True, "runs": len(rows),
            "by_planner": dict(Counter(r["planner"] for r in rows)), "by_status": dict(Counter(r["status"] for r in rows)),
            "report_status": dict(report_status), "report_problems": dict(problems.most_common(8)),
            "step_status": dict(step_status),
            "step_latency": [{"tool": k, "steps": len(v), "p50_ms": _pct(v, 0.5), "p95_ms": _pct(v, 0.95)} for k, v in sorted(step_ms.items())],
            "cost_per_ai_investigation": {"runs": len(costs), "mean_usd": round(statistics.fmean(costs), 6) if costs else None,
                                          "max_usd": round(max(costs), 6) if costs else None},
            "audit": audit.verify(),
            "recent": [{k: r[k] for k in ("id", "created_at", "question", "planner", "status", "cost_usd")} for r in rows[-limit:][::-1]]}


# ---------------- Local ops store: billing figures and feedback

def ops_path() -> Path:
    value = os.getenv("GIST_OPS_DB_PATH")
    if not value:
        return ROOT / "backend" / "gist-ops.sqlite3"
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _ops() -> sqlite3.Connection:
    db = sqlite3.connect(ops_path())
    db.executescript("""
    CREATE TABLE IF NOT EXISTS billing (day TEXT PRIMARY KEY, amount_usd REAL NOT NULL, source TEXT NOT NULL, entered_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, target_type TEXT NOT NULL,
      target_id TEXT NOT NULL, rating TEXT NOT NULL, comment TEXT);""")
    return db


def set_billing(day: str, amount_usd: float, source: str) -> dict:
    try:
        parsed = date.fromisoformat(day)
    except ValueError as exc:
        raise InvalidRequest("bad day", public_message="day must be a UTC date like 2026-11-26.") from exc
    if parsed > datetime.now(timezone.utc).date():
        raise InvalidRequest("future day", public_message="Billing days cannot be in the future.")
    if not (0 <= amount_usd < 1000) or amount_usd != amount_usd:
        raise InvalidRequest("bad amount", public_message="amount_usd must be between 0 and 1000.")
    source = (source or "").strip()[:120] or "owner entry"
    with _ops() as db:
        db.execute("INSERT OR REPLACE INTO billing VALUES (?,?,?,?)",
                   (parsed.isoformat(), round(amount_usd, 6), source, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return {"day": parsed.isoformat(), "amount_usd": round(amount_usd, 6), "source": source}


def billing_vs_ledger() -> dict:
    with _ops() as db:
        billed = {r[0]: {"amount_usd": r[1], "source": r[2]} for r in db.execute("SELECT day, amount_usd, source FROM billing")}
    ledger = {d["key"]: d["cost_usd"] for d in ledger_summary()["by_day"]}
    days = []
    for day in sorted(set(billed) | set(ledger)):
        b, l = billed.get(day, {}).get("amount_usd"), ledger.get(day)
        days.append({"day": day, "billed_usd": b, "ledger_usd": l, "source": billed.get(day, {}).get("source"),
                     "difference_usd": round(b - l, 6) if b is not None and l is not None else None,
                     "ledger_vs_billed": round(l / b, 4) if b and l is not None else None})
    return {"days": days, "note": "Billing is per UTC day for the whole provider account; it may include non-Gist usage. "
                                  "Enter figures from the provider's cost export."}


def add_feedback(target_type: str, target_id: str, rating: str, comment: str | None) -> dict:
    if target_type not in FEEDBACK_TARGETS:
        raise InvalidRequest("bad target", public_message="Feedback target must be investigation or ask.")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", target_id or ""):
        raise InvalidRequest("bad id", public_message="Invalid target id.")
    if rating not in ("up", "down"):
        raise InvalidRequest("bad rating", public_message="Rating must be up or down.")
    comment = (comment or "").strip() or None
    if comment and len(comment) > COMMENT_LIMIT:
        raise InvalidRequest("long comment", public_message=f"Comments are limited to {COMMENT_LIMIT} characters.")
    with _ops() as db:
        cur = db.execute("INSERT INTO feedback (created_at, target_type, target_id, rating, comment) VALUES (?,?,?,?,?)",
                         (datetime.now(timezone.utc).isoformat(timespec="seconds"), target_type, target_id, rating, comment))
    return {"id": cur.lastrowid, "target_type": target_type, "target_id": target_id, "rating": rating}


def feedback_summary(limit: int = 20) -> dict:
    with _ops() as db:
        rows = db.execute("SELECT id, created_at, target_type, target_id, rating, comment FROM feedback ORDER BY id DESC").fetchall()
    counts: dict = defaultdict(lambda: {"up": 0, "down": 0})
    for r in rows:
        counts[r[2]][r[4]] += 1
    return {"total": len(rows), "by_target": dict(counts),
            "recent": [dict(zip(("id", "created_at", "target_type", "target_id", "rating", "comment"), r)) for r in rows[:limit]],
            "note": "Feedback is an unvalidated signal from whoever uses this local app; it is not an accuracy measure."}


# ---------------- Regressions

def regressions() -> dict:
    data = json.loads(REGRESSIONS.read_text())
    for case in data["cases"]:
        path, _, name = case["test"].partition("::")
        source = (ROOT / path).read_text() if (ROOT / path).exists() else ""
        case["test_exists"] = bool(re.search(rf"^def {re.escape(name.split('[')[0])}\(", source, re.M))
    return data
