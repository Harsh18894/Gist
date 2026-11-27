"""Claim-support judge: parsing, agreement arithmetic, request size, run guards. No network."""
import json
from pathlib import Path

import pytest

from app.rag import provider
from scripts import judge_answers as judge
from helpers import require_private  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "evals/phase21/results/benchmark3-answer-claim-review-completed.csv"


def test_parse_verdict_validates_labels():
    good = judge.parse_verdict('Here: {"claims_supported": "Some", "unsupported_claims": ["x"], '
                               '"correct_abstention": "yes", "overall": "poor", "reason": "r"}')
    assert good["claims_supported"] == "some" and good["overall"] == "poor"
    assert "parse_error" in judge.parse_verdict("no json")
    assert "parse_error" in judge.parse_verdict('{"claims_supported": "mostly", "correct_abstention": "yes", "overall": "good"}')


def test_sources_round_trip_from_review_sheet():
    text = "[a-1] First text.\n\n[V2-SUP-9] Customer: hi\n\nSupport: ok"
    assert judge._sources(text) == [{"source_id": "a-1", "text": "First text."},
                                    {"source_id": "V2-SUP-9", "text": "Customer: hi\n\nSupport: ok"}]
    assert judge._sources("") == []


def test_agreement_counts_and_excludes_trivial_abstentions():
    h = lambda c, a, o: {"claims_supported": c, "correct_abstention": a, "overall": o}
    pairs = [(h("all", "yes", "good"), h("all", "yes", "good")),
             (h("some", "yes", "poor"), h("all", "yes", "good")),
             (h("n_a", "yes", "good"), h("n_a", "yes", "good")),
             (h("all", "yes", "good"), {"parse_error": "x"})]
    result = judge.agreement(pairs)
    assert result["all_rows"]["overall"] == {"agree": 2, "of": 3, "rate": 0.6667}
    assert result["rows_with_claims"]["overall"]["of"] == 2
    assert result["poor_recall"] == "0/1" and result["judge_more_lenient"] == 1 and result["parse_errors"] == 1


NEW_SHEET = ROOT / "evals/phase21/results/benchmark3-answer-claim-review-phase22-dev-cap600.csv"


@require_private()
@pytest.mark.parametrize("prompt", sorted(judge.PROMPTS))
@pytest.mark.parametrize("sheet", [REVIEW, NEW_SHEET])
def test_every_review_row_fits_the_request_bound(prompt, sheet):
    for row in judge._rows(sheet):
        body = {"model": "m", "instructions": judge.PROMPTS[prompt],
                "input": json.dumps(judge.judge_input(row), ensure_ascii=True), "max_output_tokens": 600, "store": False}
        assert len(json.dumps(body, ensure_ascii=True).encode()) <= provider.GENERATION_BYTE_LIMIT, row["question_id"]


@require_private()
def test_calibration_run_with_fake_judge_is_immutable(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "RESULTS", tmp_path)
    reply = '{"claims_supported": "all", "unsupported_claims": [], "correct_abstention": "yes", "overall": "good", "reason": "r"}'
    monkeypatch.setattr(judge, "judge", lambda db, instructions, payload: (reply, {"model": "fake", "input_tokens": 1}))
    result = judge.run("calibrate", REVIEW, "fake")
    assert result["rows"] == 24 and result["agreement"]["all_rows"]["overall"]["of"] == 24
    with pytest.raises(FileExistsError):
        judge.run("calibrate", REVIEW, "fake")
    with pytest.raises(ValueError, match="completed human review"):
        judge.run("calibrate", ROOT / "evals/phase21/results/benchmark3-answer-claim-review.csv", "blank")


def test_judge_cap_is_separate_from_answer_cap(monkeypatch):
    sent = {}
    def fake_post(_db, endpoint, model, body, *_prices, output_cap=None, **_kw):
        sent.update(cap=output_cap, max=body["max_output_tokens"])
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]}, {}
    monkeypatch.setattr(provider, "_post", fake_post)
    provider.judge(None, "i", {"q": 1})
    assert sent == {"cap": 1500, "max": 1500} and provider.MAX_OUTPUT_TOKENS == 600


def test_answer_path_cannot_borrow_the_judge_cap(monkeypatch):
    for name, value in (("GIST_ENABLE_PAID_API", "true"), ("GIST_PAID_EVAL_APPROVED", "true"),
                        ("GIST_MAX_API_SPEND_USD", "0.5"), ("OPENAI_API_KEY", "test-not-a-key")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(provider.budget, "reserve", lambda *a, **k: pytest.fail("must reject before reserving"))
    with pytest.raises(provider.PaidRequestRejected, match="600"):
        provider._post(None, "responses", "m", {"input": "x", "max_output_tokens": 1500}, 0.1, 0.5)
    with pytest.raises(provider.PaidRequestRejected, match="Unsupported output cap"):
        provider._post(None, "responses", "m", {"input": "x", "max_output_tokens": 10}, 0.1, 0.5, output_cap=5000)


@require_private()
def test_v2_decision_label_maps_and_prompt_is_recorded(tmp_path, monkeypatch):
    verdict = judge.parse_verdict('{"claims_supported": "all", "decision_correct": "No", "overall": "poor"}')
    assert verdict["correct_abstention"] == "no"
    assert "decision_correct" in judge.PROMPTS["v2"] and "WRONG" in judge.PROMPTS["v2"]
    monkeypatch.setattr(judge, "RESULTS", tmp_path)
    reply = '{"claims_supported": "n_a", "decision_correct": "yes", "overall": "good"}'
    monkeypatch.setattr(judge, "judge", lambda db, instructions, payload: (reply, {"model": "fake"}))
    result = judge.run("calibrate", REVIEW, "v2-fake")
    assert result["judge_prompt"] == "v2" and len(result["judge_prompt_sha256"]) == 64
    with pytest.raises(ValueError, match="Unknown judge prompt"):
        judge.run("calibrate", REVIEW, "bad", prompt="v9")
