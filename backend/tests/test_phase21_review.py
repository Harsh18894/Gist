"""Phase 2.1 human-review importer: synthetic review fixtures only, no network."""
import csv
import json
from pathlib import Path

import pytest

from scripts import import_phase21_review as importer

ROOT = Path(__file__).resolve().parents[2]
DRAFT = json.loads((ROOT / "evals/phase21/benchmark-v2-draft.json").read_text())
Q_HEADERS = ["question_id", "split", "category", "question", "proposed_answer_ai_reviewed",
             "ai_reviewed_evidence_groups", "ai_reviewed_supporting_source_ids",
             "ai_reviewed_hard_negative_source_ids", "all_source_ids_in_source_review_csv", "ai_review_findings",
             "question_reviewer_decision (approve/revise/unclear)", "your_corrected_answer",
             "your_missing_source_ids", "your_question_comments", "all_evidence_groups_covered (yes/no/unclear)",
             "judgments_are (exhaustive/reviewed_subset)", "reviewer_name", "review_date",
             "second_reviewer_comments", "human_sign_off (yes/no)"]
S_HEADERS = ["question_id", "split", "category", "question", "source_id", "ai_source_classification",
             "ai_reviewed_evidence_group_numbers", "was_ai_reviewed_supporting_source",
             "was_ai_reviewed_hard_negative",
             "your_source_verdict (supports/partial/unsupported/unclear/hard_negative)", "your_source_comments",
             "your_corrected_evidence_group", "human_reviewer", "review_date", "second_reviewer_resolution"]


def _pack(approved: bool = True) -> tuple[list[dict], list[dict]]:
    """Recreate the review-pack shape from the draft, optionally with a full approval."""
    questions, sources = [], []
    for item in DRAFT["questions"]:
        rows = []
        for number, group in enumerate(item["evidence_groups"], 1):
            rows += [(sid, str(number), "yes", "no") for sid in group]
        rows += [(sid, "", "no", "yes") for sid in item["hard_negative_source_ids"]]
        text = " | ".join(f"Group {n}: {', '.join(g)}" for n, g in enumerate(item["evidence_groups"], 1))
        questions.append({"question_id": item["id"], "split": item["split"], "category": item["category"],
                          "question": item["question"],
                          "proposed_answer_ai_reviewed": item["expected_answer_or_abstention"],
                          "ai_reviewed_evidence_groups": text,
                          "ai_reviewed_supporting_source_ids": "; ".join(item["relevant_source_ids"]),
                          "ai_reviewed_hard_negative_source_ids": "; ".join(item["hard_negative_source_ids"]),
                          "all_source_ids_in_source_review_csv": "; ".join(row[0] for row in rows),
                          "ai_review_findings": "fixture",
                          **({"question_reviewer_decision (approve/revise/unclear)": "approve",
                              "all_evidence_groups_covered (yes/no/unclear)": "yes",
                              "judgments_are (exhaustive/reviewed_subset)": "reviewed_subset",
                              "reviewer_name": "Fixture Reviewer", "review_date": "2026-11-20",
                              "human_sign_off (yes/no)": "yes"} if approved else {})})
        for sid, number, support, negative in rows:
            verdict = "hard_negative" if negative == "yes" else "supports"
            sources.append({"question_id": item["id"], "split": item["split"], "category": item["category"],
                            "question": item["question"], "source_id": sid,
                            "ai_source_classification": "fixture", "ai_reviewed_evidence_group_numbers": number,
                            "was_ai_reviewed_supporting_source": support, "was_ai_reviewed_hard_negative": negative,
                            **({"your_source_verdict (supports/partial/unsupported/unclear/hard_negative)": verdict}
                               if approved else {})})
    return questions, sources


def _write(tmp_path: Path, questions: list[dict], sources: list[dict]) -> tuple[Path, Path]:
    paths = tmp_path / "questions.csv", tmp_path / "sources.csv"
    for path, headers, rows in ((paths[0], Q_HEADERS, questions), (paths[1], S_HEADERS, sources)):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    return paths


def _check(tmp_path: Path, questions: list[dict], sources: list[dict]) -> importer.Review:
    return importer.load(*_write(tmp_path, questions, sources))[0]


def _row(rows: list[dict], qid: str, sid: str | None = None) -> dict:
    return next(row for row in rows if row["question_id"] == qid and (sid is None or row["source_id"] == sid))


def _multi_source_dev() -> dict:
    return next(q for q in DRAFT["questions"] if q["split"] == "development" and len(q["evidence_groups"]) > 1
                and any(len(group) > 1 for group in q["evidence_groups"]))


def test_blank_review_is_blocked_and_cannot_freeze(tmp_path):
    questions, sources = _pack(approved=False)
    review = _check(tmp_path, questions, sources)
    assert review.report()["status"] == "BLOCKED"
    assert sum("source verdict is blank" in b for b in review.blockers) == len(sources)
    assert sum("human_sign_off" in b for b in review.blockers) == 24
    with pytest.raises(ValueError, match="blockers"):
        importer.freeze(*_write(tmp_path, questions, sources), out=tmp_path / "frozen")
    assert not (tmp_path / "frozen").exists()


