"""Phase 4.2 controlled investigations: validation before execution, limits, audit chain, planner routing, findings."""
import re
import sqlite3

import pytest

from app.investigate import audit, executor, tools
from app.investigate.plan import MAX_STEPS, PlanRejected, rule_plan, validate
from app.main import app

CAUSAL = re.compile(r"\b(caused|causes|because|due to|led to|leads to|resulted in|drove|driven by|root cause)\b", re.I)


@pytest.fixture
def events(events_db, monkeypatch):
    monkeypatch.setenv("GIST_EVENTS_DB_PATH", str(events_db[0]))
    return events_db[0]


def _plan(steps, **extra):
    return {"question": "test question", "planner": "test", "intent": "x", "window": {}, "steps": steps, **extra}


def _step(i=1, tool="releases", **args):
    return {"id": f"s{i}", "tool": tool, "args": args or {"from_date": "2025-01-08", "to_date": "2025-03-01"}, "purpose": "testing"}


BAD_PLANS = {
    "unknown tool": _plan([_step(tool="delete_events")]),
    "write-like tool": _plan([_step(tool="sql", query="DROP TABLE events")]),
    "extra argument": _plan([_step(tool="releases", from_date="2025-01-08", to_date="2025-02-01", sql="x")]),
    "bad metric": _plan([_step(tool="metric_series", metric="revenue", from_date="2025-01-08", to_date="2025-02-01")]),
    "too many steps": _plan([_step(i) for i in range(1, MAX_STEPS + 2) if i < 10]),
    "duplicate ids": _plan([_step(1), _step(1)]),
    "reversed dates": _plan([_step(tool="data_quality", from_date="2025-05-01", to_date="2025-02-01")]),
    "out of range": _plan([_step(tool="data_quality", from_date="2023-01-01", to_date="2023-02-01")]),
    "role on account metric": _plan([_step(tool="metric_series", metric="crm_sync_failure_rate", by="role", from_date="2025-01-08", to_date="2025-02-01")]),
    "unsafe search term": _plan([_step(tool="search_feedback", terms=["x'; DROP"], from_date="2025-01-08", to_date="2025-02-01")]),
    "no steps": _plan([]),
}


@pytest.mark.parametrize("name", BAD_PLANS)
def test_invalid_plans_rejected_before_any_tool_runs(name, monkeypatch, events):
    calls = []
    monkeypatch.setattr(executor, "FUNCTIONS", {k: (lambda *a, **k2: calls.append(1)) for k in executor.FUNCTIONS})
    with pytest.raises(PlanRejected):
        validate(BAD_PLANS[name])
    result = executor.run(BAD_PLANS[name])
    assert result["status"] == "rejected" and result["checks"] and calls == []
    assert audit.get(result["id"])["status"] == "rejected"


def test_step_timeout_and_total_limit_end_partial(events):
    plan = rule_plan("Why did activation drop in October?")
    timed = executor.run(plan, step_timeout=1e-9)
    assert timed["status"] == "partial"
    assert {t["status"] for t in timed["trace"] if t["tool"] in ("metric_series", "compare_periods")} == {"timeout"}
    assert all(f["step"] not in {t["step"] for t in timed["trace"] if t["status"] != "ok"} for f in timed["findings"])
    capped = executor.run(plan, total_timeout=0)
    assert capped["status"] == "partial" and {t["status"] for t in capped["trace"]} == {"skipped_time_limit"}


def test_result_size_cap(events, monkeypatch):
    monkeypatch.setattr(executor, "MAX_RESULT_BYTES", 10)
    result = executor.run(rule_plan("Why did activation drop in October?"))
    assert result["status"] == "partial" and all(t["status"] == "error" for t in result["trace"])


