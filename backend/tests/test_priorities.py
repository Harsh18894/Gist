"""Phase 3.4 prioritization: traceable parts, estimates never invented, validated persistent edits."""
import sqlite3

import pytest

from app import priorities


def _table(client):
    response = client.get("/api/priorities")
    assert response.status_code == 200
    return response.json()


def test_contributions_sum_and_trace_to_opportunities(client):
    table = _table(client)
    cards = {c["id"]: c for c in client.get("/api/opportunities").json()["opportunities"]}
    assert {r["opportunity_id"] for r in table["rows"]} == set(cards)
    assert table["weights"] == priorities.DEFAULT_WEIGHTS
    for row in table["rows"]:
        card = cards[row["opportunity_id"]]
        parts = {p["part"]: p for p in row["measured"]}
        assert set(parts) == set(priorities.PARTS)
        assert parts["reach"]["raw"] == card["frequency"]["records"]
        assert parts["recent"]["raw"] == card["trend"]["recent_90_days"]
        assert parts["negative"]["raw"] == card["severity_proxy"]["negative_share"]
        assert parts["evidence"]["raw"] == card["confidence"]["points"] / 4
        assert all(0 <= p["score"] <= 100 for p in parts.values())
        assert row["evidence_score"] == pytest.approx(sum(p["contribution"] for p in parts.values()), abs=0.01)
    ranks = [r["rank"] for r in table["rows"]]
    assert ranks == list(range(1, len(ranks) + 1))
    assert [r["priority"] for r in table["rows"]] == sorted((r["priority"] for r in table["rows"]), reverse=True)


def test_unset_estimates_never_change_scores_or_invent_effort(client):
    for row in _table(client)["rows"]:
        assert row["priority"] == row["evidence_score"]
        assert row["estimates"]["strategic"] is None and row["estimates"]["effort"] is None
        assert row["estimates"]["effort_points"] is None and row["priority_per_effort_point"] is None


def test_estimates_apply_persist_and_clear(client):
    row = _table(client)["rows"][0]
    oid = row["opportunity_id"]
    assert client.put(f"/api/priorities/{oid}", json={"strategic": "low", "effort": "L", "note": " check with sales "}).status_code == 200
    updated = next(r for r in _table(client)["rows"] if r["opportunity_id"] == oid)
    assert updated["priority"] == pytest.approx(row["evidence_score"] * 0.8, abs=0.01)
    assert updated["priority_per_effort_point"] == pytest.approx(updated["priority"] / 3, abs=0.01)
    assert updated["estimates"]["note"] == "check with sales"
    assert updated["evidence_score"] == row["evidence_score"]          # measured part untouched
    assert client.put(f"/api/priorities/{oid}", json={}).status_code == 200  # clearing removes the row
    cleared = next(r for r in _table(client)["rows"] if r["opportunity_id"] == oid)
    assert cleared["priority"] == row["evidence_score"] and cleared["estimates"]["updated_at"] is None


def test_weights_validate_persist_and_reset(client):
    new = {**priorities.DEFAULT_WEIGHTS, "reach": 0, "support": 60}
    assert client.put("/api/priorities/weights", json={"weights": new}).json()["weights"] == new
    assert _table(client)["weights"] == new
    for bad in ({**new, "extra": 5}, {k: 0 for k in new}, {**new, "reach": 101}, {**new, "reach": -1}):
        assert client.put("/api/priorities/weights", json={"weights": bad}).status_code == 422
    assert client.delete("/api/priorities/weights").json()["weights"] == priorities.DEFAULT_WEIGHTS


def test_invalid_inputs_rejected(client):
    oid = _table(client)["rows"][0]["opportunity_id"]
    for bad in ({"strategic": "urgent"}, {"effort": "XXL"}, {"note": "x" * 501}):
        assert client.put(f"/api/priorities/{oid}", json=bad).status_code == 422
    assert client.put("/api/priorities/OPP-C999", json={"effort": "S"}).status_code == 404


def test_inputs_for_changed_data_are_stale_not_applied(client):
    oid = _table(client)["rows"][0]["opportunity_id"]
    key = _table(client)["dataset_key"]
    version = key.split(":")[0]
    with sqlite3.connect(priorities.store_path()) as store:
        store.execute("INSERT INTO inputs VALUES (?, ?, 'high', 'S', NULL, 'x')", (f"{version}:oldfingerprint", oid))
    table = _table(client)
    assert table["stale_inputs"] == 1
    assert all(r["estimates"]["strategic"] is None for r in table["rows"])


def test_rank_scores_handle_ties_and_bounds():
    assert priorities._rank_scores([1, 1, 1]) == [50.0, 50.0, 50.0]
    assert priorities._rank_scores([1, 2, 3]) == [0.0, 50.0, 100.0]
    assert priorities._rank_scores([7]) == [50.0]


def test_browser_preflight_allows_priority_edits(client):
    for method in ("PUT", "DELETE"):
        response = client.options("/api/priorities/weights", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
