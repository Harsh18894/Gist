"""Offline, opt-in retrieval scoring; v2 answer validation is separate."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import connection  # noqa: E402
from app.dataset import default_db_path  # noqa: E402
from app.rag.retrieval import Filters, hits_for_ids, hybrid_search, keyword_search  # noqa: E402


def evaluate_v1() -> dict:
    questions = json.loads((ROOT / "evals/questions.json").read_text())["questions"]
    results: dict[str, dict] = {}
    with connection(default_db_path("v1", ROOT)) as db:
        has_meta = db.execute("SELECT name FROM sqlite_master WHERE name='dataset_meta'").fetchone()
        version = db.execute("SELECT value FROM dataset_meta WHERE key='version'").fetchone() if has_meta else None
        if version and version[0] != "v1":
            raise ValueError("The v1 evaluator needs a v1 database.")
        for strategy in ("keyword", "hybrid_demo"):
            hits_at_1 = hits_at_5 = 0
            reciprocal_rank = 0.0
            misses: list[str] = []
            for item in questions:
                if strategy == "keyword":
                    ids = keyword_search(db, item["question"], Filters(), limit=5)
                    hits = hits_for_ids(db, ids, "keyword")
                else:
                    hits = hybrid_search(db, item["question"], Filters(), limit=5)
                found = next((rank for rank, hit in enumerate(hits, 1)
                              if hit.source_id in item["source_ids"]), None)
                if found == 1:
                    hits_at_1 += 1
                if found is not None:
                    hits_at_5 += 1
                    reciprocal_rank += 1 / found
                else:
                    misses.append(item["id"])
            count = len(questions)
            results[strategy] = {"questions": count, "recall_at_1": round(hits_at_1 / count, 3),
                                 "recall_at_5": round(hits_at_5 / count, 3),
                                 "mrr_at_5": round(reciprocal_rank / count, 3), "misses": misses}
    return {"dataset_version": "v1", "benchmark": "evals/questions.json", "strategies": results}


def evaluate_v2() -> dict:
    """Legacy entry point disabled after freezing the v2 held-out split."""
    raise RuntimeError("Pulse v2 has a frozen held-out split. Use run_v2_retrieval.py on the development set.")


def evaluate(dataset: str = "v1") -> dict:
    return evaluate_v1() if dataset == "v1" else evaluate_v2()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["v1", "v2"], default="v1")
    parser.add_argument("--save", action="store_true", help="Write results to the version-specific evals directory")
    args = parser.parse_args()
    result = evaluate(args.dataset)
    if args.save:
        path = ROOT / "evals" / args.dataset / "retrieval-results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
