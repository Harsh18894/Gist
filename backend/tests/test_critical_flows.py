"""Characterization tests that lock in the current behaviour of Gist's critical flows.

These tests pin exact outputs (IDs, ranks, scores, payload shapes) observed on the
deterministic Pulse v1 corpus. A failure here means user-visible behaviour changed;
update the expectation only when that change is intended.

Every test runs offline against temporary databases. No test enables paid mode,
and the shared spend ledger is redirected to a temporary file.
"""
import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.database import connection, initialize
from app.main import app
from app.rag import provider
from app.rag.ingest import (DEMO_DIMENSIONS, DEMO_MODEL, Source, chunk_text, demo_vector,
                            import_file, upsert_source)
from app.rag.provider import EMBED_MODEL, PaidApiDisabled, index_missing_embeddings
from app.rag.retrieval import Filters, hybrid_search, keyword_search
from scripts.seed import seed

ROOT = Path(__file__).resolve().parents[2]
V1_FINGERPRINT = "482a605903f9720781f66bed39c923edfe759769c169cd1e2309c260403b89e7"
PAID_ENV = ("GIST_ENABLE_PAID_API", "GIST_PAID_EVAL_APPROVED", "OPENAI_API_KEY",
            "GIST_MAX_API_SPEND_USD", "GIST_LLM_MODEL", "GIST_DATASET_VERSION")


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory) -> Path:
    """One read-only seeded v1 database shared by the read-only API tests."""
    path = tmp_path_factory.mktemp("flows") / "v1.sqlite3"
    seed("v1", path=path)
    return path


@pytest.fixture
def offline_env(monkeypatch, tmp_path):
    for name in PAID_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIST_SPEND_DB_PATH", str(tmp_path / "spend.sqlite3"))


@pytest.fixture
def api(seeded_db, offline_env, monkeypatch):
    monkeypatch.setenv("GIST_DB_PATH", str(seeded_db))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def fresh_db(offline_env, monkeypatch, tmp_path) -> Path:
    """A writable seeded v1 database for tests that import or embed."""
    path = tmp_path / "fresh.sqlite3"
    seed("v1", path=path)
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    return path


# --------------------------------------------------------------------------- seeding

def test_seed_builds_v1_index_with_fixed_counts_and_fingerprint(seeded_db: Path):
    with sqlite3.connect(seeded_db) as db:
        assert db.execute("SELECT kind, COUNT(*) FROM sources GROUP BY kind ORDER BY kind").fetchall() == [
            ("feedback", 400), ("prd", 6), ("release_note", 8), ("support_ticket", 120)]
        assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 534
        assert db.execute("SELECT MAX(ordinal) FROM chunks").fetchone()[0] == 0  # one chunk per source
        assert db.execute("SELECT model, COUNT(*) FROM embeddings GROUP BY model").fetchall() == [(DEMO_MODEL, 534)]
        assert db.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0] == 534
        assert dict(db.execute("SELECT key, value FROM dataset_meta")) == {
            "version": "v1", "source_sha256": V1_FINGERPRINT}


def test_seed_source_metadata_mapping(seeded_db: Path):
    with sqlite3.connect(seeded_db) as db:
        rows = {row[0]: row[1:] for row in db.execute(
            "SELECT id, title, kind, path, source_date, segment, product_area FROM sources "
            "WHERE id IN ('FB-0001', 'SUP-0001', 'release-03')")}
    assert rows == {
        "FB-0001": ("Billing confusion feedback FB-0001", "feedback", "data/feedback.jsonl#FB-0001",
                    "2025-01-05", "Individual", "Billing"),
        "SUP-0001": ("Help with seat billing", "support_ticket", "data/support-tickets.jsonl#SUP-0001",
                     "2025-01-11", "SMB", "Billing"),
        "release-03": ("Pulse release 03: Notification digest update", "release_note",
                       "data/release-notes/release-03.md", "2025-04-05", None, "Notifications"),
    }


def test_seed_refuses_overwrite_and_cross_version_replace(seeded_db: Path, tmp_path: Path):
    with pytest.raises(FileExistsError):
        seed("v1", path=seeded_db)
    with pytest.raises(ValueError, match="Refusing to replace v1 database with v2 data"):
        seed("v2", path=seeded_db, replace=True)
    with pytest.raises(ValueError, match="Dataset must be v1 or v2"):
        seed("v3", path=tmp_path / "x.sqlite3")


