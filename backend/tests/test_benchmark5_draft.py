"""Benchmark v5 draft: held-out only, balanced, new questions, real labels, freezable by the importer."""
import csv
import hashlib
import json
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

from scripts import create_benchmark4 as base
from scripts import import_phase21_review as importer

ROOT = Path(__file__).resolve().parents[2]
DRAFT_PATH, _OUT, VERSION = importer.TARGETS["v5"]
DRAFT = json.loads(DRAFT_PATH.read_text())
QCSV = ROOT / "evals/phase23/Gist_Benchmark5_Questions_for_Human_Review.csv"
SCSV = ROOT / "evals/phase23/Gist_Benchmark5_Sources_for_Human_Review.csv"


def test_v5_is_heldout_balanced_hashed_and_new():
    questions = DRAFT["questions"]
    assert len(questions) == 24 and {q["split"] for q in questions} == {"heldout"}
    assert all(q["id"].startswith("B5-Q-") for q in questions)
    for category in ("direct", "semantic", "multi_source", "temporal", "contradictory", "unanswerable"):
        assert sum(q["category"] == category for q in questions) == 4
    raw = json.dumps(questions, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    assert hashlib.sha256(raw).hexdigest() == DRAFT["questions_sha256"]
    earlier = [x["question"] for x in json.loads((ROOT / "evals/v2/questions.json").read_text())["questions"]]
    for path in ("evals/phase21/reviewed-v3/benchmark.json", "evals/phase22/reviewed-v4/benchmark.json"):
        earlier += [x["question"] for x in json.loads((ROOT / path).read_text())["questions"]]
    assert max(SequenceMatcher(None, base._norm(a["question"]), base._norm(b)).ratio()
               for a in questions for b in earlier) < 0.72


def test_v5_labels_reference_real_sources():
    with sqlite3.connect(f"file:{ROOT / 'backend/gist-v2.sqlite3'}?mode=ro", uri=True) as db:
        ids = {row[0] for row in db.execute("SELECT id FROM sources")}
    for q in DRAFT["questions"]:
        members = {sid for group in q["evidence_groups"] for sid in group}
        assert members <= ids and not members & set(q["hard_negative_source_ids"])
        assert bool(q["evidence_groups"]) == (q["category"] != "unanswerable")


def test_full_owner_approval_freezes_v5(tmp_path):
    def fill(path, update):
        with path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        for row in rows:
            update(row)
        target = tmp_path / path.name
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return target
    questions = fill(QCSV, lambda r: r.update({
        "question_reviewer_decision (approve/revise/unclear)": "approve", "judgments_are (exhaustive/reviewed_subset)": "reviewed_subset",
        "reviewer_name": "Fixture", "review_date": "2026-11-26", "human_sign_off (yes/no)": "yes",
        "all_evidence_groups_covered (yes/no/unclear)": "" if r["category"] == "unanswerable" else "yes"}))
    sources = fill(SCSV, lambda r: r.update({"your_source_verdict (supports/partial/unsupported/unclear/hard_negative)":
                                             "hard_negative" if r["was_ai_reviewed_hard_negative"] == "yes" else "supports"}))
    manifest = importer.freeze(questions, sources, out=tmp_path / "frozen", draft_path=DRAFT_PATH, version=VERSION)
    assert manifest["benchmark_version"] == VERSION and len(manifest["heldout_ids"]) == 24
