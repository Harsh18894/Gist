"""Phase 3.3 opportunities: evidence integrity, no invented business figures, both data paths."""
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import issues, opportunities
from app.main import app
from scripts.seed import seed
from helpers import V2_DB  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = ("$", "revenue of", "arr ", "mrr", "uplift", "roi", "story points", "person-days")


def _check(client):
    data = client.get("/api/opportunities").json()
    issue_map = client.get("/api/issues").json()
    triage = {s["id"] for s in issue_map["sub_themes"] if s["needs_triage"]}
    assert set(data["excluded_needs_triage"]) == triage
    assert len(data["opportunities"]) == len(issue_map["sub_themes"]) - len(triage)
    subs = {s["id"]: s for s in issue_map["sub_themes"]}
    for card in data["opportunities"]:
        sub = subs[card["sub_theme_id"]]
        assert card["evidence"]["feedback_records"] == sub["size"]
        assert card["evidence"]["also_mentioned_in"] == sub["secondary_members"]
        assert card["confidence"]["level"] in ("high", "medium", "low")
    detail = client.get(f"/api/opportunities/{data['opportunities'][0]['id']}").json()
    assert len(detail["evidence"]["feedback"]) == detail["evidence"]["feedback_records"] + detail["evidence"]["also_mentioned_in"]
    assert detail["assumptions"] and detail["unknowns"] and detail["confidence_rubric"]
    assert any("Business impact" in u for u in detail["unknowns"])
    generated = json.dumps({k: detail[k] for k in ("assumptions", "unknowns", "severity_proxy", "frequency", "confidence")}).lower()
    assert not any(token in generated for token in FORBIDDEN)
    assert client.get("/api/opportunities/OPP-C999").status_code == 404
    return data


def test_opportunities_fall_back_without_stored_vectors(tmp_path, monkeypatch):
    issues._cache.clear()
    path = tmp_path / "v2.sqlite3"
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    seed("v2", path=path)
    with TestClient(app) as client:
        assert _check(client)["method"] == "word similarity"


def test_opportunities_on_real_v2_index_link_tickets_and_documents(monkeypatch, tmp_path):
    issues._cache.clear()
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    copy = tmp_path / "gist-v2.sqlite3"
    shutil.copyfile(V2_DB, copy)   # never write to the shipped snapshot
    monkeypatch.setenv("GIST_DB_PATH", str(copy))
    with TestClient(app) as client:
        data = _check(client)
    assert data["method"].startswith("learned vectors") and len(data["opportunities"]) == 61
    assert data["link_config"]["ticket_threshold"] == 0.6 and data["link_config"]["document_threshold"] == 0.5
    assert any(c["evidence"]["linked_tickets"] for c in data["opportunities"])
    assert any(c["product_context"] for c in data["opportunities"])
    issues._cache.clear()


def test_link_config_validation():
    with pytest.raises(ValueError):
        opportunities.LinkConfig(ticket_threshold=1.2)


def test_frequency_counts_primary_records_only(client):
    for card in client.get("/api/opportunities").json()["opportunities"]:
        assert card["frequency"]["records"] == card["evidence"]["feedback_records"]
        assert card["confidence"]["checks"]["evidence"] == (card["frequency"]["records"] >= 5)


def test_build_cache_matches_fresh_computation_and_is_reused(client):
    from app.config import database_path
    with sqlite3.connect(database_path()) as db:
        first = opportunities.build(db)
        assert opportunities.build(db) is first                                   # reused, not recomputed
        fresh = opportunities._build(db, opportunities.DEFAULT_LINK)
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(fresh, sort_keys=True, default=str)


def test_routes_never_modify_the_cached_opportunities(client, events_db, monkeypatch):
    import copy
    from app.config import database_path
    monkeypatch.setenv("GIST_EVENTS_DB_PATH", str(events_db[0]))
    with sqlite3.connect(database_path()) as db:
        cached = opportunities.build(db)
    before = copy.deepcopy(cached)
    oid = cached["opportunities"][0]["id"]
    for path in ("/api/opportunities", f"/api/opportunities/{oid}", "/api/priorities", "/api/experiments",
                 f"/api/experiments/{oid}", "/api/evidence", "/api/evidence?q=invite"):
        assert client.get(path).status_code == 200, path
    client.put(f"/api/priorities/{oid}", json={"strategic": "high", "effort": "S", "note": "x"})
    assert cached == before


def test_cache_key_follows_tickets_and_documents(client):
    from app.config import database_path
    with sqlite3.connect(database_path()) as db:
        first = opportunities.build(db)
        cols = [r[1] for r in db.execute("PRAGMA table_info(support_tickets)")]
        row = dict(zip(cols, db.execute("SELECT * FROM support_tickets LIMIT 1").fetchone()))
        row["id"] = "SUP-ZZZ-CACHE"
        db.execute(f"INSERT INTO support_tickets ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
        db.commit()
        assert opportunities.build(db) is not first