def test_audit_chain_detects_tampering_and_has_no_write_routes(events):
    first = executor.run(rule_plan("Why did CRM sync failures rise in July?"))
    executor.run(rule_plan("Are dashboards slow in March?"))
    assert audit.verify() == {"ok": True, "entries": 2, "first_bad": None}
    with sqlite3.connect(audit.log_path()) as db:
        db.execute("UPDATE investigations SET findings = '[]' WHERE id = ?", (first["id"],))
    assert audit.verify() == {"ok": False, "entries": 2, "first_bad": first["id"]}
    methods = {m for r in app.routes if getattr(r, "path", "").startswith("/api/investigations") for m in r.methods}
    assert methods <= {"GET", "POST", "HEAD"}


ROUTES = {
    "Why did onboarding activation drop last month?": ("activation", "2025-11-01", "2025-11-30"),
    "Why are fewer invitations being accepted since February?": ("invites", "2025-02-01", "2025-12-15"),
    "CRM sync problems in August": ("crm", "2025-08-01", "2025-08-31"),
    "Are urgent alerts late recently?": ("alerts", "2025-11-16", "2025-12-15"),
    "Why is the portfolio dashboard slow in May?": ("dashboard", "2025-05-01", "2025-05-31"),
    "Too many digest emails in June": ("digest", "2025-06-01", "2025-06-30"),
    "Can people duplicate templates in October?": ("templates", "2025-10-01", "2025-10-31"),
    "How did engagement change this year?": ("usage", "2025-01-08", "2025-12-15"),
}


@pytest.mark.parametrize("question", ROUTES)
def test_rule_planner_routes_intent_and_window(question):
    plan = rule_plan(question)
    intent, lo, hi = ROUTES[question]
    assert (plan["intent"], plan["window"]["from_date"], plan["window"]["to_date"]) == (intent, lo, hi)
    validate(plan)


def test_unclear_question_gets_health_plan_not_a_guess():
    plan = rule_plan("What should we build next?")
    assert plan["intent"] == "unclear" and any("did not name a metric" in n for n in plan["notes"])
    assert {s["tool"] for s in plan["steps"]} <= {"metric_series", "data_quality", "releases"}


def _check_findings(result):
    ok_steps = {t["step"] for t in result["trace"] if t["status"] == "ok"}
    for f in result["findings"]:
        if f["kind"] == "limitation":
            assert f["step"] is None and not re.search(r"\d", f["text"].replace("Phase 4.3", ""))
            continue
        assert f["step"] in ok_steps
        assert not CAUSAL.search(f["text"].split("“")[0]), f["text"]   # customer quotes are excluded from the check


def test_demo_findings_cite_steps_and_surface_mix_shift_and_gap(client, events):
    october = client.post("/api/investigations", json={"question": "Why did onboarding activation drop in October?"}).json()
    assert october["status"] == "completed"
    _check_findings(october)
    assert any(c["kind"] == "mostly_mix" for c in october["checks"])
    assert any("paid_campaign" in f["text"] for f in october["findings"])
    assert any(c["kind"] == "unaligned_feedback" for c in october["checks"])     # the test client serves v1 feedback
    november = client.post("/api/investigations", json={"question": "Why did onboarding activation drop last month?"}).json()
    _check_findings(november)
    assert any(c["kind"] == "tracking_gap" for c in november["checks"])
    listed = client.get("/api/investigations").json()
    assert listed["audit"]["ok"] and {i["id"] for i in listed["investigations"]} >= {october["id"], november["id"]}
    assert client.get(f"/api/investigations/{october['id']}").json()["plan"]["intent"] == "activation"
    assert client.get("/api/investigations/INV-missing").status_code == 404
    assert client.post("/api/investigations", json={"question": "x"}).status_code == 422
    off = client.post("/api/investigations", json={"question": "Why?", "planner": "model"})
    assert off.status_code == 503 and off.json()["error"]["code"] == "paid_disabled"     # paid mode off: nothing spent
    assert client.post("/api/investigations", json={"question": "Why?", "planner": "agent"}).status_code == 422
