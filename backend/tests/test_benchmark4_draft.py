"""Benchmark v4 draft: held-out only, balanced, phrase-backed labels, and freezable by the importer."""
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from scripts import import_phase21_review as importer

ROOT = Path(__file__).resolve().parents[2]
DRAFT_PATH, _OUT, VERSION = importer.TARGETS["v4"]
DRAFT = json.loads(DRAFT_PATH.read_text())
QCSV = ROOT / "evals/phase22/Gist_Benchmark4_Questions_for_Human_Review.csv"
SCSV = ROOT / "evals/phase22/Gist_Benchmark4_Sources_for_Human_Review.csv"


def test_draft_is_heldout_only_balanced_and_hashed():
    questions = DRAFT["questions"]
    assert len(questions) == 24 and {q["split"] for q in questions} == {"heldout"}
    for category in ("direct", "semantic", "multi_source", "temporal", "contradictory", "unanswerable"):
        assert sum(q["category"] == category for q in questions) == 4
    raw = json.dumps(questions, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    assert hashlib.sha256(raw).hexdigest() == DRAFT["questions_sha256"] == DRAFT["heldout_sha256"]
    assert DRAFT["human_review_status"].startswith("pending")
    assert DRAFT["max_similarity_to_earlier_questions"]["ratio"] < 0.72
    assert all(bool(q["evidence_groups"]) == (q["category"] != "unanswerable") for q in questions)


def test_labels_reference_real_sources_and_negatives_are_disjoint():
    with sqlite3.connect(f"file:{ROOT / 'backend/gist-v2.sqlite3'}?mode=ro", uri=True) as db:
        ids = {row[0] for row in db.execute("SELECT id FROM sources")}
    for q in DRAFT["questions"]:
        members = {sid for group in q["evidence_groups"] for sid in group}
        assert members <= ids and set(q["hard_negative_source_ids"]) <= ids
        assert not members & set(q["hard_negative_source_ids"]) and len(q["hard_negative_source_ids"]) <= 3


def test_full_owner_approval_freezes_v4(tmp_path):
    def fill(path, updates):
        with path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        for row in rows:
            updates(row)
        target = tmp_path / path.name
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return target
    def question(row):
        row.update({"question_reviewer_decision (approve/revise/unclear)": "approve", "judgments_are (exhaustive/reviewed_subset)": "reviewed_subset",
                    "reviewer_name": "Fixture", "review_date": "2026-11-25", "human_sign_off (yes/no)": "yes",
                    "all_evidence_groups_covered (yes/no/unclear)": "" if row["category"] == "unanswerable" else "yes"})
    def source(row):
        row["your_source_verdict (supports/partial/unsupported/unclear/hard_negative)"] = (
            "hard_negative" if row["was_ai_reviewed_hard_negative"] == "yes" else "supports")
    questions, sources = fill(QCSV, question), fill(SCSV, source)
    review, _ = importer.load(questions, sources, draft_path=DRAFT_PATH)
    assert review.blockers == []
    manifest = importer.freeze(questions, sources, out=tmp_path / "frozen", draft_path=DRAFT_PATH, version=VERSION)
    assert manifest["benchmark_version"] == VERSION and len(manifest["heldout_ids"]) == 24
    assert manifest["development_ids"] == [] and importer.verify(tmp_path / "frozen")
