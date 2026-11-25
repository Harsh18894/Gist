"""Every API failure returns {"error": {"code", "message"}} with CORS headers.

No test here makes a network call: paid paths use fakes.
"""
import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.database import connection, initialize
from app.errors import ConfigurationError, DatasetStateError
from app.rag import provider, service
from app.rag.ingest import Source, demo_vector, upsert_source
from app.rag.provider import EMBED_MODEL, PaidApiDisabled, PaidRequestRejected, ProviderError
from scripts.seed import seed

ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def v1_db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "v1.sqlite3"
    seed("v1", path=path)
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    return path


@pytest.fixture
def api():
    # raise_server_exceptions=False: if the catch-all ever regresses, the test
    # sees Starlette's plain 500 instead of an exception escaping the client.
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def _assert_structured(response, status: int, code: str, *, secret: str | None = None) -> dict:
    assert response.status_code == status
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    if secret is not None:
        assert secret not in response.text
    return body["error"]


# ------------------------------------------------------------ dataset/config: 503

def test_version_mismatch_is_503_without_paths(v1_db: Path, api, monkeypatch):
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    for path in ("/api/stats", "/api/records", "/api/rag/status", "/api/usage"):
        error = _assert_structured(api.get(path, headers=ORIGIN), 503, "dataset_mismatch", secret=str(v1_db.parent))
        assert "contains v1" in error["message"] and "GIST_DB_PATH" in error["message"]
    _assert_structured(api.post("/api/ask", json={"question": "CRM sync"}, headers=ORIGIN),
                               503, "dataset_mismatch", secret=str(v1_db.parent))


def test_stale_index_is_503_with_reseed_command(v1_db: Path, api):
    with sqlite3.connect(v1_db) as db:
        db.execute("UPDATE dataset_meta SET value = 'stale' WHERE key = 'source_sha256'")
    error = _assert_structured(api.get("/api/search", params={"query": "CRM sync"}, headers=ORIGIN),
                               503, "index_stale", secret=str(v1_db.parent))
    assert "seed.py --dataset v1 --replace" in error["message"]


def test_legacy_database_read_as_v2_is_503(tmp_path: Path, api, monkeypatch):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sources (id TEXT)")
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    _assert_structured(api.get("/api/stats", headers=ORIGIN), 503, "legacy_database", secret=str(tmp_path))


def test_invalid_dataset_version_is_503(v1_db: Path, api, monkeypatch):
    monkeypatch.setenv("GIST_DATASET_VERSION", "v3")
    error = _assert_structured(api.get("/api/stats", headers=ORIGIN), 503, "invalid_configuration")
    assert "v1 or v2" in error["message"]


def test_typed_errors_keep_their_builtin_bases():
    # Scripts and older tests catch RuntimeError / ValueError; keep both working.
    assert issubclass(DatasetStateError, RuntimeError)
    assert issubclass(ConfigurationError, ValueError)
    assert issubclass(PaidRequestRejected, PaidApiDisabled) and issubclass(PaidRequestRejected, ValueError)


# ----------------------------------------------------------------- catch-all: 500

def test_unexpected_error_is_structured_logged_and_redacted(v1_db: Path, api, monkeypatch, caplog):
    def boom(_db):
        raise KeyError("internal detail /very/secret/path")

    monkeypatch.setattr(main, "get_stats", boom)
    with caplog.at_level(logging.ERROR, logger="gist.api"):
        error = _assert_structured(api.get("/api/stats", headers=ORIGIN), 500, "internal_error",
                                   secret="/very/secret/path")
    assert error["message"] == "Gist hit an unexpected error. Check the API logs."
    assert any("GET /api/stats" in record.getMessage() and record.exc_info for record in caplog.records)


def test_success_and_known_errors_are_unchanged(v1_db: Path, api):
    assert api.get("/api/health").json() == {"status": "ok", "app": "Gist"}
    _assert_structured(api.get("/api/sources/missing", headers=ORIGIN), 404, "not_found")
    _assert_structured(api.get("/api/search", params={"query": "x"}, headers=ORIGIN), 422, "invalid_request")


# ------------------------------------------------------------- Ask openai mode

@pytest.fixture
def paid_ready_db(tmp_path: Path, monkeypatch) -> Path:
    """A tiny unversioned DB whose chunks all have EMBED_MODEL vectors."""
    path = tmp_path / "paid.sqlite3"
    with connection(path) as db:
        initialize(db)
        with db:
            upsert_source(db, Source("release-03", "Notification digest update", "release_note",
                                     "The notification digest changed on 2025-04-05.", "release-03.md"))
            row = db.execute("SELECT id, content FROM chunks").fetchone()
            vector = demo_vector(row["content"])
            db.execute("INSERT INTO embeddings VALUES (?,?,?,?)", (row["id"], EMBED_MODEL, len(vector), vector.tobytes()))
    monkeypatch.setenv("GIST_DB_PATH", str(path))
    return path


def test_ask_incomplete_vectors_is_still_403(v1_db: Path, api):
    _assert_structured(api.post("/api/ask", json={"question": "CRM sync failure", "mode": "openai"}, headers=ORIGIN),
                       403, "paid_api_disabled")


def test_ask_pre_spend_refusal_is_422(paid_ready_db: Path, api, monkeypatch):
    def refuse(_db, _question):
        raise PaidRequestRejected("Paid request exceeds the 12000-byte limit")

    monkeypatch.setattr(service, "embed_query_cached", refuse)
    error = _assert_structured(api.post("/api/ask", json={"question": "notification digest", "mode": "openai"},
                                        headers=ORIGIN), 422, "paid_request_rejected")
    assert error["message"] == "Paid request exceeds the 12000-byte limit"


def test_ask_malformed_embedding_response_is_502(paid_ready_db: Path, api, monkeypatch):
    monkeypatch.setattr(provider, "_guard", lambda _db: "offline-test")
    monkeypatch.setattr(provider, "_post", lambda *_args, **_kwargs: ({"data": [{"embedding": [1.0]}]}, {}))
    _assert_structured(api.post("/api/ask", json={"question": "notification digest", "mode": "openai"},
                                headers=ORIGIN), 502, "provider_error")


def test_post_size_limit_raises_paid_request_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(provider, "_guard", lambda _db: "offline-test")
    with connection(tmp_path / "limit.sqlite3") as db:
        with pytest.raises(PaidRequestRejected, match="byte limit"):
            provider._post(db, "responses", "m", {"input": "x" * 13_000, "max_output_tokens": 10}, 0.1, 0.5)
        with pytest.raises(PaidRequestRejected, match="1–16 texts"):
            provider.embed(db, [])


def test_malformed_provider_payloads_become_provider_errors(tmp_path: Path, monkeypatch):
    payloads = iter([({"data": [{"index": 0}]}, {}),  # embedding missing
                     ({"data": "not-a-list-of-objects"}, {}),
                     ({"output": ["not-an-object"]}, {"input_tokens": 1, "output_tokens": 1})])
    monkeypatch.setattr(provider, "_post", lambda *_args, **_kwargs: next(payloads))
    with connection(tmp_path / "malformed.sqlite3") as db:
        with pytest.raises(ProviderError, match="malformed embedding"):
            provider.embed(db, ["a"])
        with pytest.raises(ProviderError, match="malformed embedding"):
            provider.embed(db, ["a"])
        with pytest.raises(ProviderError, match="malformed answer"):
            provider.complete(db, "q", [("s", "t")])
