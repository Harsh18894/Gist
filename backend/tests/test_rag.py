import json
import sqlite3
from pathlib import Path

import numpy as np

from app.database import connection, database_path, initialize
from app.rag.ingest import Source, chunk_text, clean_text, import_file, upsert_source
from app.rag.provider import EMBED_MODEL, _post, usage_summary
from app.rag.retrieval import Filters, hybrid_search, semantic_search
from scripts.evaluate_retrieval import evaluate


def test_clean_chunk_and_import_formats(client, tmp_path: Path):
    assert clean_text("hello\x00  world\n  again") == "hello world again"
    parts = chunk_text(" ".join(str(i) for i in range(20)), max_words=8, overlap_words=2)
    assert len(parts) == 3
    assert parts[0].split()[-2:] == parts[1].split()[:2]
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("id,title,text,customer_segment,product_area,timestamp\n1,Connector note,The fictional CRM sync retries safely,Enterprise,Integrations,2025-07-09\n")
    txt_path = tmp_path / "sample.txt"
    txt_path.write_text("This fictional billing note explains annual seats.")
    md_path = tmp_path / "sample.md"
    md_path.write_text("# Fictional gallery note\nPublished: 2025-08-10\nProduct area: Collaboration\n\nShared templates now show in the gallery.")
    with connection() as db:
        with db:
            assert import_file(db, csv_path) == (1, 1)
            assert import_file(db, txt_path, segment="SMB", product_area="Billing", source_date="2025-07-01") == (1, 1)
            assert import_file(db, md_path) == (1, 1)
        before = db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        with db:
            import_file(db, csv_path)
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == before
        row = db.execute("SELECT * FROM sources WHERE title = 'Connector note'").fetchone()
        assert (row["segment"], row["product_area"], row["source_date"]) == ("Enterprise", "Integrations", "2025-07-09")
    hit = client.get("/api/search", params={"query": "fictional CRM sync retries", "segment": "Enterprise", "product_area": "Integrations"}).json()
    assert any(item["title"] == "Connector note" for item in hit)


def test_cosine_ranking_with_known_vectors(tmp_path: Path):
    with connection(tmp_path / "vectors.sqlite3") as db:
        initialize(db)
        with db:
            upsert_source(db, Source("a", "Alpha", "text", "alpha topic", "a.txt"))
            upsert_source(db, Source("b", "Beta", "text", "beta topic", "b.txt"))
            db.executemany("INSERT INTO embeddings VALUES (?,?,?,?)", [
                ("a:000", "test-vector", 2, np.array([1, 0], dtype=np.float32).tobytes()),
                ("b:000", "test-vector", 2, np.array([0, 1], dtype=np.float32).tobytes()),
            ])
        ranked = semantic_search(db, np.array([0.9, 0.1], dtype=np.float32), "test-vector", Filters())
        assert [item[0] for item in ranked] == ["a:000", "b:000"]


def test_guarded_embedding_batch_persists_vectors_without_network(tmp_path: Path, monkeypatch):
    from app.rag import provider

    with connection(tmp_path / "embed.sqlite3") as db:
        initialize(db)
        with db:
            upsert_source(db, Source("first", "First", "text", "Fictional alpha", "first.txt"))
            upsert_source(db, Source("second", "Second", "text", "Fictional beta", "second.txt"))
        monkeypatch.setattr(provider, "embed", lambda _db, texts, **_kwargs:
                            ([np.array([float(index + 1), 0], dtype=np.float32) for index in range(len(texts))], {}))
        assert provider.index_missing_embeddings(db) == 2
        assert provider.index_missing_embeddings(db) == 0
        rows = db.execute("SELECT model, dimensions, length(vector) FROM embeddings WHERE model = ?", (EMBED_MODEL,)).fetchall()
        assert len(rows) == 2 and all(tuple(row) == (EMBED_MODEL, 2, 8) for row in rows)


