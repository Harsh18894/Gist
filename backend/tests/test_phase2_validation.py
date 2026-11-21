"""Offline validation gates for the frozen v2 corpus and HTTP behavior."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from scripts.freeze_v2_split import ROOT, verify
from scripts import seed as seed_module
from scripts.seed import seed


def test_frozen_split_hashes_and_stratification():
    manifest = verify()
    questions = {item["id"]: item for item in json.loads((ROOT / "evals/v2/questions.json").read_text())["questions"]}
    assert len(manifest["development_ids"]) == 30
    assert len(manifest["heldout_test_ids"]) == 20
    assert not set(manifest["development_ids"]) & set(manifest["heldout_test_ids"])
    assert set(manifest["development_ids"] + manifest["heldout_test_ids"]) == set(questions)
    assert manifest["maximum_cross_split_similarity"]["normalized_sequence_similarity"] < .72


def test_v2_api_filters_errors_and_source_resolution(tmp_path: Path, monkeypatch):
    path = tmp_path / "v2.sqlite3"
    seed("v2", path=path)
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/stats").json()["feedback_count"] == 400
        assert client.get("/api/rag/status").json()["dataset_version"] == "v2"
        records = client.get("/api/records", params={"category": "Unclear", "page_size": 5}).json()
        assert records["total"] > 0 and len(records["items"]) == 5
        assert all(row["issue_category"] == "Unclear" for row in records["items"])
        assert client.get("/api/records/V2-FB-0001").status_code == 200
        assert client.get("/api/records/not-here").status_code == 404
        assert client.get("/api/sources/not-here").status_code == 404
        response = client.get("/api/search", params={"query": "invoice seats", "strategy": "keyword",
                                                     "segment": "Enterprise", "product_area": "Billing",
                                                     "from_date": "2025-01-01", "to_date": "2025-12-31", "limit": 10})
        assert response.status_code == 200
        hits = response.json()
        assert hits and all(hit["segment"] == "Enterprise" and hit["product_area"] == "Billing" for hit in hits)
        assert all("2025-01-01" <= hit["source_date"] <= "2025-12-31" for hit in hits)
        for hit in hits:
            source = client.get(f"/api/sources/{hit['source_id']}")
            assert source.status_code == 200 and source.json()["id"] == hit["source_id"]
        assert client.get("/api/search", params={"query": "   "}).json() == []
        for params in ({"query": "x"}, {"query": "invoice", "segment": "invalid"},
                       {"query": "invoice", "from_date": "2025-12-01", "to_date": "2025-01-01"}):
            result = client.get("/api/search", params=params)
            assert result.status_code == 422 and result.json()["error"]["code"] == "invalid_request"
        assert client.post("/api/ask", json={"question": "invoice seats", "mode": "openai"}).status_code == 403
        assert client.get("/api/usage").json()["calls"] == 0


def test_missing_source_files_abort_before_database_creation(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(seed_module, "ROOT", tmp_path)
    target = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError, match="Incomplete v2 source dataset"):
        seed_module.seed("v2", path=target)
    assert not target.exists()