def test_seed_replace_clears_paid_vectors_and_imported_sources(fresh_db: Path, tmp_path: Path):
    note = tmp_path / "note.txt"
    note.write_text("A fictional imported note about kanban swimlanes.")
    with connection(fresh_db) as db:
        with db:
            import_file(db, note)
            db.execute("INSERT INTO embeddings VALUES ('FB-0001:000', ?, 1, ?)",
                       (EMBED_MODEL, np.ones(1, dtype=np.float32).tobytes()))
    seed("v1", path=fresh_db, replace=True)
    with sqlite3.connect(fresh_db) as db:
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 534
        assert db.execute("SELECT COUNT(*) FROM embeddings WHERE model = ?", (EMBED_MODEL,)).fetchone()[0] == 0


def test_connection_rejects_version_mismatch_and_changed_fingerprint(fresh_db: Path, monkeypatch):
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    with pytest.raises(RuntimeError, match="Selected v2, but .* contains v1"):
        with connection():
            pass
    monkeypatch.delenv("GIST_DATASET_VERSION")
    with sqlite3.connect(fresh_db) as db:
        db.execute("UPDATE dataset_meta SET value = 'stale' WHERE key = 'source_sha256'")
    with pytest.raises(RuntimeError, match="source files changed since indexing"):
        with connection():
            pass


# ----------------------------------------------------------------- chunking & vectors

def test_chunk_boundaries_with_default_window():
    words = " ".join(str(i) for i in range(300))
    chunks = [(c.split()[0], c.split()[-1], len(c.split())) for c in chunk_text(words)]
    assert chunks == [("0", "139", 140), ("115", "254", 140), ("230", "299", 70)]
    assert chunk_text("   \n\t ") == []
    for bad in ({"max_words": 0}, {"max_words": 5, "overlap_words": 5}, {"overlap_words": -1}):
        with pytest.raises(ValueError):
            chunk_text("a b c", **bad)


def test_demo_vector_is_deterministic_hash_projection():
    vector = demo_vector("CRM sync failure")
    assert vector.dtype == np.float32 and vector.shape == (DEMO_DIMENSIONS,)
    assert np.nonzero(vector)[0].tolist() == [67, 115, 200]
    assert np.allclose(vector[[67, 115, 200]], [1 / np.sqrt(3), -1 / np.sqrt(3), -1 / np.sqrt(3)])
    assert np.array_equal(vector, demo_vector("crm SYNC, failure!"))  # case and punctuation insensitive
    assert not np.any(demo_vector("the and of what a"))  # stopwords and 1-char tokens only


def test_stored_demo_vectors_match_chunk_text(seeded_db: Path):
    with sqlite3.connect(seeded_db) as db:
        rows = db.execute("""SELECT c.content, e.dimensions, e.vector FROM chunks c
            JOIN embeddings e ON e.chunk_id = c.id AND e.model = ?
            WHERE c.id IN ('FB-0001:000', 'SUP-0071:000', 'release-03:000')""", (DEMO_MODEL,)).fetchall()
    assert len(rows) == 3
    for content, dimensions, blob in rows:
        assert dimensions == DEMO_DIMENSIONS
        assert np.array_equal(np.frombuffer(blob, dtype=np.float32), demo_vector(content))


def test_chunk_text_is_title_prefixed(seeded_db: Path):
    with sqlite3.connect(seeded_db) as db:
        content, words = db.execute("SELECT content, word_count FROM chunks WHERE id = 'FB-0001:000'").fetchone()
    assert content.startswith("Billing confusion feedback FB-0001. ")
    assert words == len(content.split())


# ------------------------------------------------------------------------- ingestion

