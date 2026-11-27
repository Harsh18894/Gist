"""Phase 4.5 evaluation registry and observability: values come from files and logs, never retyped."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from app import observability
from app.investigate import executor
from app.investigate.plan import rule_plan
from app.rag import budget

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = json.loads((ROOT / "evals/registry.json").read_text())
FINALS = ["evals/v2/results/heldout_test-all.json", "evals/phase21/results/benchmark3-heldout-final.json",
          "evals/phase22/results/benchmark4-final.json", "evals/phase23/results/benchmark5-final.json",
          "evals/phase32/results/clustering-themes-v1.json", "evals/phase33/results/linking-v3-owner-key.json",
          "evals/phase34/results/robustness-v1.json", "evals/phase35/results/review-v1.json",
          "evals/phase43/results/dev-run2.json", "evals/phase44/results/heldout-run.json"]


def test_registry_covers_finals_and_every_metric_resolves():
    data = observability.benchmarks()
    assert {r["file"] for r in REGISTRY["runs"]} >= set(FINALS)
    for run in data["runs"]:
        assert run["files"][0]["sha256"], run["id"]
        for m in run["metrics"]:
            assert m["problem"] is None and (isinstance(m["value"], (int, float)) or m["not_applicable"]), (run["id"], m)


def test_registry_never_types_a_value():
    for run in REGISTRY["runs"]:
        for m in run["metrics"]:
            assert set(m) == {"key", "label", "source", "unit", "better"}, run["id"]
            assert set(m["source"]) <= {"json", "csv_count"}


def test_judged_metrics_name_their_process_document():
    for run in REGISTRY["runs"]:
        assert run["judged_by"] in REGISTRY["judged_by"]
        if run["judged_by"] in ("owner", "ai-judge"):
            doc = run["process"].split(" ")[0]
            assert (ROOT / doc).exists(), (run["id"], doc)


def test_values_match_the_files_directly():
    data = {r["id"]: r for r in observability.benchmarks()["runs"]}
    heldout = json.loads((ROOT / "evals/phase44/results/heldout-run.json").read_text())
    assert {m["key"]: m["value"] for m in data["p44-heldout"]["metrics"]}["planted"] == heldout["totals"]["planted_found"]
    answered = json.loads((ROOT / "evals/phase21/results/benchmark3-answers.json").read_text())["summary"]["answerable_answered_by_gist"]
    a, b = map(int, answered.split("/"))
    assert {m["key"]: m["value"] for m in data["p21-b3-answers"]["metrics"]}["answered"] == round(a / b, 4)


def test_missing_metric_location_is_reported_not_invented():
    run = dict(REGISTRY["runs"][0], metrics=[{"key": "x", "label": "x", "unit": "share", "better": "higher", "source": {"json": "no.such.path"}}])
    m = observability.resolve(run)["metrics"][0]
    assert m["value"] is None and "no number" in m["problem"]


def _seed_ledger(path):
    with budget._ledger():
        pass
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO spend_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
            ("a", None, "2026-11-26T10:00:00+00:00", "responses", "m", "completed", 0.05, 0.01, 100, 50, 1000, None),
            ("b", None, "2026-11-26T11:00:00+00:00", "responses", "m", "completed", 0.05, 0.02, 200, 60, 3000, None),
            ("c", None, "2026-11-26T12:00:00+00:00", "responses", "m", "uncertain", 0.05, None, None, None, None, "timeout"),
            ("d", None, "2026-11-25T12:00:00+00:00", "embeddings", "e", "reconciled", 0.05, 0.002, 10, 0, 50, "x")])


def test_ledger_summary_matches_direct_sql():
    _seed_ledger(budget._path())
    s = observability.ledger_summary()
    day = {d["key"]: d for d in s["by_day"]}
    assert day["2026-11-26"]["cost_usd"] == pytest.approx(0.08) and day["2026-11-26"]["failed_or_uncertain"] == 1
    assert day["2026-11-25"]["cost_usd"] == pytest.approx(0.002)
    assert s["totals"]["requests"] == 4 and s["totals"]["uncertain"] == 1
    assert day["2026-11-26"]["input_tokens"] == 300 and day["2026-11-26"]["latency_p95_ms"] == 3000


def test_billing_vs_ledger_and_validation(client):
    _seed_ledger(budget._path())
    assert client.put("/api/observability/billing", json={"day": "2026-11-26", "amount_usd": 0.1, "source": "export"}).status_code == 200
    for bad in ({"day": "2026-13-01", "amount_usd": 1}, {"day": "2999-01-01", "amount_usd": 1}, {"day": "2026-11-26", "amount_usd": -1}):
        assert client.put("/api/observability/billing", json=bad).status_code == 422
    days = {d["day"]: d for d in client.get("/api/observability/runtime").json()["billing"]["days"]}
    assert days["2026-11-26"]["difference_usd"] == pytest.approx(0.02) and days["2026-11-25"]["billed_usd"] is None


def test_feedback_capture_and_validation(client):
    assert client.post("/api/feedback", json={"target_type": "investigation", "target_id": "INV-abc123", "rating": "up"}).status_code == 200
    assert client.post("/api/feedback", json={"target_type": "ask", "target_id": "q-1", "rating": "down", "comment": " vague "}).status_code == 200
    for bad in ({"target_type": "admin", "target_id": "x", "rating": "up"}, {"target_type": "ask", "target_id": "x", "rating": "meh"},
                {"target_type": "ask", "target_id": "../etc", "rating": "up"}, {"target_type": "ask", "target_id": "x", "rating": "up", "comment": "x" * 501}):
        assert client.post("/api/feedback", json=bad).status_code == 422
    summary = client.get("/api/feedback").json()
    assert summary["total"] == 2 and summary["by_target"]["ask"]["down"] == 1 and summary["recent"][0]["comment"] == "vague"


def test_investigation_summary_matches_audit_log(client, events_db, monkeypatch):
    monkeypatch.setenv("GIST_EVENTS_DB_PATH", str(events_db[0]))
    executor.run(rule_plan("Why did activation drop in October?"))
    executor.run(rule_plan("Why did activation drop in October?"), step_timeout=1e-9)
    s = client.get("/api/observability/runtime").json()["investigations"]
    assert s["runs"] == 2 and s["by_status"] == {"completed": 1, "partial": 1} and s["audit"]["ok"]
    assert s["step_status"]["timeout"] >= 1 and {t["tool"] for t in s["step_latency"]} >= {"metric_series", "data_quality"}


def test_regression_registry_maps_to_existing_tests():
    data = observability.regressions()
    assert len(data["cases"]) >= 12
    missing = [c["id"] for c in data["cases"] if not c["test_exists"]]
    assert not missing, missing


def test_observability_reads_are_read_only(client):
    _seed_ledger(budget._path())
    before = budget._path().read_bytes()
    client.get("/api/observability/runtime")
    assert budget._path().read_bytes() == before


def test_every_run_has_a_status_target_note_and_matching_label():
    for run in REGISTRY["runs"]:
        assert run["status"] in REGISTRY["statuses"], run["id"]
        assert run["verdict"] == REGISTRY["statuses"][run["status"]], run["id"]
        assert run["target_note"].strip(), run["id"]


def test_met_status_only_where_every_recorded_target_was_met():
    """'Met' must not be used for a run whose result file records any missed target."""
    met = {r["id"]: r for r in REGISTRY["runs"] if r["status"] == "met"}
    files = {"p33-linking": ("chosen", "test_targets_met"), "p32-clustering": ("chosen", "test_targets_met"),
             "p44-heldout": ("totals", "criteria"), "p43-dev-run2": ("totals", "criteria")}
    for run_id, (a, b) in files.items():
        run = next(r for r in REGISTRY["runs"] if r["id"] == run_id)
        flags = json.loads((ROOT / run["file"]).read_text())[a][b]
        if not all(flags.values()):
            assert run_id not in met, f"{run_id} records a missed target but is labelled Met"
