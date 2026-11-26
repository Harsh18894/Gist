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
        return text, {**FREE, "sent_source_ids": sent or [item[0] for item in evidence]}
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


def test_source_metadata_is_sent_to_the_model(monkeypatch):
    sent = {}
    def fake_post(_db, endpoint, model, body, *_prices, **_kw):
        sent["sources"] = json.loads(body["input"])["sources"]
        sent["instructions"] = body["instructions"]
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Status: answered\nok [a]"}]}]}, dict(FREE)
    monkeypatch.setattr(provider, "_post", fake_post)
    provider.complete(None, "When?", [("a", "text", {"kind": "feedback", "date": "2025-03-01", "segment": None}),
                                      ("b", "legacy two-item evidence")])
    assert sent["sources"][0] == {"source_id": "a", "kind": "feedback", "date": "2025-03-01", "content": "text"}
    assert sent["sources"][1] == {"source_id": "b", "content": "legacy two-item evidence"}
    assert "does not show when an issue began" in sent["instructions"] and "several unrelated issues" in sent["instructions"]


def test_answer_path_passes_hit_metadata(paid_db, monkeypatch):
    calls = _reply(monkeypatch, "Status: answered\nIt moved [rel-1].")
    _ask(paid_db)
    assert all(len(item) == 3 and "date" in item[2] and "kind" in item[2] for item in calls[0])


def test_numbers_followed_by_punctuation_are_matched_without_it():
    from app.rag.evidence import unsupported_numbers
    source = ["Published: 2025-05-05. Seats archived mid-cycle remain counted. I woke up to 38 project emails."]
    assert not unsupported_numbers("The breakdown was published May 5, 2025. [release-04]", source)
    assert not unsupported_numbers("One customer got 38 emails.", source)
    assert unsupported_numbers("One customer got 39 emails.", source)
    assert unsupported_numbers("Revenue rose 12%.", source)


def test_paid_cause_rule_blocks_only_explicit_cause_requests():
    policy = [Hit("p:000", "p", "", "release_note", "", None, None, None,
                  "Exports are counted per workspace until the month closes.", 1, 1, None)]
    why = "Why did the export count stay high after a workspace was removed?"
    assert assess(why, policy, fact_rules_only=True).sufficient
    assert assess(why, policy).rule == "cause"  # demo mode keeps the broad rule
    assert not assess("What caused the export failures?", policy, fact_rules_only=True).sufficient
    assert not assess("What is the root cause of the export failures?", policy, fact_rules_only=True).sufficient


def test_paid_retriever_setting(paid_db, monkeypatch):
    calls = _reply(monkeypatch, "Status: answered\nIt moved [rel-1].")
    monkeypatch.setenv("GIST_PAID_RETRIEVER", "mmr")
    result = _ask(paid_db)
    assert result.status == "answered" and calls and all(item[0] in {"rel-1", "fb-1"} for item in calls[0])
    monkeypatch.setenv("GIST_PAID_RETRIEVER", "other")
    with pytest.raises(ValueError, match="hybrid or mmr"):
        _ask(paid_db)
    monkeypatch.delenv("GIST_PAID_RETRIEVER")
    assert service.paid_retriever() == "hybrid"


def test_dates_from_source_metadata_count_as_number_evidence(tmp_path, monkeypatch):
    with connection(tmp_path / "dated.sqlite3") as db:
        initialize(db)
        with db:
            upsert_source(db, Source("fb-9", "fb-9", "feedback", "We archived two collaborators but the invoice still counts them.",
                                     "fb-9.md", "2025-01-29"))
        row = db.execute("SELECT id, content FROM chunks").fetchone()
        vector = demo_vector(row["content"])
        with db:
            db.execute("INSERT INTO embeddings VALUES (?,?,?,?)", (row["id"], EMBED_MODEL, len(vector), vector.tobytes()))
        monkeypatch.setattr(service, "embed_query_cached", lambda _db, text: (demo_vector(text), FREE))
        _reply(monkeypatch, "Status: answered\nA report on January 29 says archived collaborators still counted [fb-9].")
        assert _ask(db, "Were archived collaborators still counted on invoices?").status == "answered"
        _reply(monkeypatch, "Status: answered\nA report on January 30 says archived collaborators still counted [fb-9].")
        assert _ask(db, "Were archived collaborators still counted on invoices?").status == "insufficient_evidence"
