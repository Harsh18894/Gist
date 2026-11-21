import hashlib
import json
import sqlite3
from pathlib import Path

from scripts.generate_data import generate

ROOT = Path(__file__).resolve().parents[2]


def test_reproducible_generated_data():
    path = ROOT / "data/feedback.jsonl"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    generate()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_generated_counts_and_required_fields():
    feedback = [json.loads(line) for line in (ROOT / "data/feedback.jsonl").read_text().splitlines()]
    tickets = (ROOT / "data/support-tickets.jsonl").read_text().splitlines()
    assert len(feedback) == 400
    assert len(tickets) == 120
    assert len(list((ROOT / "data/prds").glob("*.md"))) == 6
    assert len(list((ROOT / "data/release-notes").glob("*.md"))) == 8
    assert len({row["id"] for row in feedback}) == 400
    required = {"id", "timestamp", "customer_segment", "subscription_tier", "product_area", "feedback_channel", "feedback_text", "sentiment", "issue_category", "related_feature"}
    assert all(required <= row.keys() and all(row[key] for key in required) for row in feedback)
    benchmark = json.loads((ROOT / "evals/questions.json").read_text())
    assert benchmark["synthetic"] is True
    assert len(benchmark["questions"]) >= 20


def test_release_timing_is_consistent():
    feedback = [json.loads(line) for line in (ROOT / "data/feedback.jsonl").read_text().splitlines()]
    assert all(row["timestamp"][:10] >= "2025-04-05" for row in feedback if "April digest change" in row["feedback_text"])
    assert all(row["timestamp"][:10] >= "2025-06-05" for row in feedback if "June connector update" in row["feedback_text"])
    release_mentions = {
        "new checklist": "2025-02-05", "new digest": "2025-04-05",
        "updated invoice breakdown": "2025-05-05", "template gallery": "2025-07-05",
    }
    assert all(row["timestamp"][:10] >= date for row in feedback for phrase, date in release_mentions.items() if phrase in row["feedback_text"])
