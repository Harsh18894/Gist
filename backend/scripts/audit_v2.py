"""Offline quality audit for fictional Pulse v2; no retriever calls."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median

try:
    from .generate_v2 import MIN_LINE_DATE, ROOT, SCENARIOS
except ImportError:  # direct script invocation
    from generate_v2 import MIN_LINE_DATE, ROOT, SCENARIOS


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def audit(data: Path | None = None, evals: Path | None = None) -> dict:
    data = data or ROOT / "data/v2"
    evals = evals or ROOT / "evals/v2"
    feedback = _rows(data / "feedback.jsonl")
    tickets = _rows(data / "support-tickets.jsonl")
    annotations = _rows(evals / "source_annotations.jsonl")
    ann = {item["source_id"]: item for item in annotations}
    all_text = [item["feedback_text"] for item in feedback]
    canonical = [re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip() for text in all_text]
    duplicates = sum(count - 1 for count in Counter(canonical).values() if count > 1)
    near_pairs: list[tuple[str, str, float]] = []
    for left in range(len(feedback)):
        for right in range(left + 1, len(feedback)):
            if canonical[left] == canonical[right]:
                continue
            if abs(len(canonical[left]) - len(canonical[right])) > max(len(canonical[left]), len(canonical[right])) * .20:
                continue
            score = SequenceMatcher(None, canonical[left], canonical[right]).ratio()
            if score >= .88:
                near_pairs.append((feedback[left]["id"], feedback[right]["id"], round(score, 3)))
    words = [re.findall(r"[a-z0-9']+", value.lower()) for value in all_text]
    lengths = sorted(len(row) for row in words)
    tokens = [word for row in words for word in row]
    timeline_errors = []
    for row in feedback + tickets:
        day = row["timestamp"][:10]
        text = row.get("feedback_text", row.get("description", ""))
        for phrase, minimum in MIN_LINE_DATE.items():
            if phrase in text and day < minimum:
                timeline_errors.append(row["id"])
        for issue in ann[row["id"]]["issue_ids"]:
            model = SCENARIOS[issue]
            if day < model["onset"] or (model["end"] and day > model["end"] and row["id"].startswith("V2-FB")):
                timeline_errors.append(row["id"])
    for index, row in enumerate(tickets):
        parent_id = ann[row["id"]]["related_source_id"]
        parent = next(item for item in feedback if item["id"] == parent_id)
        if row["timestamp"] < parent["timestamp"]:
            timeline_errors.append(row["id"])
    issues = Counter(issue for item in annotations for issue in item["issue_ids"] if item["source_id"].startswith("V2-FB"))
    segments = Counter(row["customer_segment"] for row in feedback)
    months = Counter(row["timestamp"][:7] for row in feedback)
    return {
        "dataset_version": "v2", "feedback": len(feedback), "tickets": len(tickets),
        "prds": len(list((data / "prds").glob("*.md"))), "release_notes": len(list((data / "release-notes").glob("*.md"))),
        "exact_duplicate_records": duplicates, "near_duplicate_pairs": len(near_pairs), "near_duplicate_examples": near_pairs[:12],
        "text_length_words": {"min": lengths[0], "median": median(lengths), "p90": lengths[int(.9 * (len(lengths)-1))], "max": lengths[-1]},
        "vocabulary": {"unique_tokens": len(set(tokens)), "total_tokens": len(tokens), "type_token_ratio": round(len(set(tokens)) / len(tokens), 3)},
        "issue_distribution": dict(sorted(issues.items())), "segment_distribution": dict(sorted(segments.items())),
        "date_distribution_by_month": dict(sorted(months.items())),
        "multi_issue_feedback": sum(ann[row["id"]]["multi_issue"] for row in feedback),
        "ambiguous_feedback": sum(ann[row["id"]]["ambiguous"] for row in feedback),
        "limited_context_feedback": sum(ann[row["id"]]["context_limited"] for row in feedback),
        "timeline_errors": timeline_errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, help="Optional audit result file")
    args = parser.parse_args()
    result = audit()
    output = json.dumps(result, indent=2)
    if args.json:
        args.json.write_text(output + "\n")
    print(output)