def test_full_approval_freezes_immutable_versioned_benchmark(tmp_path):
    draft_bytes = (ROOT / "evals/phase21/benchmark-v2-draft.json").read_bytes()
    paths = _write(tmp_path, *_pack())
    assert importer.load(*paths)[0].blockers == []
    manifest = importer.freeze(*paths, out=tmp_path / "frozen")
    benchmark = json.loads((tmp_path / "frozen/benchmark.json").read_text())
    assert benchmark["benchmark_version"] == importer.BENCHMARK_VERSION
    assert benchmark["split_counts"] == {"development": 18, "heldout": 6}
    assert benchmark["source_sha256"] == DRAFT["source_sha256"]
    assert manifest["heldout_ids"] == sorted(q["id"] for q in DRAFT["questions"] if q["split"] == "heldout")
    by_id = {q["id"]: q for q in benchmark["questions"]}
    for item in DRAFT["questions"]:
        assert by_id[item["id"]]["evidence_groups"] == item["evidence_groups"]
        assert by_id[item["id"]]["review"]["reviewer"] == "Fixture Reviewer"
    assert (ROOT / "evals/phase21/benchmark-v2-draft.json").read_bytes() == draft_bytes
    assert importer.verify(tmp_path / "frozen")["questions_sha256"] == benchmark["questions_sha256"]
    with pytest.raises(FileExistsError):
        importer.freeze(*paths, out=tmp_path / "frozen")
    (tmp_path / "frozen/benchmark.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        importer.verify(tmp_path / "frozen")


def test_human_verdict_overrides_ai_and_both_are_preserved(tmp_path):
    questions, sources = _pack()
    target = _multi_source_dev()
    group = next(g for g in target["evidence_groups"] if len(g) > 1)
    _row(sources, target["id"], group[0])["your_source_verdict (supports/partial/unsupported/unclear/hard_negative)"] = "unsupported"
    paths = _write(tmp_path, questions, sources)
    review = importer.load(*paths)[0]
    assert review.blockers == []
    assert {"question_id": target["id"], "split": "development", "source_id": group[0],
            "ai_proposal": "supports", "human_final": "unsupported"} in review.disagreements
    importer.freeze(*paths, out=tmp_path / "frozen")
    frozen = next(q for q in json.loads((tmp_path / "frozen/benchmark.json").read_text())["questions"]
                  if q["id"] == target["id"])
    assert group[0] not in frozen["relevant_source_ids"] and group[0] in frozen["unsupported_source_ids"]
    assert group[0] in frozen["ai_proposal"]["supporting_source_ids"]


def test_unclear_needs_second_reviewer_resolution(tmp_path):
    questions, sources = _pack()
    target = _multi_source_dev()
    row = _row(sources, target["id"], target["evidence_groups"][0][0])
    row["your_source_verdict (supports/partial/unsupported/unclear/hard_negative)"] = "unclear"
    assert any("unclear and has no second-reviewer" in b for b in _check(tmp_path, questions, sources).blockers)
    row["second_reviewer_resolution"] = "maybe it supports"
    assert any("must start with a verdict" in b for b in _check(tmp_path, questions, sources).blockers)
    row["second_reviewer_resolution"] = "supports: names the exact control"
    review = _check(tmp_path, questions, sources)
    assert review.blockers == [] and any("second reviewer" in w for w in review.warnings)


def test_structural_problems_block(tmp_path):
    questions, sources = _pack()
    first = questions[0]["question_id"]
    _row(questions, first)["question"] += " (edited)"
    sources.append({**sources[0], "source_id": "V2-FB-9999"})
    sources.append(dict(sources[1]))
    removed = sources.pop(2)
    blockers = _check(tmp_path, questions, sources).blockers
    assert any(f"{first}: 'question' was edited" in b for b in blockers)
    assert any("V2-FB-9999: source ID does not exist" in b for b in blockers)
    assert any("duplicate source row" in b for b in blockers)
    assert any(f"{removed['question_id']}/{removed['source_id']}: an original review row was deleted" in b
               for b in blockers)


def test_unanswerable_with_support_and_lost_group_block(tmp_path):
    questions, sources = _pack()
    unanswerable = next(q for q in DRAFT["questions"] if q["category"] == "unanswerable" and q["hard_negative_source_ids"])
    _row(sources, unanswerable["id"], unanswerable["hard_negative_source_ids"][0])[
        "your_source_verdict (supports/partial/unsupported/unclear/hard_negative)"] = "supports"
    target = _multi_source_dev()
    for sid in target["evidence_groups"][-1]:
        _row(sources, target["id"], sid)["your_source_verdict (supports/partial/unsupported/unclear/hard_negative)"] = "partial"
    blockers = _check(tmp_path, questions, sources).blockers
    assert any(f"{unanswerable['id']}: unanswerable question has supporting sources" in b for b in blockers)
    assert any(f"{target['id']}: proposed evidence group {len(target['evidence_groups'])} has no human-supported" in b
               for b in blockers)
    _row(questions, target["id"])["question_reviewer_decision (approve/revise/unclear)"] = "revise"
    _row(questions, target["id"])["your_question_comments"] = "Group dropped: no source states it."
    blockers = _check(tmp_path, questions, sources).blockers
    assert not any(target["id"] in b for b in blockers)


def test_missing_sources_need_their_own_reviewed_row(tmp_path):
    questions, sources = _pack()
    target = _multi_source_dev()
    present = {row["source_id"] for row in sources if row["question_id"] == target["id"]}
    corpus_ids, _ = importer.corpus()
    extra = sorted(sid for sid in corpus_ids if sid.startswith("V2-FB-") and sid not in present)[0]
    _row(questions, target["id"])["your_missing_source_ids"] = extra
    assert any(f"{extra}: reported missing source needs its own row" in b
               for b in _check(tmp_path, questions, sources).blockers)
    sources.append({"question_id": target["id"], "source_id": extra,
                    "your_source_verdict (supports/partial/unsupported/unclear/hard_negative)": "supports",
                    "your_corrected_evidence_group": "1"})
    paths = _write(tmp_path, questions, sources)
    assert importer.load(*paths)[0].blockers == []
    importer.freeze(*paths, out=tmp_path / "frozen")
    frozen = next(q for q in json.loads((tmp_path / "frozen/benchmark.json").read_text())["questions"]
                  if q["id"] == target["id"])
    assert extra in frozen["evidence_groups"][0]
    assert next(j for j in frozen["source_judgments"] if j["source_id"] == extra)["ai_proposal"] is None


def test_invalid_enums_and_dates_block(tmp_path):
    questions, sources = _pack()
    _row(questions, questions[0]["question_id"])["review_date"] = "11/20/2026"
    _row(questions, questions[1]["question_id"])["judgments_are (exhaustive/reviewed_subset)"] = "complete"
    sources[0]["your_source_verdict (supports/partial/unsupported/unclear/hard_negative)"] = "relevant"
    blockers = _check(tmp_path, questions, sources).blockers
    assert any("must be YYYY-MM-DD" in b for b in blockers)
    assert any("judgments_are must be" in b for b in blockers)
    assert any("unknown verdict 'relevant'" in b for b in blockers)


def test_owner_corrections_apply_to_copies_and_are_hashed(tmp_path):
    questions, sources = _pack()
    target = questions[0]["question_id"]
    _row(questions, target)["review_date"] = "11/20/2026"
    paths = _write(tmp_path, questions, sources)
    original = paths[0].read_bytes()
    corrections = tmp_path / "corrections.json"
    change = {"file": "questions", "question_id": target, "field": "review_date",
              "old": "11/20/2026", "new": "2026-11-20", "reason": "ISO date"}
    corrections.write_text(json.dumps({"approved_by": "Owner", "approved_on": "2026-11-20", "changes": [change]}))
    manifest = importer.freeze(*paths, out=tmp_path / "frozen", corrections=corrections)
    assert paths[0].read_bytes() == original
    assert (tmp_path / "frozen/questions-review-original.csv").read_bytes() == original
    assert {"corrections.json", "questions-review-original.csv"} <= set(manifest["files_sha256"])
    benchmark = json.loads((tmp_path / "frozen/benchmark.json").read_text())
    assert benchmark["owner_approved_corrections"]["changed_cells"] == 1
    assert importer.verify(tmp_path / "frozen")
    assert not (tmp_path / "frozen.staging").exists()


def test_stale_correction_is_rejected_without_writing(tmp_path):
    paths = _write(tmp_path, *_pack())
    corrections = tmp_path / "corrections.json"
    qid = DRAFT["questions"][0]["id"]
    corrections.write_text(json.dumps({"approved_by": "Owner", "approved_on": "2026-11-20", "changes": [
        {"file": "questions", "question_id": qid, "field": "reviewer_name", "old": "Someone Else", "new": "X"}]}))
    with pytest.raises(ValueError, match="differs"):
        importer.freeze(*paths, out=tmp_path / "frozen", corrections=corrections)
    assert not (tmp_path / "frozen").exists() and not (tmp_path / "frozen.staging").exists()


def test_label_provenance_from_corrections_is_recorded(tmp_path):
    questions, sources = _pack()
    target = questions[0]["question_id"]
    _row(questions, target)["review_date"] = "11/20/2026"
    paths = _write(tmp_path, questions, sources)
    corrections = tmp_path / "corrections.json"
    corrections.write_text(json.dumps({"approved_by": "Owner", "approved_on": "2026-11-20",
                                       "label_provenance": "Labels produced by an AI judge and adopted by the owner.",
                                       "owner_statement": "Use these.",
                                       "changes": [{"file": "questions", "question_id": target, "field": "review_date",
                                                    "old": "11/20/2026", "new": "2026-11-20"}]}))
    importer.freeze(*paths, out=tmp_path / "frozen", corrections=corrections)
    frozen = json.loads((tmp_path / "frozen/benchmark.json").read_text())
    assert frozen["human_review"]["label_provenance"].startswith("Labels produced by an AI judge")
    assert frozen["human_review"]["independence"] == frozen["human_review"]["label_provenance"]
    assert frozen["label_policy"].startswith("Owner-adopted final verdicts")
