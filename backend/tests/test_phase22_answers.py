"""Phase 2.2 answer reliability: status line, partial answers, context bound, paid-mode gate. No network."""
import json

import pytest

from app.database import connection, initialize
from app.rag import provider, service
from app.rag.evidence import assess
from app.rag.ingest import Source, demo_vector, upsert_source
from app.rag.provider import EMBED_MODEL
from app.rag.retrieval import Hit
from app.schemas import AskRequest

FREE = {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0, "latency_ms": 1}


@pytest.fixture
def paid_db(tmp_path, monkeypatch):
    with connection(tmp_path / "answers.sqlite3") as db:
        initialize(db)
        with db:
            for sid, text in (("rel-1", "The export button moved to the toolbar in March."),
                              ("fb-1", "I could not find the export button after the toolbar change.")):
                upsert_source(db, Source(sid, sid, "feedback", text, f"{sid}.md"))
        for row in db.execute("SELECT id, content FROM chunks").fetchall():
            vector = demo_vector(row["content"])
            with db:
                db.execute("INSERT INTO embeddings VALUES (?,?,?,?)", (row["id"], EMBED_MODEL, len(vector), vector.tobytes()))
        monkeypatch.setattr(service, "embed_query_cached", lambda _db, text: (demo_vector(text), FREE))
        yield db


def _reply(monkeypatch, text, sent=None):
    calls = []
    def fake(_db, _question, evidence):
        calls.append(evidence)
        return text, {**FREE, "sent_source_ids": sent or [sid for sid, _ in evidence]}
    monkeypatch.setattr(service, "complete", fake)
    return calls


def _ask(db, question="Where did the export button move?"):
    return service.answer(db, AskRequest(question=question, mode="openai"))


def test_partial_status_keeps_cited_answer_and_strips_status_line(paid_db, monkeypatch):
    _reply(monkeypatch, "Status: partial\nIt moved to the toolbar [rel-1].\nLimitation: no source says why.")
    result = _ask(paid_db)
    assert result.status == "partial" and not result.answer.lower().startswith("status")
    assert [c.source_id for c in result.citations] == ["rel-1"] and "Limitation:" in result.answer


def test_declared_insufficient_abstains_even_with_citations(paid_db, monkeypatch):
    _reply(monkeypatch, "Status: insufficient\nNo source names an approver [rel-1].")
    assert _ask(paid_db).status == "insufficient_evidence"


def test_answered_with_stated_gap_is_downgraded_to_partial(paid_db, monkeypatch):
    _reply(monkeypatch, "Status: answered\nIt moved to the toolbar [rel-1]; there is insufficient evidence about timing.")
    assert _ask(paid_db).status == "partial"


def test_legacy_reply_without_status_line_keeps_old_rule(paid_db, monkeypatch):
    _reply(monkeypatch, "There is insufficient evidence, but see [rel-1].")
    assert _ask(paid_db).status == "insufficient_evidence"
    _reply(monkeypatch, "It moved to the toolbar [rel-1].")
    assert _ask(paid_db).status == "answered"


def test_semicolon_citations_and_unsent_sources(paid_db, monkeypatch):
    _reply(monkeypatch, "Status: answered\nIt moved and one customer could not find it [rel-1; fb-1].")
    assert {c.source_id for c in _ask(paid_db).citations} == {"rel-1", "fb-1"}
    _reply(monkeypatch, "Status: answered\nIt moved [rel-1; fb-1].", sent=["rel-1"])
    assert _ask(paid_db).status == "insufficient_evidence"


def test_paid_gate_keeps_fact_rules_but_skips_lexical_coverage(paid_db, monkeypatch):
    calls = _reply(monkeypatch, "Status: answered\nIt is on the toolbar [rel-1].")
    _ask(paid_db, "Where would someone locate the relocated toolbar control?")
    assert calls, "a paraphrased question should reach the model in paid mode"
    calls.clear()
    assert _ask(paid_db, "How much revenue did the export button move generate?").status == "insufficient_evidence"
    assert not calls, "a fact-type rule must still block before any paid generation"


def test_fact_rules_only_flag_on_assess():
    hits = [Hit("a:000", "a", "", "feedback", "", None, None, None, "Billing export broke.", 1, 1, None)]
    assert not assess("Where is the relocated download control?", hits).sufficient
    assert assess("Where is the relocated download control?", hits, fact_rules_only=True).sufficient
    assert not assess("Who approved the billing export change?", hits, fact_rules_only=True).sufficient


def test_complete_trims_context_to_byte_bound_and_reports_sent_ids(monkeypatch):
    sent = {}
    def fake_post(_db, endpoint, model, body, *_prices, **_kw):
        sent["size"] = len(json.dumps(body, ensure_ascii=True).encode())
        sent["ids"] = [s["source_id"] for s in json.loads(body["input"])["sources"]]
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Status: answered\nok [s0]"}]}]}, dict(FREE)
    monkeypatch.setattr(provider, "_post", fake_post)
    evidence = [(f"s{i}", "x" * 5000) for i in range(10)]
    _text, usage = provider.complete(None, "q?", evidence)
    assert sent["size"] <= provider.GENERATION_BYTE_LIMIT
    assert usage["sent_source_ids"] == sent["ids"] == [f"s{i}" for i in range(len(sent["ids"]))]
    assert 1 <= len(sent["ids"]) < 10


def test_output_cap_is_600_and_enforced_before_any_spend(monkeypatch):
    assert provider.MAX_OUTPUT_TOKENS == 600
    monkeypatch.setenv("GIST_ENABLE_PAID_API", "true")
    monkeypatch.setenv("GIST_PAID_EVAL_APPROVED", "true")
    monkeypatch.setenv("GIST_MAX_API_SPEND_USD", "0.5")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-key")
    monkeypatch.setattr(provider.budget, "reserve", lambda *a, **k: pytest.fail("must reject before reserving"))
    with pytest.raises(provider.PaidRequestRejected, match="600"):
        provider._post(None, "responses", "m", {"input": "x", "max_output_tokens": 601}, 0.1, 0.5)
