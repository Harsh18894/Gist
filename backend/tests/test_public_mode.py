"""Phase 5.1 public-mode hardening: read-only demo, gated paid AI, request limits. No paid calls (mocked model)."""
import json

import pytest

from app import public
from app.investigate import model
from app.investigate.plan import rule_plan
from app.rag import provider

CODE = "demo-code-1234567"
Q = "Why did onboarding activation drop in October?"


@pytest.fixture
def public_on(client, monkeypatch):
    monkeypatch.setenv("GIST_PUBLIC_MODE", "true")
    monkeypatch.setattr(public, "GATE", public.AiGate())
    monkeypatch.setattr(public, "API_WINDOW", public._Window())
    return client


@pytest.fixture
def ai_on(public_on, monkeypatch, events_db):
    monkeypatch.setenv("GIST_PUBLIC_AI", "true")
    monkeypatch.setenv("GIST_PUBLIC_AI_ACCESS_CODE", CODE)
    monkeypatch.setenv("GIST_EVENTS_DB_PATH", str(events_db[0]))
    calls = []

    def fake(db, instructions, payload):
        calls.append(1)
        usage = {"model": "mock", "input_tokens": 1, "output_tokens": 1, "estimated_cost_usd": 0.001}
        if instructions == model.PLANNER_INSTRUCTIONS:
            return json.dumps({k: v for k, v in rule_plan(payload["question"]).items() if k in ("intent", "window", "steps", "notes")}), usage
        return "{}", usage
    monkeypatch.setattr(provider, "investigation_call", fake)
    public_on.calls = calls
    return public_on


def _ai(client, code=CODE):
    headers = {"X-Gist-Access-Code": code} if code else {}
    return client.post("/api/investigations", json={"question": Q, "planner": "model"}, headers=headers)


def test_off_by_default(client):
    assert client.get("/api/public/status").json() == {"public_mode": False, "public_ai": False, "ai_needs_access_code": False,
                                                       "limits": None, "spent_today_usd": None, "read_only": False}


def test_owner_only_writes_blocked_reads_allowed(public_on):
    oid = public_on.get("/api/priorities").json()["rows"][0]["opportunity_id"]
    blocked = [public_on.put("/api/priorities/weights", json={"weights": {"reach": 1, "recent": 1, "negative": 1, "support": 1, "evidence": 1}}),
               public_on.delete("/api/priorities/weights"),
               public_on.put(f"/api/priorities/{oid}", json={"effort": "S"}),
               public_on.put("/api/observability/billing", json={"day": "2026-11-26", "amount_usd": 1}),
               public_on.post("/api/feedback", json={"target_type": "ask", "target_id": "a", "rating": "up", "comment": "rude text"})]
    assert all(r.status_code == 403 and r.json()["error"]["code"] == "read_only_demo" for r in blocked)
    assert public_on.post("/api/feedback", json={"target_type": "ask", "target_id": "a", "rating": "up"}).status_code == 200
    for path in ("/api/priorities", "/api/opportunities", "/api/evidence", "/api/eval/benchmarks", "/api/investigations"):
        assert public_on.get(path).status_code == 200, path
    assert public_on.post("/api/investigations", json={"question": Q}).status_code == 200      # $0 rules mode stays open


def test_public_ai_off_unless_enabled_with_a_long_code(public_on, monkeypatch):
    assert _ai(public_on).json()["error"]["code"] == "ai_disabled"
    monkeypatch.setenv("GIST_PUBLIC_AI", "true")
    monkeypatch.setenv("GIST_PUBLIC_AI_ACCESS_CODE", "short")
    assert _ai(public_on, "short").json()["error"]["code"] == "ai_disabled"
    assert public_on.post("/api/ask", json={"question": "What do customers say about invites?", "mode": "openai"}).status_code == 403


def test_access_code_required_and_never_revealed(ai_on):
    assert _ai(ai_on, None).json()["error"]["code"] == "access_code"
    assert _ai(ai_on, "wrong-code-123456").json()["error"]["code"] == "access_code"
    assert ai_on.calls == []
    ok = _ai(ai_on)
    assert ok.status_code == 200 and ok.json()["planner"] == "model" and len(ai_on.calls) == 2
    status = ai_on.get("/api/public/status").json()
    assert CODE not in json.dumps(status) and status["public_ai"] and status["spent_today_usd"] == pytest.approx(0.002)


def test_per_ip_limit(ai_on, monkeypatch):
    monkeypatch.setenv("GIST_PUBLIC_AI_PER_HOUR", "1")
    assert _ai(ai_on).status_code == 200
    second = _ai(ai_on)
    assert second.status_code == 429 and second.json()["error"]["code"] == "rate_limited" and len(ai_on.calls) == 2


def test_daily_cap_checks_worst_case_before_spending(ai_on, monkeypatch):
    monkeypatch.setenv("GIST_PUBLIC_AI_DAILY_USD", str(public.worst_case_usd(2, provider.INVESTIGATION_MAX_OUTPUT_TOKENS) / 2))
    r = _ai(ai_on)
    assert r.status_code == 429 and r.json()["error"]["code"] == "daily_cap" and ai_on.calls == []


def test_one_ai_request_at_a_time(ai_on):
    public.GATE.busy.acquire()
    try:
        r = _ai(ai_on)
        assert r.status_code == 429 and r.json()["error"]["code"] == "busy" and ai_on.calls == []
    finally:
        public.GATE.busy.release()


def test_reservation_released_when_run_fails(ai_on, monkeypatch):
    def broken(*a, **k):
        raise provider.PaidApiDisabled("off")
    monkeypatch.setattr(provider, "investigation_call", broken)
    assert _ai(ai_on).status_code == 503
    assert public.GATE.spent_today() == 0 and not public.GATE.busy.locked()


def test_general_rate_limit_and_body_cap(public_on, monkeypatch):
    monkeypatch.setenv("GIST_PUBLIC_API_PER_MINUTE", "3")
    codes = [public_on.get("/api/health").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    monkeypatch.setattr(public, "API_WINDOW", public._Window())
    big = public_on.post("/api/investigations", content=json.dumps({"question": "x" * 70_000}), headers={"Content-Type": "application/json"})
    assert big.status_code == 413


def test_client_ip_uses_proxy_header_only_when_trusted(monkeypatch):
    class R:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = type("C", (), {"host": "10.0.0.9"})()
    assert public.client_ip(R()) == "10.0.0.9"
    monkeypatch.setenv("GIST_TRUST_PROXY", "true")
    assert public.client_ip(R()) == "203.0.113.7"
