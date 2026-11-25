"""Benchmark 3 development evaluator: split safety and metric arithmetic, no network."""
import json
from pathlib import Path

from scripts import evaluate_benchmark3_dev as evaluator

ROOT = Path(__file__).resolve().parents[2]


def test_only_frozen_development_questions_are_selected():
    manifest, questions = evaluator.development_questions()
    assert len(questions) == 18 and all(q["split"] == "development" for q in questions)
    assert not {q["id"] for q in questions} & set(manifest["heldout_ids"])


def test_score_uses_groups_hard_negatives_and_no_full_recall():
    question = {"relevant_source_ids": ["a", "b", "c"], "hard_negative_source_ids": ["x"],
                "partial_source_ids": ["p"], "evidence_groups": [["a"], ["b", "c"]]}
    kinds = {"a": "prd", "b": "feedback", "c": "feedback", "x": "feedback", "p": "feedback"}
    row = evaluator.score(question, ["x", "p", "b", "z", "z2"], kinds)
    assert row["hit_at_5"] == 1 and row["mrr_at_5"] == round(1 / 3, 4)
    assert row["evidence_group_coverage_at_20"] == 0.5 and row["missed_evidence_groups"] == [1]
    assert row["hard_negatives_above_first_relevant"] == ["x"] and row["partial_sources_in_top5"] == ["p"]
    assert row["documents_relevant"] == ["a"] and row["documents_relevant_retrieved_at_20"] == []
    assert "recall" not in json.dumps(row).lower()
    unanswerable = evaluator.score({**question, "relevant_source_ids": [], "evidence_groups": []}, ["x"], kinds)
    assert unanswerable["answerable"] is False and "hit_at_5" not in unanswerable
