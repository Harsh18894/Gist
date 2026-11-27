"""Bounded answer check: deterministic flags and run guards, with a fake answer path."""
import pytest

from app.schemas import AskResponse
from scripts import run_benchmark3_answers as runner
from helpers import require_private  # noqa: E402


def _response(status, cited=(), retrieved=("a", "x")):
    hit = lambda sid: {"source_id": sid, "chunk_id": f"{sid}:000", "title": "", "kind": "feedback", "path": "",
                       "source_date": None, "segment": None, "product_area": None, "snippet": "", "score": 1.0,
                       "keyword_rank": 1, "semantic_rank": None}
    return AskResponse(answer="x", status=status, mode="openai", citations=[hit(s) for s in cited],
                       retrieved_sources=[hit(s) for s in retrieved], latency_ms=1, input_tokens=10,
                       output_tokens=5, estimated_cost_usd=0.0001)


def test_checks_flag_hard_negatives_context_and_abstention():
    question = {"category": "semantic", "relevant_source_ids": ["a"], "hard_negative_source_ids": ["x"],
                "partial_source_ids": [], "evidence_groups": [["a"]]}
    row = runner.checks(question, _response("answered", ["a", "x"]).model_dump(), "Yes [a] and [x, zz].")
    assert row["cited_hard_negatives"] == ["x"] and not row["cited_ids_all_retrieved"]
    assert row["evidence_groups_cited"] == "1/1" and row["abstention_correct"]
    unanswerable = {**question, "category": "unanswerable", "relevant_source_ids": [], "evidence_groups": []}
    assert runner.checks(unanswerable, _response("insufficient_evidence").model_dump(), None)["abstention_correct"]
    assert not runner.checks(unanswerable, _response("answered", ["a"]).model_dump(), "It was [a].")["abstention_correct"]


@require_private()
def test_run_refuses_rerun_and_keeps_answers_on_provider_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    done = tmp_path / "done.json"
    done.write_text("{}")
    monkeypatch.setattr(runner, "RESULT", done)
    with pytest.raises(FileExistsError):
        runner.run()
    monkeypatch.setattr(runner, "RESULT", tmp_path / "answers.json")
    monkeypatch.setattr(runner, "REVIEW_CSV", tmp_path / "review.csv")
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    calls = []
    def fake(db, request, audit_generated=None):
        calls.append(request.question)
        if len(calls) == 3:
            raise runner.ProviderError("timeout")
        audit_generated("Insufficient evidence.")
        return _response("insufficient_evidence")
    monkeypatch.setattr(runner, "answer", fake)
    result = runner.run()
    assert len(result["answers"]) == 2 and result["summary"]["stopped_early"]
    assert result["errors"][0]["error"] == "ProviderError" and (tmp_path / "review.csv").exists()


@require_private()
def test_labelled_rerun_is_development_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    with pytest.raises(ValueError, match="development-only"):
        runner.run(label="x")
    asked = []
    def fake(db, request, audit_generated=None):
        asked.append(request.question)
        audit_generated("Status: partial\nPart [a].\nLimitation: more needed.")
        return _response("partial", ["a"])
    monkeypatch.setattr(runner, "answer", fake)
    result = runner.run(development_only=True, label="dev-check")
    assert len(result["answers"]) == 18 and {r["split"] for r in result["answers"]} == {"development"}
    assert result["summary"]["answerable_partial_by_gist"] == "15/15"
    assert not any(r["abstained"] for r in result["answers"])
    assert (tmp_path / "benchmark3-answers-dev-check.json").exists()
    with pytest.raises(FileExistsError):
        runner.run(development_only=True, label="dev-check")
