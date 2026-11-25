"""ONE-TIME final retrieval test on the six benchmark-3 held-out questions.

Runs only with --heldout-final after the retrieval lock verifies, and refuses to
run again once a result file exists. The locked candidate is compared with
keyword, vector and the locked v2 hybrid under identical rules. Query
embeddings are paid on a cache miss (six at most) behind the existing approval
flags and shared $0.50 ledger. No answers are generated.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/scripts"))

from app.database import connection  # noqa: E402
from app.rag.candidate_v3 import LOCKED_CONFIG, retrieve  # noqa: E402
from app.rag.evidence import assess  # noqa: E402
from app.rag.provider import EMBED_MODEL, embed_query_cached  # noqa: E402
from app.rag.retrieval import Filters, Hit, hybrid_search, keyword_search, semantic_search  # noqa: E402
import evaluate_benchmark3_dev as evaluation  # noqa: E402
import import_phase21_review as review  # noqa: E402
from lock_benchmark3_retrieval import verify_lock  # noqa: E402

RESULT = evaluation.RESULTS / "benchmark3-heldout-final.json"


def heldout_questions(benchmark_dir: Path = review.OUT) -> tuple[dict, list[dict]]:
    manifest = review.verify(benchmark_dir)
    benchmark = json.loads((benchmark_dir / "benchmark.json").read_text())
    selected = [q for q in benchmark["questions"] if q["id"] in set(manifest["heldout_ids"])]
    if len(selected) != 6 or any(q["split"] != "heldout" for q in selected):
        raise ValueError("Held-out selection does not match the frozen manifest.")
    return manifest, selected


def _gate(db, question: str, source_ids: list[str]) -> dict:
    hits = [Hit(f"{sid}:000", sid, "", "", "", None, None, None,
                db.execute("SELECT content FROM sources WHERE id=?", (sid,)).fetchone()[0], 1.0, 1, None)
            for sid in source_ids[:5]]
    result = assess(question, hits)
    return {"evidence_gate_top5_sufficient": result.sufficient, "evidence_gate_reason": result.reason}


def run() -> dict:
    lock = verify_lock()
    if RESULT.exists():
        raise FileExistsError("The held-out set was already run once; it must not be rerun.")
    if os.getenv("GIST_DATASET_VERSION") != "v2":
        raise RuntimeError("Set GIST_DATASET_VERSION=v2.")
    manifest, questions = heldout_questions()
    rows: dict[str, list[dict]] = {name: [] for name in ("keyword", "vector", "hybrid_locked_v2", "candidate_locked")}
    embeddings = []
    with connection() as db:
        if dict(db.execute("SELECT key,value FROM dataset_meta")).get("source_sha256") != manifest["source_sha256"]:
            raise ValueError("The v2 index does not match the benchmark's frozen corpus.")
        kinds = dict(db.execute("SELECT id,kind FROM sources"))
        for question in questions:
            started = time.perf_counter()
            vector, usage = embed_query_cached(db, question["question"])
            embeddings.append({"question_id": question["id"], "cache_hit": usage.get("cache_hit", False),
                               "input_tokens": usage.get("input_tokens", 0),
                               "estimated_cost_usd": usage.get("estimated_cost_usd", 0.0),
                               "latency_ms": round((time.perf_counter() - started) * 1000, 3)})
            for name in rows:
                started = time.perf_counter()
                if name == "keyword":
                    ids = evaluation._sources(db, keyword_search(db, question["question"], Filters(), limit=50))
                elif name == "vector":
                    ids = evaluation._sources(db, [c for c, _ in semantic_search(db, vector, EMBED_MODEL, Filters(), limit=50)])
                elif name == "hybrid_locked_v2":
                    ids = [h.source_id for h in hybrid_search(db, question["question"], Filters(), model=EMBED_MODEL,
                                                              query_vector=vector, limit=20)]
                else:
                    ids, _trace = retrieve(db, question["question"], Filters(), vector, EMBED_MODEL, LOCKED_CONFIG)
                latency = round((time.perf_counter() - started) * 1000, 3)
                rows[name].append({"question_id": question["id"], "category": question["category"],
                                   "latency_ms": latency, **_gate(db, question["question"], ids),
                                   **evaluation.score(question, ids[:20], kinds)})
    result = {"benchmark_version": review.BENCHMARK_VERSION, "split": "heldout", "run": "one-time final",
              "lock_sha256": lock["lock_sha256"], "questions_sha256": manifest["questions_sha256"],
              "heldout_sha256": manifest["heldout_sha256"], "embedding_model": EMBED_MODEL,
              "strategies": {name: evaluation.aggregate(values) for name, values in rows.items()},
              "query_embeddings": embeddings, "per_question": rows,
              "limitations": ("Six held-out questions (five answerable): directional evidence only. Labels are "
                              "owner-reviewed, non-exhaustive subsets; full Recall@K is not reported. Retrieval only.")}
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    with RESULT.open("x") as handle:  # exclusive create: a second run cannot overwrite
        handle.write(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--heldout-final", action="store_true", required=True,
                        help="Confirms this is the single approved held-out run")
    parser.parse_args()
    result = run()
    print(json.dumps({name: {k: v for k, v in values.items() if k != "by_category"}
                      for name, values in result["strategies"].items()}, indent=2))
    print(f"Saved {RESULT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
