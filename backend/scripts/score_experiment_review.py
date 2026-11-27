"""Import and score the Phase 3.5 owner review of experiment suggestions. No API calls.

Checks that the completed sheet matches the generated sheet in every non-review column,
validates the labels, stores the owner copy once, and scores the targets fixed before the review.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "evals/phase35/review"
ORIGINAL = REVIEW / "experiment-review.csv"
OWNER = REVIEW / "experiment-review-owner.csv"
RESULT = ROOT / "evals/phase35/results/review-v1.json"
LABELS = {"grounded": {"yes", "no"}, "usefulness": {"useful", "needs_work", "wrong"}, "metric_sensible": {"yes", "no"}}
TARGETS = {"useful_at_least": 6, "wrong_at_most": 1, "metric_sensible_at_least": 8}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("completed", type=Path)
    args = parser.parse_args()
    original = list(csv.DictReader(ORIGINAL.open()))
    completed = [r for r in csv.DictReader(args.completed.open()) if any(r.values())]
    if len(completed) != len(original):
        raise ValueError(f"expected {len(original)} rows, got {len(completed)}")
    for o, c in zip(original, completed):
        changed = [k for k in o if k not in LABELS and k != "reviewer_notes" and o[k] != c.get(k)]
        if changed:
            raise ValueError(f"{o['review_id']}: non-review columns changed: {changed}")
        for k, allowed in LABELS.items():
            if c[k].strip() not in allowed:
                raise ValueError(f"{o['review_id']}: {k}={c[k]!r} not in {sorted(allowed)}")
    if OWNER.exists() or RESULT.exists():
        raise FileExistsError("review already imported; results are immutable")
    shutil.copyfile(args.completed, OWNER)
    use, metric, grounded = (Counter(r[k].strip() for r in completed) for k in ("usefulness", "metric_sensible", "grounded"))
    met = {"useful_at_least_6": use["useful"] >= 6, "wrong_at_most_1": use["wrong"] <= 1, "metric_sensible_at_least_8": metric["yes"] >= 8}
    result = {"reviewer": "owner", "rows": len(completed), "usefulness": dict(use), "metric_sensible": dict(metric),
              "grounded": dict(grounded), "targets": TARGETS, "targets_met": met, "pass": all(met.values()),
              "rows_detail": [{k: r[k] for k in ("review_id", "opportunity_id", "grounded", "usefulness", "metric_sensible", "reviewer_notes")}
                              for r in completed]}
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: result[k] for k in ("usefulness", "metric_sensible", "grounded", "targets_met", "pass")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
