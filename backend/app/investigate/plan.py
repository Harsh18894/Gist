"""Investigation plans: a typed schema, a validator, and a $0 rule-based planner (Phase 4.2).

A plan is a short list of steps, each naming a tool from a fixed read-only registry with
typed arguments. Every plan, whoever wrote it, passes `validate` before anything runs.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import tools
from ..schemas import Area

MAX_STEPS = 6
REFERENCE_DATE = tools.DATA_END        # "today" for relative phrases is the end of the data
Metric = Literal[tuple(tools.METRICS)]  # type: ignore[valid-type]
Dimension = Literal[tuple(tools.DIMENSIONS)]  # type: ignore[valid-type]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricSeriesArgs(_Args):
    metric: Metric
    grain: Literal["week", "month"] = "month"
    by: Dimension | None = None
    from_date: date
    to_date: date


class ComparePeriodsArgs(_Args):
    metric: Metric
    a_from: date
    a_to: date
    b_from: date
    b_to: date
    by: Dimension = "segment"


class WindowArgs(_Args):
    from_date: date
    to_date: date


class SearchFeedbackArgs(_Args):
    terms: list[str] = Field(min_length=1, max_length=5)
    product_area: Area | None = None
    from_date: date
    to_date: date

    @field_validator("terms")
    @classmethod
    def _terms(cls, value: list[str]) -> list[str]:
        if not all(re.fullmatch(r"[A-Za-z][A-Za-z\-]{1,29}", t) for t in value):
            raise ValueError("terms must be single words of 2-30 letters")
        return value


class ProductDocsArgs(_Args):
    from_date: date
    to_date: date
    ids: list[str] | None = Field(default=None, max_length=6)

    @field_validator("ids")
    @classmethod
    def _ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and not all(re.fullmatch(r"(prd|release)-\d{2}", i) for i in value):
            raise ValueError("document ids look like prd-01 or release-05")
        return value


# The registry is the only place tools are named. Every entry is read-only by construction.
REGISTRY: dict[str, type[_Args]] = {
    "metric_series": MetricSeriesArgs, "compare_periods": ComparePeriodsArgs,
    "releases": WindowArgs, "data_quality": WindowArgs, "search_feedback": SearchFeedbackArgs,
    "product_docs": ProductDocsArgs,
}


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^s[1-9]$")
    tool: str
    args: dict
    purpose: str = Field(min_length=3, max_length=200)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=500)
    planner: str
    intent: str
    window: dict
    steps: list[Step] = Field(min_length=1)
    notes: list[str] = []


class PlanRejected(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def validate(raw: dict) -> tuple[Plan, list[_Args]]:
    """Return the plan and parsed arguments, or raise PlanRejected listing every problem."""
    try:
        plan = Plan.model_validate(raw)
    except ValidationError as exc:
        raise PlanRejected([f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]) from exc
    problems, parsed = [], []
    if len(plan.steps) > MAX_STEPS:
        problems.append(f"plan has {len(plan.steps)} steps; the limit is {MAX_STEPS}")
    if len({s.id for s in plan.steps}) != len(plan.steps):
        problems.append("step ids must be unique")
    lo, hi = tools.DATA_START - timedelta(days=31), tools.DATA_END + timedelta(days=31)
    for step in plan.steps:
        schema = REGISTRY.get(step.tool)
        if schema is None:
            problems.append(f"{step.id}: '{step.tool}' is not an allowed tool (allowed: {', '.join(REGISTRY)})")
            continue
        try:
            args = schema.model_validate(step.args)
        except ValidationError as exc:
            problems += [f"{step.id}.{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
            continue
        dates = [v for v in args.model_dump().values() if isinstance(v, date)]
        if any(not lo <= d <= hi for d in dates):
            problems.append(f"{step.id}: dates must be within the data range")
        for a, b in (("from_date", "to_date"), ("a_from", "a_to"), ("b_from", "b_to")):
            if hasattr(args, a) and getattr(args, a) > getattr(args, b):
                problems.append(f"{step.id}: {a} is after {b}")
        if step.tool == "compare_periods" and args.a_to >= args.b_from:
            problems.append(f"{step.id}: period a is the earlier baseline and must end before period b (the target) starts")
        if step.tool in ("metric_series", "compare_periods") and getattr(args, "by", None) == "role" and \
                args.metric in ("crm_sync_failure_rate", "alert_delay_p50_minutes", "alert_delayed_share"):
            problems.append(f"{step.id}: {args.metric} is recorded per account and has no role breakdown")
        parsed.append(args)
    if problems:
        raise PlanRejected(problems)
    return plan, parsed


# ---------------- Rule-based planner ($0)

INTENTS = [  # (intent, keywords, metric, breakdowns, feedback area, feedback terms)
    ("invites", ("invite", "invitation", "invited", "join", "joining"), "invite_acceptance_rate", ("segment", "role"), "Onboarding", ["invite", "join"]),
    ("activation", ("activation", "activate", "activated", "onboard", "onboarding", "signup", "sign-up", "signups", "new users"),
     "activation_rate", ("segment", "channel"), "Onboarding", ["invite", "setup", "onboarding"]),
    ("crm", ("crm", "sync", "integration", "integrations", "connector"), "crm_sync_failure_rate", ("segment",), "Integrations", ["sync", "crm", "connector"]),
    ("alerts", ("alert", "alerts", "notification", "notifications", "mention", "mentions", "urgent"), "alert_delayed_share", ("segment",), "Notifications", ["alert", "urgent", "mention"]),
    ("dashboard", ("dashboard", "slow", "load", "loading", "performance", "portfolio"), "dashboard_load_p50_ms", ("workspace_size", "segment"), "Dashboard", ["slow", "load", "loading"]),
    ("digest", ("digest", "email", "emails", "inbox", "noise", "noisy"), "digest_emails_per_user_week", ("segment",), "Notifications", ["digest", "email", "emails"]),
    ("templates", ("template", "templates", "gallery", "duplicate"), "template_duplicate_denials", ("role", "segment"), "Collaboration", ["template", "duplicate"]),
    ("usage", ("active", "engagement", "usage", "sessions", "retention"), "weekly_active_users", ("segment",), None, []),
]
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}


def _month_window(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))
    return max(start, tools.DATA_START), min(end, tools.DATA_END)


def _window(question: str) -> tuple[date, date, str]:
    q = question.lower()
    found = [(m, i) for m, i in MONTHS.items() if re.search(rf"\b{m}\b", q)]
    if found:
        month = found[-1][1]
        if re.search(r"\bsince\b", q):
            return max(date(2025, month, 1), tools.DATA_START), tools.DATA_END, f"since {found[-1][0].title()} 2025"
        lo, hi = _month_window(2025, month)
        return lo, hi, f"{found[-1][0].title()} 2025"
    if re.search(r"\b(this month|recently|lately|last (few|couple of) weeks|past (two|2|few) weeks)\b", q):
        return REFERENCE_DATE - timedelta(days=29), REFERENCE_DATE, "the last 30 days of data"
    if re.search(r"\b(this year|over the year|all year|2025)\b", q):
        return tools.DATA_START, tools.DATA_END, "all of 2025"
    lo, hi = _month_window(2025, 11)      # "last month" and the default: the last full month before the data end
    return lo, hi, "November 2025 (the last full month of data)" if "last month" not in q else "last month (November 2025)"


def rule_plan(question: str) -> dict:
    q = question.lower()
    # Prefix match, so "invitation" also matches "invitations" and "email" matches "emails".
    scores = [(sum(bool(re.search(rf"\b{re.escape(k)}", q)) for k in kw), -i, intent) for i, (intent, kw, *_) in enumerate(INTENTS)]
    best = max(scores)
    lo, hi, label = _window(question)
    span = (hi - lo).days + 1   # used for the health-plan trend window
    if label == "all of 2025":                        # whole year: no separate baseline, monthly trend only
        base_lo = base_hi = None
    else:
        base_hi = lo - timedelta(days=1)
        base_lo = max(tools.DATA_START, base_hi - timedelta(days=89))
        if base_hi < tools.DATA_START + timedelta(days=13):
            base_lo = base_hi = None
    window = {"from_date": lo.isoformat(), "to_date": hi.isoformat(), "label": label,
              "baseline": [base_lo.isoformat(), base_hi.isoformat()] if base_lo else None}
    notes = [f"Relative dates use the end of the data ({REFERENCE_DATE.isoformat()}) as today."]
    if best[0] == 0:
        steps = [
            {"id": "s1", "tool": "metric_series", "args": {"metric": "event_volume", "grain": "week", "from_date": (lo - timedelta(days=56)).isoformat() if span < 300 else lo.isoformat(), "to_date": hi.isoformat()},
             "purpose": "Overall activity trend, as a general health check"},
            {"id": "s2", "tool": "data_quality", "args": {"from_date": lo.isoformat(), "to_date": hi.isoformat()}, "purpose": "Look for tracking gaps"},
            {"id": "s3", "tool": "releases", "args": {"from_date": lo.isoformat(), "to_date": hi.isoformat()}, "purpose": "Releases in the window (timing only)"},
        ]
        notes.append("The question did not name a metric Gist tracks (activation, invites, CRM sync, alerts, dashboard speed, "
                     "digest emails, templates or usage), so this is a general data-health plan. Ask about one of these to investigate.")
        return {"question": question, "planner": "rules", "intent": "unclear", "window": window, "steps": steps, "notes": notes}
    intent, _, metric, dims, area, terms = INTENTS[-best[1]]
    series_from = base_lo or lo
    steps = [{"id": "s1", "tool": "metric_series", "args": {"metric": metric, "grain": "month", "from_date": series_from.isoformat(), "to_date": hi.isoformat()},
              "purpose": f"Trend of {metric} before and during the window"}]
    if base_lo:
        for dim in dims[:2]:
            steps.append({"id": f"s{len(steps) + 1}", "tool": "compare_periods",
                          "args": {"metric": metric, "a_from": base_lo.isoformat(), "a_to": base_hi.isoformat(),
                                   "b_from": lo.isoformat(), "b_to": hi.isoformat(), "by": dim},
                          "purpose": f"Compare the window with the 3 months before, by {dim}" +
                                     (" (separates a mix shift from a rate change)" if tools.METRICS[metric][1] == "rate" else "")})
    else:
        notes.append("No baseline period: the window starts too close to the beginning of the data (or covers the whole year).")
    steps.append({"id": f"s{len(steps) + 1}", "tool": "data_quality", "args": {"from_date": lo.isoformat(), "to_date": hi.isoformat()},
                  "purpose": "Check for tracking gaps inside the window"})
    steps.append({"id": f"s{len(steps) + 1}", "tool": "releases", "args": {"from_date": series_from.isoformat(), "to_date": hi.isoformat()},
                  "purpose": "Releases before and during the window (timing only)"})
    if terms:
        steps.append({"id": f"s{len(steps) + 1}", "tool": "search_feedback",
                      "args": {"terms": terms, "product_area": area, "from_date": series_from.isoformat(), "to_date": hi.isoformat()},
                      "purpose": "What customers said about this area"})
    return {"question": question, "planner": "rules", "intent": intent, "window": window, "steps": steps[:MAX_STEPS], "notes": notes}