def test_embedding_response_reorders_vectors_by_input_index(monkeypatch, tmp_path: Path):
    from app.rag import provider

    monkeypatch.setattr(provider, "_post", lambda *_args, **_kwargs:
                        ({"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}, {}))
    with connection(tmp_path / "response.sqlite3") as db:
        vectors, _usage = provider.embed(db, ["alpha", "beta"])
    assert vectors[0].tolist() == [1.0, 0.0]
    assert vectors[1].tolist() == [0.0, 1.0]


def test_responses_answer_parsing_and_source_prompt_without_network(monkeypatch, tmp_path: Path):
    from app.rag import provider

    captured: dict = {}
    def fake_post(_db, endpoint, model, body, _input_price, _output_price):
        captured.update({"endpoint": endpoint, "model": model, "body": body})
        return ({"output": [{"type": "message", "content": [{"type": "output_text", "text": "The digest changed [release-03]."}]}]},
                {"input_tokens": 10, "output_tokens": 6, "estimated_cost_usd": 0.000004})

    monkeypatch.setattr(provider, "_post", fake_post)
    with connection(tmp_path / "answer.sqlite3") as db:
        text, usage = provider.complete(db, "What changed?", [("release-03", "Synthetic digest update")])
    assert text == "The digest changed [release-03]."
    assert usage["input_tokens"] == 10
    assert captured["endpoint"] == "responses" and captured["body"]["store"] is False
    assert json.loads(captured["body"]["input"])["sources"] == [
        {"source_id": "release-03", "content": "Synthetic digest update"}]


def test_ask_citations_filters_insufficient_and_guards(client):
    answer = client.post("/api/ask", json={"question": "What did Pulse release on 2025-04-05?"}).json()
    assert answer["status"] == "sources_only" and answer["mode"] == "demo"
    assert "No answer was generated" in answer["answer"]
    assert not answer["citations"]
    assert answer["retrieved_sources"][0]["source_id"] == "release-03"
    source = client.get("/api/sources/release-03").json()
    assert "Notification digest update" in source["content"]
    assert answer["input_tokens"] == answer["output_tokens"] == 0
    assert client.post("/api/ask", json={"question": "What is Pulse revenue?"}).json()["status"] == "insufficient_evidence"
    assert client.post("/api/ask", json={"question": "How many customers churned in 2026?"}).json()["status"] == "insufficient_evidence"
    filtered = client.post("/api/ask", json={"question": "CRM sync failure", "segment": "Enterprise", "product_area": "Integrations", "from_date": "2025-06-05"}).json()
    assert filtered["retrieved_sources"]
    assert all(item["segment"] == "Enterprise" and item["product_area"] == "Integrations" and item["source_date"] >= "2025-06-05" for item in filtered["retrieved_sources"])
    assert client.post("/api/ask", json={"question": "What did Pulse release?", "mode": "openai"}).status_code == 403
    assert client.get("/api/usage").json()["calls"] == 0


def test_search_strategies_and_validation(client):
    for strategy in ("keyword", "semantic", "hybrid"):
        response = client.get("/api/search", params={"query": "CRM sync", "strategy": strategy, "limit": 3})
        assert response.status_code == 200
        assert 0 < len(response.json()) <= 3
    for params in ({"query": "x"}, {"query": "CRM", "segment": "Invalid"},
                   {"query": "CRM", "from_date": "2025-08-01", "to_date": "2025-01-01"}):
        response = client.get("/api/search", params=params)
        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request"
    bad = client.post("/api/ask", json={"question": "CRM sync", "from_date": "2025-10-01", "to_date": "2025-01-01"})
    assert bad.status_code == 422


def test_retrieval_benchmark(client):
    # The fixture has seeded the same deterministic corpus used by the CLI.
    questions = json.loads((Path(__file__).resolve().parents[2] / "evals/questions.json").read_text())["questions"]
    with connection() as db:
        found = sum(any(hit.source_id in question["source_ids"] for hit in hybrid_search(db, question["question"], Filters(), limit=5))
                    for question in questions)
    assert found == 20


def test_usage_ledger_records_reported_tokens_without_network(client, monkeypatch, tmp_path):
    from app.rag import provider

    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"usage": {"input_tokens": 100, "output_tokens": 20}}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setenv("GIST_ENABLE_PAID_API", "true")
    monkeypatch.setenv("GIST_PAID_EVAL_APPROVED", "true")
    monkeypatch.setenv("GIST_MAX_API_SPEND_USD", "0.50")
    monkeypatch.setenv("GIST_SPEND_DB_PATH", str(tmp_path / "spend.sqlite3"))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(provider.httpx, "Client", FakeClient)
    with connection() as db:
        _payload, measured = _post(db, "responses", "test-model", {"input": "synthetic", "max_output_tokens": 350}, 0.10, 0.50)
        assert measured["input_tokens"] == 100 and measured["output_tokens"] == 20
        assert measured["estimated_cost_usd"] == 0.00002
        assert usage_summary(db)["calls"] == 1


def test_generated_answer_rejects_unknown_source_ids(tmp_path, monkeypatch):
    from app.rag import service
    from app.rag.ingest import demo_vector
    from app.schemas import AskRequest

    with connection(tmp_path / "answer.sqlite3") as db:
        initialize(db)
        with db:
            upsert_source(db, Source("release-03", "Notification digest update", "release_note",
                                     "The notification digest changed on 2025-04-05.", "release-03.md"))
        row = db.execute("SELECT id, content FROM chunks WHERE source_id = 'release-03'").fetchone()
        vector = demo_vector(row["content"])
        with db:
            db.execute("INSERT INTO embeddings VALUES (?,?,?,?)",
                       (row["id"], EMBED_MODEL, len(vector), vector.tobytes()))
        monkeypatch.setattr(service, "embed_query_cached", lambda _db, _text: (demo_vector("2025-04-05 notification digest"),
                             {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0, "latency_ms": 7}))
        monkeypatch.setattr(service, "complete", lambda _db, _question, _evidence:
                            ("A made-up claim [invented-source].", {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0, "latency_ms": 9}))
        result = service.answer(db, AskRequest(question="What changed in the 2025-04-05 notification release?", mode="openai"))
        assert result.status == "insufficient_evidence" and result.citations == []


def test_generated_answer_accepts_provider_latency_without_duplicate_field(tmp_path, monkeypatch):
    from app.rag import service
    from app.rag.ingest import demo_vector
    from app.schemas import AskRequest

    with connection(tmp_path / "answer-success.sqlite3") as db:
        initialize(db)
        with db:
            upsert_source(db, Source("release-03", "Notification digest update", "release_note",
                                     "The notification digest changed on 2025-04-05.", "release-03.md"))
            row = db.execute("SELECT id,content FROM chunks WHERE source_id='release-03'").fetchone()
            vector = demo_vector(row["content"])
            db.execute("INSERT INTO embeddings VALUES (?,?,?,?)", (row["id"], EMBED_MODEL, len(vector), vector.tobytes()))
        monkeypatch.setattr(service, "embed_query_cached", lambda _db, _text: (demo_vector("notification digest"),
                             {"input_tokens": 3, "output_tokens": 0, "estimated_cost_usd": 0.000001, "latency_ms": 7}))
        monkeypatch.setattr(service, "complete", lambda _db, _question, _evidence:
                            ("The notification digest changed [release-03].",
                             {"input_tokens": 10, "output_tokens": 5, "estimated_cost_usd": 0.000003, "latency_ms": 9}))
        audit: list[str] = []
        result = service.answer(db, AskRequest(question="What changed in the notification digest?", mode="openai"),
                                audit_generated=audit.append)
        assert result.status == "answered"
        assert audit == ["The notification digest changed [release-03]."]
        assert result.input_tokens == 13 and result.output_tokens == 5
        assert result.estimated_cost_usd == 0.000004
        assert result.citations[0].source_id == "release-03"


def test_grouped_citation_ids_are_parsed_and_numeric_check_ignores_ids():
    from app.rag.service import cited_source_ids
    from app.rag.evidence import unsupported_numbers

    answer = "Experiences varied [V2-FB-0367, V2-FB-0198]."
    assert cited_source_ids(answer) == {"V2-FB-0367", "V2-FB-0198"}
    assert not unsupported_numbers(answer, ["Some liked it; others muted summaries."])
    # Semicolons separate IDs too (Phase 2.2); unknown IDs are rejected later against the sent sources.
    assert cited_source_ids("Claim [V2-FB-0367; fake-id].") == {"V2-FB-0367", "fake-id"}
    assert cited_source_ids("Claim [V2-FB-0367; not valid!].") is None
