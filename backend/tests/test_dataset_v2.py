"""Version isolation and realistic-data invariants; all tests are offline."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.database import connection
from app.main import app
from app.rag.ingest import Source, upsert_source
from scripts.audit_v2 import audit
from scripts.generate_v2 import ROOT, generate
from scripts.seed import seed


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v2_generation_is_reproducible_and_does_not_touch_v1(tmp_path: Path):
    v1 = ROOT / "data/feedback.jsonl"
    before = _digest(v1)
    left_data, left_evals = tmp_path / "left/data", tmp_path / "left/evals"
    right_data, right_evals = tmp_path / "right/data", tmp_path / "right/evals"
    counts = generate(left_data, left_evals)
    assert counts == {"feedback": 400, "tickets": 120, "prds": 6, "release_notes": 8, "annotations": 534}
    generate(right_data, right_evals)
    for relative in ("feedback.jsonl", "support-tickets.jsonl", "prds/prd-01.md", "release-notes/release-01.md"):
        assert _digest(left_data / relative) == _digest(right_data / relative)
    assert _digest(left_evals / "questions.json") == _digest(right_evals / "questions.json")
    assert _digest(v1) == before
    with pytest.raises(FileExistsError):
        generate(left_data, left_evals)


def test_v2_annotations_benchmark_and_quality():
    result = audit()
    assert result["feedback"] == 400 and result["tickets"] == 120
    assert result["exact_duplicate_records"] <= 12
    assert result["near_duplicate_pairs"] <= 12
    assert result["multi_issue_feedback"] >= 30
    assert result["ambiguous_feedback"] >= 25
    assert result["timeline_errors"] == []
    questions = json.loads((ROOT / "evals/v2/questions.json").read_text())["questions"]
    assert len(questions) == 50
    assert Counter(item["evaluation_category"] for item in questions) == {
        "direct": 15, "semantic": 15, "multi_source": 10,
        "contradiction_ambiguity": 5, "unanswerable": 5,
    }
    assert len({item["id"] for item in questions}) == 50
    annotations = [json.loads(line) for line in (ROOT / "evals/v2/source_annotations.jsonl").read_text().splitlines()]
    source_ids = {item["source_id"] for item in annotations}
    assert len(source_ids) == 534
    assert all(set(item["relevant_source_ids"]) <= source_ids for item in questions)
    assert all(set(item["representative_source_ids"]) <= set(item["relevant_source_ids"]) for item in questions)
    assert all(item["dataset_version"] == "v2" for item in questions)


def test_versioned_seed_protects_existing_db_and_indexes_only_public_content(tmp_path: Path, monkeypatch):
    path_v2 = tmp_path / "v2.sqlite3"
    path_v1 = tmp_path / "v1.sqlite3"
    seed("v2", path=path_v2)
    seed("v1", path=path_v1)
    with pytest.raises(FileExistsError):
        seed("v2", path=path_v2)
    with pytest.raises(ValueError):
        seed("v1", path=path_v2, replace=True)
    with connection(path_v2) as db:
        assert db.execute("SELECT value FROM dataset_meta WHERE key='version'").fetchone()[0] == "v2"
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 534
        assert db.execute("SELECT COUNT(*) FROM embeddings WHERE model='text-embedding-3-small'").fetchone()[0] == 0
        assert db.execute("SELECT title FROM sources WHERE id='V2-FB-0001'").fetchone()[0] == "Feedback V2-FB-0001"
        assert db.execute("SELECT COUNT(*) FROM sources WHERE path LIKE '%evals/%'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sources WHERE id LIKE 'FB-%'").fetchone()[0] == 0
    with connection(path_v1) as db:
        assert db.execute("SELECT COUNT(*) FROM sources WHERE id LIKE 'V2-%'").fetchone()[0] == 0
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    monkeypatch.setenv("GIST_DB_PATH", str(path_v2))
    with TestClient(app) as client:
        status = client.get("/api/rag/status").json()
        assert status["dataset_version"] == "v2"
        assert client.get("/api/records?category=Unclear").json()["total"] > 0
        search = client.get("/api/search", params={"query": "invoice seats", "segment": "Enterprise", "product_area": "Billing", "limit": 10})
        assert search.status_code == 200
        assert all(item["segment"] == "Enterprise" and item["product_area"] == "Billing" for item in search.json())
    monkeypatch.setenv("GIST_DB_PATH", str(path_v1))
    with pytest.raises(RuntimeError, match="contains v1"):
        with connection():
            pass
    monkeypatch.setenv("GIST_DB_PATH", str(path_v2))
    with connection(path_v2) as db, db:
        db.execute("UPDATE dataset_meta SET value='outdated' WHERE key='source_sha256'")
    with pytest.raises(RuntimeError, match="source files changed"):
        with connection():
            pass


def test_changed_source_invalidates_existing_vectors(tmp_path: Path):
    path = tmp_path / "v2.sqlite3"
    seed("v2", path=path)
    with connection(path) as db, db:
        first = db.execute("SELECT id FROM chunks WHERE source_id='V2-FB-0002'").fetchone()[0]
        db.execute("INSERT INTO embeddings VALUES (?,?,?,?)", (first, "text-embedding-3-small", 3, np.ones(3, dtype=np.float32).tobytes()))
        upsert_source(db, Source("V2-FB-0002", "Feedback V2-FB-0002", "feedback", "Changed synthetic text", "data/v2/feedback.jsonl#V2-FB-0002"))
        assert db.execute("SELECT COUNT(*) FROM embeddings WHERE model='text-embedding-3-small' AND chunk_id LIKE 'V2-FB-0002:%'").fetchone()[0] == 0