def test_import_example_files_via_cli(fresh_db: Path, tmp_path: Path):
    env = {**os.environ, "GIST_DB_PATH": str(fresh_db), "PYTHONPATH": str(ROOT / "backend")}
    commands = [
        (["data/examples/example.csv"], "Imported 2 synthetic sources in 2 chunks."),
        (["data/examples/example.md"], "Imported 1 synthetic sources in 1 chunks."),
        (["data/examples/example.txt", "--segment", "SMB", "--product-area", "Billing",
          "--source-date", "2025-09-01"], "Imported 1 synthetic sources in 1 chunks."),
    ]
    for args, expected in commands:
        result = subprocess.run([sys.executable, "backend/scripts/rag.py", "import", *args],
                                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        assert result.stdout.strip() == expected
    examples = ROOT / "data/examples"
    csv_id = hashlib.sha256(str((examples / "example.csv").resolve()).encode()).hexdigest()[:12]
    md_id = hashlib.sha256(str((examples / "example.md").resolve()).encode()).hexdigest()[:12]
    txt_id = hashlib.sha256(str((examples / "example.txt").resolve()).encode()).hexdigest()[:12]
    with sqlite3.connect(fresh_db) as db:
        rows = {row[0]: row[1:] for row in db.execute(
            "SELECT id, title, kind, source_date, segment, product_area FROM sources "
            "WHERE kind IN ('csv', 'markdown', 'text') ORDER BY id")}
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 538
    assert rows == {
        f"csv-{csv_id}-0001": ("Synthetic CRM retry note", "csv", "2025-10-01", "Enterprise", "Integrations"),
        f"csv-{csv_id}-0002": ("Synthetic digest note", "csv", "2025-10-02", "SMB", "Notifications"),
        f"file-{md_id}": ("Synthetic shared template interview", "markdown", "2025-10-03", "Mid-market", "Collaboration"),
        f"file-{txt_id}": ("example", "text", "2025-09-01", "SMB", "Billing"),
    }


def test_import_metadata_precedence_and_csv_rules(fresh_db: Path, tmp_path: Path):
    path = tmp_path / "rows.csv"
    path.write_text("subject,description,date,segment\n"
                    "Row with values,First fictional body,2025-03-04T10:00:00Z,SMB\n"
                    ",Second fictional body,,\n"
                    "Blank body row,,2025-01-01,SMB\n")
    with connection() as db:
        with db:
            assert import_file(db, path, segment="Enterprise", product_area="Billing",
                               source_date="2025-02-02") == (2, 2)
        rows = db.execute("SELECT title, source_date, segment, product_area, path FROM sources "
                          "WHERE kind = 'csv' ORDER BY id").fetchall()
    # CSV values win over CLI fallbacks; timestamps are truncated to dates; blank bodies are skipped
    # but still consume a row number.
    assert [tuple(r) for r in rows] == [
        ("Row with values", "2025-03-04", "SMB", "Billing", f"{path.resolve()}#row=1"),
        ("rows row 2", "2025-02-02", "Enterprise", "Billing", f"{path.resolve()}#row=2"),
    ]


def test_import_rejections(fresh_db: Path, tmp_path: Path):
    cases = {
        "notes.pdf": ("x", "Supported formats are CSV, TXT, and Markdown."),
        "no-text.csv": ("title,summary\na,b\n", "CSV needs a text, content, feedback_text, or description column."),
        "bad-date.txt": ("Date: 2025-13-40\nFictional body", "month must be in 1..12"),
        "empty.md": ("   \n", "has no text"),
    }
    with connection() as db:
        for name, (body, message) in cases.items():
            path = tmp_path / name
            path.write_text(body)
            with pytest.raises(ValueError, match=message):
                with db:
                    import_file(db, path)
        big = tmp_path / "big.txt"
        big.write_bytes(b"a " * 2_500_001)
        with pytest.raises(ValueError, match="exceeds the 5 MB local limit"):
            import_file(db, big)
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 534


def test_reimport_preserves_or_invalidates_vectors(fresh_db: Path, tmp_path: Path):
    path = tmp_path / "note.md"
    path.write_text("# Swimlane note\nSegment: SMB\n\nFictional swimlane feedback.")
    paid = np.ones(4, dtype=np.float32).tobytes()
    with connection() as db:
        with db:
            import_file(db, path)
        chunk_id = db.execute("SELECT id FROM chunks WHERE content LIKE 'Swimlane note.%'").fetchone()[0]
        with db:
            db.execute("INSERT INTO embeddings VALUES (?, ?, 4, ?)", (chunk_id, EMBED_MODEL, paid))
            import_file(db, path)  # identical: no-op
            import_file(db, path, product_area="Dashboard")  # metadata-only: keeps vectors
        assert db.execute("SELECT product_area FROM sources WHERE id = ?", (chunk_id[:-4],)).fetchone()[0] == "Dashboard"
        assert db.execute("SELECT COUNT(*) FROM embeddings WHERE chunk_id = ?", (chunk_id,)).fetchone()[0] == 2
        path.write_text("# Swimlane note\nSegment: SMB\n\nRevised fictional swimlane feedback.")
        with db:
            import_file(db, path)  # text change: re-chunks and drops the paid vector
        assert [row[0] for row in db.execute("SELECT model FROM embeddings WHERE chunk_id = ?", (chunk_id,))] == [DEMO_MODEL]
        assert db.execute("SELECT COUNT(*) FROM chunk_fts WHERE chunk_id = ?", (chunk_id,)).fetchone()[0] == 1


def test_imported_source_is_searchable_and_resolvable(fresh_db: Path, tmp_path: Path):
    path = tmp_path / "kanban.txt"
    path.write_text("Fictional teams want kanban swimlanes grouped by assignee.")
    with connection() as db:
        with db:
            import_file(db, path, segment="SMB", product_area="Dashboard", source_date="2025-09-09")
    with TestClient(app) as client:
        hits = client.get("/api/search", params={"query": "kanban swimlanes"}).json()
        assert hits[0]["title"] == "kanban" and hits[0]["kind"] == "text"
        source = client.get(f"/api/sources/{hits[0]['source_id']}").json()
    assert source["content"] == "Fictional teams want kanban swimlanes grouped by assignee."
    assert (source["segment"], source["product_area"], source["source_date"]) == ("SMB", "Dashboard", "2025-09-09")


# ------------------------------------------------------------------ paid embedding guard

def test_paid_embedding_refuses_without_approval_and_makes_no_request(fresh_db: Path, monkeypatch):
    class NoNetwork:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("network must not be used")

    monkeypatch.setattr(provider.httpx, "Client", NoNetwork)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")  # a key alone is not approval
    with connection() as db:
        with pytest.raises(PaidApiDisabled, match="Paid AI is disabled"):
            index_missing_embeddings(db)
        monkeypatch.setenv("GIST_ENABLE_PAID_API", "true")
        with pytest.raises(PaidApiDisabled, match="Paid AI is disabled"):
            index_missing_embeddings(db)
        monkeypatch.setenv("GIST_PAID_EVAL_APPROVED", "true")
        with pytest.raises(PaidApiDisabled, match="spending cap"):
            index_missing_embeddings(db)
        assert db.execute("SELECT COUNT(*) FROM embeddings WHERE model = ?", (EMBED_MODEL,)).fetchone()[0] == 0


def test_embed_openai_cli_requires_confirmation(fresh_db: Path):
    env = {**os.environ, "GIST_DB_PATH": str(fresh_db)}
    result = subprocess.run([sys.executable, "backend/scripts/rag.py", "embed-openai"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert "Paid indexing needs --confirm-paid after explicit approval." in result.stderr
    result = subprocess.run([sys.executable, "backend/scripts/rag.py", "embed-openai", "--confirm-paid"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert "requires GIST_DATASET_VERSION=v2 and the standard v2 database path" in result.stderr


def test_index_missing_embeddings_batches_by_16_and_is_resumable(fresh_db: Path, monkeypatch):
    calls: list[tuple[int, str]] = []

    def fake_embed(_db, texts, *, request_key=None):
        calls.append((len(texts), request_key))
        return [np.full(3, 0.5, dtype=np.float32) for _ in texts], {}

    monkeypatch.setattr(provider, "embed", fake_embed)
    with connection() as db:
        with db:
            db.execute("DELETE FROM sources WHERE id NOT IN (SELECT id FROM sources ORDER BY id LIMIT 20)")
        assert index_missing_embeddings(db) == 20
        assert [size for size, _ in calls] == [16, 4]
        assert all(key.startswith(f"embed:v1:{EMBED_MODEL}:") for _, key in calls)
        assert db.execute("SELECT COUNT(*) FROM embeddings WHERE model = ?", (EMBED_MODEL,)).fetchone()[0] == 20
        assert index_missing_embeddings(db) == 0
    assert len(calls) == 2


# ---------------------------------------------------------------------------- search

def test_search_strategy_rankings_are_stable(api):
    expected_ids = ["SUP-0071:000", "SUP-0092:000", "SUP-0095:000", "SUP-0103:000", "SUP-0117:000"]
    for strategy, keyword, semantic in (("keyword", True, False), ("semantic", False, True), ("hybrid", True, True)):
        hits = api.get("/api/search", params={"query": "CRM sync failure", "strategy": strategy}).json()
        assert [hit["chunk_id"] for hit in hits] == expected_ids
        assert [hit["keyword_rank"] for hit in hits] == ([1, 2, 3, 4, 5] if keyword else [None] * 5)
        assert [hit["semantic_rank"] for hit in hits] == ([1, 2, 3, 4, 5] if semantic else [None] * 5)
        if strategy == "hybrid":
            assert [hit["score"] for hit in hits] == pytest.approx([2 / (60 + rank) for rank in range(1, 6)])
        else:
            assert [hit["score"] for hit in hits] == pytest.approx([1 / rank for rank in range(1, 6)])


def test_search_hit_shape(api):
    hit = api.get("/api/search", params={"query": "CRM sync failure", "limit": 1}).json()[0]
    assert set(hit) == {"source_id", "chunk_id", "title", "kind", "path", "source_date", "segment",
                        "product_area", "snippet", "score", "keyword_rank", "semantic_rank"}
    assert hit["source_id"] == "SUP-0071" and hit["kind"] == "support_ticket"
    assert hit["path"] == "data/support-tickets.jsonl#SUP-0071"


def test_search_filters_are_inclusive_and_ranked(api):
    hits = api.get("/api/search", params={
        "query": "notification digest", "segment": "Enterprise", "product_area": "Notifications",
        "from_date": "2025-05-01", "to_date": "2025-08-31", "limit": 10}).json()
    assert [(h["source_id"], h["source_date"]) for h in hits] == [
        ("SUP-0045", "2025-05-05"), ("SUP-0091", "2025-08-30"), ("SUP-0061", "2025-06-15"),
        ("FB-0140", "2025-05-04"), ("FB-0144", "2025-05-07"), ("FB-0184", "2025-06-10"),
        ("FB-0145", "2025-05-08"), ("FB-0192", "2025-06-17"), ("FB-0278", "2025-08-30"),
        ("FB-0148", "2025-05-11")]
    same_day = api.get("/api/search", params={"query": "digest", "from_date": "2025-04-05",
                                              "to_date": "2025-04-05", "limit": 20}).json()
    assert same_day and {h["source_date"] for h in same_day} == {"2025-04-05"}


def test_search_stopword_only_query_returns_nothing(api):
    for strategy in ("keyword", "semantic", "hybrid"):
        assert api.get("/api/search", params={"query": "the and of what", "strategy": strategy}).json() == []


def test_search_validation_errors(api):
    error = {"error": {"code": "invalid_request", "message": "Check the supplied query parameters."}}
    for params in ({}, {"query": "ab"}, {"query": "x" * 501}, {"query": "crm", "strategy": "vector"},
                   {"query": "crm", "limit": 0}, {"query": "crm", "limit": 21},
                   {"query": "crm", "product_area": "Search"}, {"query": "crm", "from_date": "2025-02-30"}):
        response = api.get("/api/search", params=params)
        assert (response.status_code, response.json()) == (422, error)
    response = api.get("/api/search", params={"query": "crm", "from_date": "2025-02-01", "to_date": "2025-01-01"})
    assert (response.status_code, response.json()) == (422, {"error": {
        "code": "invalid_request", "message": "from_date must be on or before to_date."}})


def test_hybrid_dedupes_sources_and_boosts_asked_date(seeded_db: Path, monkeypatch):
    monkeypatch.setenv("GIST_DB_PATH", str(seeded_db))
    with connection() as db:
        hits = hybrid_search(db, "What did Pulse release on 2025-04-05?", Filters(), limit=50)
        keyword_only = keyword_search(db, "What did Pulse release on 2025-04-05?", Filters())
    assert len({h.source_id for h in hits}) == len(hits)
    assert hits[0].source_id == "release-03" and hits[0].source_date == "2025-04-05"
    assert hits[0].score > 0.1  # date-match boost
    assert all(h.keyword_rank is not None for h in hits)  # demo mode requires a keyword match
    assert len(hits) <= len(keyword_only)


# ------------------------------------------------------------------------------- ask

def test_ask_demo_returns_sources_only(api):
    response = api.post("/api/ask", json={"question": "What did Pulse release on 2025-04-05?"})
    body = response.json()
    assert response.status_code == 200
    assert {k: body[k] for k in ("answer", "status", "mode", "citations", "input_tokens",
                                 "output_tokens", "estimated_cost_usd")} == {
        "answer": "Retrieved sources for review. No answer was generated.", "status": "sources_only",
        "mode": "demo", "citations": [], "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
    assert [s["source_id"] for s in body["retrieved_sources"]] == [
        "release-03", "release-04", "release-05", "release-06", "release-08"]
    assert isinstance(body["latency_ms"], int)
    crm = api.post("/api/ask", json={"question": "CRM sync failure"}).json()
    assert [s["source_id"] for s in crm["retrieved_sources"]] == [
        "SUP-0071", "SUP-0092", "SUP-0095", "SUP-0103", "SUP-0117"]


@pytest.mark.parametrize("question", ["What is Pulse revenue?", "zzzz qqqq",
                                      "Which engineer broke the CRM sync?"])
def test_ask_demo_insufficient_evidence(api, question):
    body = api.post("/api/ask", json={"question": question}).json()
    assert body["status"] == "insufficient_evidence" and body["mode"] == "demo"
    assert body["answer"].startswith("I don't have enough evidence in the indexed Pulse sources")
    assert body["citations"] == []


def test_ask_openai_mode_is_blocked_without_vectors(api, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no paid call expected")

    monkeypatch.setattr(provider, "_post", forbidden)
    response = api.post("/api/ask", json={"question": "CRM sync failure", "mode": "openai"})
    assert (response.status_code, response.json()) == (403, {"error": {
        "code": "paid_api_disabled",
        "message": "OpenAI embeddings are incomplete. Run the guarded embedding command after approval."}})


def test_ask_validation_errors(api):
    for body in ({}, {"question": "ab"}, {"question": "x" * 501}, {"question": "crm sync", "mode": "gpt"},
                 {"question": "crm sync", "segment": "Startup"},
                 {"question": "crm sync", "from_date": "2025-03-01", "to_date": "2025-02-01"}):
        response = api.post("/api/ask", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


# ------------------------------------------------------------ sources, status, usage

def test_source_detail_and_not_found(api):
    source = api.get("/api/sources/release-03").json()
    assert {k: v for k, v in source.items() if k != "content"} == {
        "id": "release-03", "title": "Pulse release 03: Notification digest update", "kind": "release_note",
        "path": "data/release-notes/release-03.md", "source_date": "2025-04-05", "segment": None,
        "product_area": "Notifications"}
    assert source["content"] == (ROOT / "data/release-notes/release-03.md").read_text()
    response = api.get("/api/sources/missing")
    assert (response.status_code, response.json()) == (404, {"error": {"code": "not_found", "message": "Source not found."}})


def test_rag_status_payload(api, monkeypatch):
    expected = {"dataset_version": "v1", "source_sha256": V1_FINGERPRINT, "sources": 534, "chunks": 534,
                "openai_vectors": 0, "paid_api_enabled": False, "llm_model": "gpt-6-luna"}
    assert api.get("/api/rag/status").json() == expected
    monkeypatch.setenv("GIST_ENABLE_PAID_API", "true")
    monkeypatch.setenv("GIST_PAID_EVAL_APPROVED", "true")
    assert api.get("/api/rag/status").json()["paid_api_enabled"] is False  # vectors incomplete


def test_usage_payload_on_empty_ledgers(api):
    assert api.get("/api/usage").json() == {
        "calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0, "total_latency_ms": 0,
        "project_committed_or_reserved_usd": 0.0, "project_uncertain_requests": 0,
        "project_allocation_usd": 0.5, "project_input_tokens": 0, "project_output_tokens": 0}


def test_unseeded_database_status(offline_env, monkeypatch, tmp_path):
    path = tmp_path / "empty.sqlite3"
    with connection(path) as db:
        initialize(db)
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    with TestClient(app) as client:
        status = client.get("/api/rag/status").json()
        assert (status["dataset_version"], status["sources"], status["chunks"]) == ("unseeded", 0, 0)
        assert client.post("/api/ask", json={"question": "CRM sync failure"}).json()["status"] == "insufficient_evidence"


def test_cors_allows_only_configured_origin(api):
    preflight = {"Access-Control-Request-Method": "GET"}
    allowed = api.options("/api/health", headers={"Origin": "http://localhost:3000", **preflight})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    denied = api.options("/api/health", headers={"Origin": "http://evil.example", **preflight})
    assert "access-control-allow-origin" not in denied.headers
