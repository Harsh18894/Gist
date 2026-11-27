"""Phase 2.2 answer lock and one-time v4 final exam: guards and outputs, with fakes only."""
import pytest

from app.schemas import AskResponse
from scripts import lock_benchmark4 as lock
from scripts import run_benchmark4_final as final
from helpers import require_private  # noqa: E402


@require_private()
def test_lock_create_verify_and_tamper(tmp_path, monkeypatch):
    path = tmp_path / "lock.json"
    record = lock.create(path)
    assert record["answer_config"]["context_sources"] == 8 and record["answer_config"]["max_output_tokens"] == 600
    assert lock.verify_lock(path)["lock_sha256"]
    with pytest.raises(FileExistsError):
        lock.create(path)
    original = lock._sha
    monkeypatch.setattr(lock, "_sha", lambda p: "changed" if p.name == "service.py" else original(p))
    with pytest.raises(ValueError, match="files_sha256"):
        lock.verify_lock(path)


@require_private()
def test_final_selection_is_the_frozen_heldout_set():
    manifest, questions = final.final_questions()
    assert [q["id"] for q in questions] == manifest["heldout_ids"] and len(questions) == 24


def _response(status, cited=(), retrieved=("a",)):
    hit = lambda sid: {"source_id": sid, "chunk_id": f"{sid}:000", "title": "", "kind": "feedback", "path": "",
                       "source_date": None, "segment": None, "product_area": None, "snippet": "", "score": 1.0,
                       "keyword_rank": 1, "semantic_rank": None}
    return AskResponse(answer="x", status=status, mode="openai", citations=[hit(s) for s in cited],
                       retrieved_sources=[hit(s) for s in retrieved], latency_ms=1, input_tokens=1, output_tokens=1,
                       estimated_cost_usd=0.0)


@require_private()
def test_run_guards_and_fake_full_run(tmp_path, monkeypatch):
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    monkeypatch.setattr(final, "verify_lock", lambda: (_ for _ in ()).throw(ValueError("lock changed")))
    with pytest.raises(ValueError, match="lock changed"):
        final.run()
    monkeypatch.setattr(final, "verify_lock", lambda: {"lock_sha256": "x", "answer_config": {"llm_model": "gpt-6-luna"}})
    done = tmp_path / "done.json"
    done.write_text("{}")
    monkeypatch.setattr(final, "RESULT", done)
    with pytest.raises(FileExistsError, match="already ran once"):
        final.run()
    monkeypatch.setattr(final, "RESULTS", tmp_path)
    monkeypatch.setattr(final, "RESULT", tmp_path / "final.json")
    monkeypatch.setattr(final, "REVIEW_CSV", tmp_path / "review.csv")
    monkeypatch.setattr(final, "embed_query_cached", lambda db, q: (None, {"cache_hit": True}))
    monkeypatch.setattr(final, "hybrid_search", lambda *a, **k: [])
    def fake_answer(db, request, audit_generated=None):
        audit_generated("Status: insufficient\nNo.")
        return _response("insufficient_evidence")
    monkeypatch.setattr(final, "answer", fake_answer)
    result = final.run()
    assert result["answers_summary"]["questions_answered"] == 24
    assert result["answers_summary"]["unanswerable_declined"] == "4/4"
    assert result["answers_summary"]["answerable_wrongly_refused"] == "20/20"
    assert (tmp_path / "review.csv").exists() and result["label_provenance"].startswith("AI-judge labels")
