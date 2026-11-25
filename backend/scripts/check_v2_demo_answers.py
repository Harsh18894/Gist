"""Offline deterministic checks for the development-set extractive demo only."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.dataset import default_db_path  # noqa: E402
from app.rag.service import answer  # noqa: E402
from app.schemas import AskRequest  # noqa: E402
from freeze_v2_split import verify  # noqa: E402


def run() -> dict:
    manifest = verify()
    questions = {item["id"]: item for item in json.loads((ROOT / "evals/v2/questions.json").read_text())["questions"]}
    rows = []
    with sqlite3.connect(f"file:{default_db_path('v2', ROOT)}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        for question_id in manifest["development_ids"]:
            item = questions[question_id]
            result = answer(db, AskRequest(question=item["question"], mode="demo"))
            source_ids = [hit.source_id for hit in result.retrieved_sources]
            valid_sources = all(db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone() for source_id in source_ids)
            expected_abstention = item["evaluation_category"] == "unanswerable"
            rows.append({"question_id": question_id, "category": item["evaluation_category"],
                         "status": result.status, "retrieved_source_ids": source_ids,
                         "retrieved_source_ids_valid": valid_sources,
                         "generated_citations_empty": not result.citations,
                         "expected_abstention": expected_abstention,
                         "abstention_correct": result.status == "insufficient_evidence" if expected_abstention else None,
                         "latency_ms": result.latency_ms})
    unanswerable = [row for row in rows if row["expected_abstention"]]
    return {"dataset_version": "v2", "split": "development", "split_version": manifest["split_version"],
            "mode": "demo", "questions": len(rows), "retrieved_source_ids_valid": all(row["retrieved_source_ids_valid"] for row in rows),
            "generated_citations_empty": all(row["generated_citations_empty"] for row in rows),
            "unanswerable_questions": len(unanswerable),
            "correct_abstentions": sum(row["abstention_correct"] for row in unanswerable),
            "answer_correctness": "BLOCKED: retrieval-only mode does not generate answers",
            "per_question": rows}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Offline development-split demo answer check.")
    parser.add_argument("--output", type=Path, default=ROOT / "evals/v2/results/development-demo-answers.json",
                        help="Result path; use a new file to keep earlier results as history.")
    args = parser.parse_args()
    result = run()
    path = args.output if args.output.is_absolute() else ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("questions", "retrieved_source_ids_valid", "generated_citations_empty", "unanswerable_questions", "correct_abstentions", "answer_correctness")}, indent=2))
