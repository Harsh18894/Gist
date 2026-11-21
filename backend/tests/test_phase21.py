"""Offline checks for bounded investigations and paid-query cache behavior."""
import sqlite3
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pytest

from app.database import initialize
from app.rag.ingest import Source, upsert_source
from app.rag.phase21 import InvestigationConfig, classify_question, investigate, subqueries
from app.rag.retrieval import Filters

ROOT = Path(__file__).resolve().parents[2]


def test_bounded_decomposition_and_question_types():
    assert classify_question("How should we distinguish three reasons someone cannot sign in?") == "multi_source"
    assert classify_question("How much revenue did this produce?") == "insufficient_context"
    assert classify_question("What changed after the release?") == "temporal"
    assert len(subqueries("How should we distinguish reasons someone cannot sign in?", max_subqueries=2)) == 2
    with pytest.raises(ValueError):
        InvestigationConfig(max_subqueries=5)
    with pytest.raises(ValueError):
        InvestigationConfig(retrieval_depth=101)


def test_focused_investigation_preserves_filters_and_source_ids():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    initialize(db)
    with db:
        upsert_source(db, Source("invite", "Invite", "feedback", "Owner verification blocked invitations.",
                                 "data/v2/invite", "2025-05-01", "Enterprise", "Onboarding"))
        upsert_source(db, Source("reset", "Reset", "feedback", "Password reset link expired.",
                                 "data/v2/reset", "2025-05-02", "SMB", "Onboarding"))
        upsert_source(db, Source("sso", "SSO", "feedback", "SAML identity provider configuration blocked sign in.",
                                 "data/v2/sso", "2025-05-03", "Enterprise", "Onboarding"))
    config = InvestigationConfig(vector_weight=0, focused_subqueries=True, evidence_quota=True)
    hits, trace = investigate(db, "Distinguish three reasons someone cannot sign in", Filters(), config)
    assert len(trace["subqueries"]) == 3
    assert {hit.source_id for hit in hits} == {"invite", "reset", "sso"}
    assert any(hit.evidence_needs for hit in hits)
    enterprise, _ = investigate(db, "Distinguish three reasons someone cannot sign in",
                                Filters(segment="Enterprise"), config)
    assert {hit.source_id for hit in enterprise} == {"invite", "sso"}
    replay, _ = investigate(db, "Distinguish three reasons someone cannot sign in",
                            Filters(segment="Enterprise"), config,
                            keyword_candidates=["reset", "invite"], vector_candidates=["sso"])
    assert "reset" not in {hit.source_id for hit in replay}
    dated, _ = investigate(db, "Distinguish three reasons someone cannot sign in",
                           Filters(product_area="Onboarding", from_date="2025-05-03"), config)
    assert {hit.source_id for hit in dated} == {"sso"}
    db.close()


def test_query_embedding_cache_uses_dataset_fingerprint_and_avoids_second_call(monkeypatch):
    from app.rag import provider

    db = sqlite3.connect(":memory:")
    initialize(db)
    db.executemany("INSERT INTO dataset_meta VALUES (?,?)", [("version", "v2"), ("source_sha256", "corpus-a")])
    calls = []
    monkeypatch.setattr(provider, "_guard", lambda _db: "offline-test")

    def fake_embed(_db, texts, *, request_key=None):
        calls.append((texts, request_key))
        return [np.array([1, 2, 3], dtype=np.float32)], {"input_tokens": 4, "output_tokens": 0,
                                                          "estimated_cost_usd": 0.00000008, "latency_ms": 2}

    monkeypatch.setattr(provider, "embed", fake_embed)
    first, first_usage = provider.embed_query_cached(db, "Why is the board slow?")
    second, second_usage = provider.embed_query_cached(db, "Why is the board slow?")
    assert len(calls) == 1 and calls[0][1].startswith("query:")
    assert np.array_equal(first, second) and not first_usage["cache_hit"] and second_usage["cache_hit"]
    assert second_usage["estimated_cost_usd"] == 0
    db.execute("UPDATE dataset_meta SET value='corpus-b' WHERE key='source_sha256'")
    provider.embed_query_cached(db, "Why is the board slow?")
    assert len(calls) == 2
    db.close()


def test_query_cache_keeps_legacy_unversioned_paid_mode_usable(monkeypatch):
    from app.rag import provider

    db = sqlite3.connect(":memory:")
    initialize(db)
    monkeypatch.setattr(provider, "_guard", lambda _db: "offline-test")
    monkeypatch.setattr(provider, "embed", lambda _db, _texts: (
        [np.array([1, 0], dtype=np.float32)], {"input_tokens": 2, "output_tokens": 0,
                                               "estimated_cost_usd": 0.0, "latency_ms": 1}))
    vector, usage = provider.embed_query_cached(db, "legacy")
    assert vector.tolist() == [1, 0] and not usage["cache_hit"]
    assert db.execute("SELECT COUNT(*) FROM query_embedding_cache").fetchone()[0] == 0
    db.close()


def test_phase21_draft_benchmark_is_separate_and_not_human_approved():
    draft = json.loads((ROOT / "evals/phase21/benchmark-v2-draft.json").read_text())
    assert draft["benchmark_version"] == "gist-phase2.1-benchmark-2-draft"
    assert draft["human_review_status"].startswith("pending")
    questions = draft["questions"]
    raw = json.dumps(questions, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    assert hashlib.sha256(raw).hexdigest() == draft["questions_sha256"]
    assert len(questions) == 24 and len({q["id"] for q in questions}) == 24
    development = [q for q in questions if q["split"] == "development"]
    heldout = [q for q in questions if q["split"] == "heldout"]
    assert len(development) == 18 and len(heldout) == 6
    heldout_raw = json.dumps(heldout, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    assert hashlib.sha256(heldout_raw).hexdigest() == draft["heldout_sha256"]
    assert all(q["review_status"] == "independent_human_review_required" for q in questions)
    assert all(q["evidence_groups"] or q["category"] == "unanswerable" for q in questions)
    assert all(q["category"] != "unanswerable" or not q["evidence_groups"] for q in questions)
    normalize = lambda text: re.sub(r"[^a-z0-9 ]", "", text.lower())
    assert max(SequenceMatcher(None, normalize(a["question"]), normalize(b["question"])).ratio()
               for a in development for b in heldout) < .72
    with sqlite3.connect(f"file:{ROOT / 'backend/gist-v2.sqlite3'}?mode=ro", uri=True) as db:
        ids = {row[0] for row in db.execute("SELECT id FROM sources")}
        assert all({sid for group in q["evidence_groups"] for sid in group} <= ids for q in questions)
        assert all(set(q["hard_negative_source_ids"]) <= ids for q in questions)
