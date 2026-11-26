"""Phase 3.5 experiments: facts trace to data, suggestions are checked and labelled, no paid calls."""
import json
import sqlite3

import pytest

from app import experiments as ex
from app.database import database_path
from app.opportunities import build
from app.priorities import dataset_key

GOOD = {
    "hypothesis": "We believe that clearer reset confirmation for SMB admins will reduce repeat reset reports because customers say the old password still works.",
    "intervention": "Show a confirmation that the old password is now invalid and sign out other sessions.",
    "target_audience": "SMB and Mid-market admins using password reset in Onboarding",
    "primary_metric": {"name": "Repeat reset requests", "definition": "Share of users who request a second reset within a week of the first"},
    "guardrail_metrics": [{"name": "Login success rate", "why": "The change must not block valid sign-ins"}],
    "experiment_design": {"type": "A/B test", "description": "Randomly show the new confirmation to half of reset users and compare repeat requests."},
    "risks": ["Signing out other sessions may surprise users"],
    "assumptions_to_validate": ["The old password really keeps working, rather than users misreading the flow"],
}


def _card_and_payload():
    with sqlite3.connect(database_path()) as db:
        card = build(db)["opportunities"][0]
        return card, ex.payload(db, card), dataset_key(db)


def test_check_accepts_a_good_draft_and_strips_code_fences(client):
    _, data, _ = _card_and_payload()
    draft, problems = ex.check("```json\n" + json.dumps(GOOD) + "\n```", data)
    assert problems == [] and draft["experiment_design"]["type"] == "A/B test"


@pytest.mark.parametrize("change, problem", [
    ({"hypothesis": "Reset fixes will cut tickets by 37% next quarter."}, "number not present"),
    ({"intervention": "Spend $5k on a redesign."}, "currency"),
    ({"intervention": "Reply within 24h and expect 2x fewer reports."}, "number not present"),
    ({"intervention": "Aim for 9 fewer reports."}, "number not present"),
    ({"intervention": "This guarantees fewer complaints."}, "guaranteed-outcome"),
    ({"experiment_design": {"type": "Multivariate bandit", "description": "x"}}, "allowed types"),
    ({"risks": []}, "risks must have"),
    ({"primary_metric": {"name": "Resets"}}, "primary_metric"),
    ({"guardrail_metrics": [{"name": "x"}] * 4}, "guardrail_metrics must have"),
])
def test_check_rejects_unsafe_or_malformed_drafts(client, change, problem):
    _, data, _ = _card_and_payload()
    draft, problems = ex.check(json.dumps({**GOOD, **change}), data)
    assert draft is None and any(problem in p for p in problems)
    assert ex.check("not json", data) == (None, ["not valid JSON"])


def test_facts_trace_to_data_and_nothing_generated_by_default(client):
    data = client.get("/api/experiments").json()
    cards = {c["id"]: c for c in client.get("/api/opportunities").json()["opportunities"]}
    assert data["counts"]["not_generated"] == len(cards) == len(data["experiments"])
    for row in data["experiments"]:
        card = cards[row["opportunity_id"]]
        assert row["status"] == "not_generated" and row["suggestion"] is None
        assert row["facts"]["baseline"]["records_last_90_days"] == card["trend"]["recent_90_days"]
        assert row["facts"]["affected_segments"] == card["segments"]
        assert row["facts"]["problem_statement"].startswith(f"{card['frequency']['records']} feedback records")
    assert client.get("/api/experiments/OPP-C999").status_code == 404


def _save(entry_overrides: dict, card, data, key):
    path = ex.generated_path(key.split(":")[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"dataset_key": key, "input_hash": ex.input_hash(data), "prompt_version": ex.PROMPT_VERSION, "model": "test",
             "generated_at": "2026-11-26T00:00:00+00:00", "draft": GOOD, "problems": [], **entry_overrides}
    path.write_text(json.dumps({"drafts": {card["id"]: entry}}))


def test_saved_draft_is_labelled_suggestion(client):
    card, data, key = _card_and_payload()
    _save({}, card, data, key)
    row = client.get(f"/api/experiments/{card['id']}").json()
    assert row["status"] == "draft"
    assert row["suggestion"]["label"].startswith("Suggestion") and "not validated" in row["suggestion"]["label"]
    assert row["suggestion"]["hypothesis"] == GOOD["hypothesis"]


def test_changed_evidence_or_failed_checks_hide_the_suggestion(client):
    card, data, key = _card_and_payload()
    _save({"input_hash": "different"}, card, data, key)
    assert client.get(f"/api/experiments/{card['id']}").json()["status"] == "stale"
    _save({"draft": None, "problems": ["contains a number not present in the evidence"]}, card, data, key)
    row = client.get(f"/api/experiments/{card['id']}").json()
    assert row["status"] == "failed_checks" and row["suggestion"] is None and row["problems"]


def test_generation_script_uses_guarded_provider(client, monkeypatch, tmp_path):
    """The script's per-card loop with a mocked provider: drafts saved and checked, no network."""
    from scripts import generate_experiments as gen
    calls = []
    monkeypatch.setattr(gen.provider, "suggest", lambda db, instructions, payload: (
        calls.append(payload["opportunity_id"]) or (json.dumps(GOOD), {"model": "mock", "input_tokens": 10, "output_tokens": 10, "estimated_cost_usd": 0.0})))
    monkeypatch.setattr(sys_argv := __import__("sys"), "argv", ["generate_experiments.py", "--run"])
    assert gen.main() == 0
    data = client.get("/api/experiments").json()
    assert len(calls) == len(data["experiments"]) and data["counts"]["draft"] == len(calls)
    calls.clear()
    assert gen.main() == 0 and calls == []          # resumable: nothing re-drafted


def test_paid_call_refused_without_approval(client):
    from app.rag import provider
    with sqlite3.connect(database_path()) as db, pytest.raises(provider.PaidApiDisabled):
        provider.suggest(db, ex.INSTRUCTIONS, {"x": 1})
