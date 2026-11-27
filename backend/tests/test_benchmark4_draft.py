"""Benchmark v4 draft: held-out only, balanced, phrase-backed labels, and freezable by the importer."""
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from scripts import import_phase21_review as importer
from helpers import V2_DB, require_private  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DRAFT_PATH, _OUT, VERSION = importer.TARGETS["v4"]
DRAFT = json.loads(DRAFT_PATH.read_text())
QCSV = ROOT / "evals/phase22/Gist_Benchmark4_Draft2_Questions_for_Human_Review.csv"
SCSV = ROOT / "evals/phase22/Gist_Benchmark4_Draft2_Sources_for_Human_Review.csv"
DRAFT1 = ROOT / "evals/phase22/benchmark-v4-draft.json"


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
    with sqlite3.connect(f"file:{V2_DB}?mode=ro", uri=True) as db:
        ids = {row[0] for row in db.execute("SELECT id FROM sources")}
    for q in DRAFT["questions"]:
        members = {sid for group in q["evidence_groups"] for sid in group}
        assert members <= ids and set(q["hard_negative_source_ids"]) <= ids
        assert not members & set(q["hard_negative_source_ids"]) and len(q["hard_negative_source_ids"]) <= 3


@require_private()
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
    frozen = json.loads((tmp_path / "frozen/benchmark.json").read_text())
    assert frozen["human_review"]["assisted_by_ai_prereview"].startswith("Owner review with an AI pre-review")


@require_private()
def test_draft2_keeps_ids_draft1_and_shows_ai_prereview_read_only():
    draft1 = json.loads(DRAFT1.read_text())
    raw = json.dumps(draft1["questions"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    assert hashlib.sha256(raw).hexdigest() == draft1["questions_sha256"]
    assert DRAFT["benchmark_version"].endswith("draft-2") and DRAFT["derived_from"]["benchmark_version"] == draft1["benchmark_version"]
    old = {q["id"]: q for q in draft1["questions"]}
    changed = [q["id"] for q in DRAFT["questions"] if q["question"] != old[q["id"]]["question"]]
    assert changed == ["B4-Q-010"] and all(q["category"] == old[q["id"]]["category"] for q in DRAFT["questions"])
    q13 = next(q for q in DRAFT["questions"] if q["id"] == "B4-Q-013")
    assert "V2-FB-0012" in q13["relevant_source_ids"] and "V2-FB-0012" not in q13["hard_negative_source_ids"]
    with SCSV.open(encoding="utf-8") as handle:
        headers = next(csv.reader(handle))
    assert any(h.startswith("ai_prereview_verdict (read-only)") for h in headers)
    assert "your_source_verdict (supports/partial/unsupported/unclear/hard_negative)" in headers
