"""Phase 2.3 development answer runner: selection, summaries and immutability, with a fake answer path."""
import pytest

from app.schemas import AskResponse
from scripts import run_dev_answers as dev


def _response(status, cited=(), retrieved=("a",)):
    hit = lambda sid: {"source_id": sid, "chunk_id": f"{sid}:000", "title": "", "kind": "feedback", "path": "",
                       "source_date": None, "segment": None, "product_area": None, "snippet": "", "score": 1.0,
                       "keyword_rank": 1, "semantic_rank": None}
    return AskResponse(answer="x", status=status, mode="openai", citations=[hit(s) for s in cited],
                       retrieved_sources=[hit(s) for s in retrieved], latency_ms=1, input_tokens=1, output_tokens=1,
                       estimated_cost_usd=0.0)


def test_selection_is_benchmark3_development_plus_consumed_v4():
    selected = dev.questions()
    assert sum(q["set"] == "benchmark3-dev" for q in selected) == 18
    assert sum(q["set"] == "benchmark4-consumed" for q in selected) == 24
    assert not any(q["set"] == "benchmark3-dev" and q["split"] != "development" for q in selected)


def test_fake_run_summarizes_and_is_immutable(tmp_path, monkeypatch):
    monkeypatch.setenv("GIST_DATASET_VERSION", "v2")
    monkeypatch.setattr(dev, "RESULTS", tmp_path)
    def fake(db, request, audit_generated=None):
        audit_generated("Status: partial\nPart [a].\nLimitation: more.")
        return _response("partial", ["a"])
    monkeypatch.setattr(dev, "answer", fake)
    result = dev.run("fake")
    assert result["retriever"] == "hybrid" and len(result["answers"]) == 42
    assert result["summary"]["all"]["partial"] == 35 and result["summary"]["all"]["wrong_refusals"] == 0
    assert result["summary"]["set:benchmark4-consumed"]["questions"] == 24
    with pytest.raises(FileExistsError):
        dev.run("fake")
