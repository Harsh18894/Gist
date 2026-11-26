"""Create the Phase 3.5 owner review sheet: 10 experiment suggestions sampled by a fixed hash.

Sampling: drafts that passed checks, ordered by sha256(opportunity_id); the first 10 are
taken. No API calls. Refuses to overwrite an existing sheet.
"""
from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import os  # noqa: E402
os.environ.setdefault("GIST_DATASET_VERSION", "v2")
from app.database import connection  # noqa: E402
from app.experiments import experiments  # noqa: E402

OUT = ROOT / "evals/phase35/review/experiment-review.csv"
SAMPLE = 10
REVIEW_COLUMNS = ["grounded", "usefulness", "metric_sensible", "reviewer_notes"]


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"{OUT} exists; the review sheet is created once.")
    with connection() as db:
        data = experiments(db)
    drafts = sorted((e for e in data["experiments"] if e["status"] == "draft"),
                    key=lambda e: hashlib.sha256(e["opportunity_id"].encode()).hexdigest())[:SAMPLE]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["review_id", "opportunity_id", "evidence_url", "facts_problem", "facts_segments",
                         "hypothesis", "intervention", "target_audience", "primary_metric", "guardrail_metrics",
                         "design", "risks", "assumptions_to_validate", *REVIEW_COLUMNS])
        for i, e in enumerate(drafts, 1):
            s = e["suggestion"]
            writer.writerow([f"EXP-R{i:02d}", e["opportunity_id"], f"http://localhost:3000/opportunities?open={e['opportunity_id']}",
                             e["facts"]["problem_statement"], e["facts"]["affected_segments_text"],
                             s["hypothesis"], s["intervention"], s["target_audience"],
                             f"{s['primary_metric']['name']}: {s['primary_metric']['definition']}",
                             " | ".join(f"{g['name']}: {g['why']}" for g in s["guardrail_metrics"]),
                             f"{s['experiment_design']['type']}: {s['experiment_design']['description']}",
                             " | ".join(s["risks"]), " | ".join(s["assumptions_to_validate"]), "", "", "", ""])
    print(f"Wrote {len(drafts)} rows to {OUT.relative_to(ROOT)}: {', '.join(e['opportunity_id'] for e in drafts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
