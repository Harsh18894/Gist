"""Version-locked Pulse v2 retrieval benchmark; paid paths require explicit flags."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.rag.provider import EMBED_MODEL, embed  # noqa: E402
from app.rag.retrieval import Filters, hits_for_ids, hybrid_search, keyword_search, semantic_search  # noqa: E402
from freeze_v2_split import verify  # noqa: E402
from scripts.lock_v2_retrieval import verify_lock  # noqa: E402

DB = ROOT / "backend/gist-v2.sqlite3"


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _unique_sources(db: sqlite3.Connection, chunk_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for hit in hits_for_ids(db, chunk_ids, "keyword"):
        if hit.source_id not in seen:
            seen.add(hit.source_id)
            result.append(hit.source_id)
    return result


def run(split: str = "development", *, include_paid_vectors: bool = False,
        heldout_final: bool = False) -> dict:
    manifest = verify()
    if split not in {"development", "heldout_test"}:
        raise ValueError("split must be development or heldout_test")
    if split == "heldout_test" and not heldout_final:
        raise PermissionError("The frozen held-out set requires --heldout-final; do not use it for tuning.")
    if split == "heldout_test":
        verify_lock()
    questions = {item["id"]: item for item in json.loads((ROOT / "evals/v2/questions.json").read_text())["questions"]}
    selected = [questions[qid] for qid in manifest["development_ids" if split == "development" else "heldout_test_ids"]]
    reviewed = ({row["question_id"]: row for row in json.loads(
        (ROOT / "evals/v2/development-judgments.json").read_text())["questions"]}
        if split == "development" else {})
    strategies = ["keyword"] + (["vector", "hybrid"] if include_paid_vectors else [])
    results: dict[str, list[dict]] = {strategy: [] for strategy in strategies}
    query_embedding_latency_ms: list[float] = []
    with sqlite3.connect(f"file:{DB}?mode=ro" if not include_paid_vectors else DB,
                         uri=not include_paid_vectors) as db:
        db.row_factory = sqlite3.Row
        version = db.execute("SELECT value FROM dataset_meta WHERE key='version'").fetchone()
        corpus_hash = db.execute("SELECT value FROM dataset_meta WHERE key='source_sha256'").fetchone()
        if not version or version[0] != "v2" or not corpus_hash or corpus_hash[0] != manifest["source_sha256"]:
            raise ValueError("The v2 index does not match the frozen source version.")
        if include_paid_vectors and db.execute("SELECT COUNT(*) FROM embeddings WHERE model=?", (EMBED_MODEL,)).fetchone()[0] != db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]:
            raise RuntimeError("BLOCKED: learned embeddings are incomplete; index them only after paid API approval.")
        for item in selected:
            question = item["question"]
            vector = None
            if include_paid_vectors:
                started = time.perf_counter()
                vector = embed(db, [question])[0][0]  # one query embedding shared across vector and hybrid
                query_embedding_latency_ms.append((time.perf_counter() - started) * 1000)
            for strategy in strategies:
                started = time.perf_counter()
                if strategy == "keyword":
                    ids = _unique_sources(db, keyword_search(db, question, Filters(), limit=50))[:20]
                elif strategy == "vector":
                    ids = _unique_sources(db, [chunk_id for chunk_id, _score in semantic_search(db, vector, EMBED_MODEL, Filters(), limit=50)])[:20]
                else:
                    ids = [hit.source_id for hit in hybrid_search(db, question, Filters(), model=EMBED_MODEL, query_vector=vector, limit=20)]
                latency = (time.perf_counter() - started) * 1000
                judgment = reviewed.get(item["id"])
                judged = set(judgment["reviewed_relevant_source_ids"] if judgment else item["relevant_source_ids"])
                groups = judgment["evidence_groups"] if judgment else []
                first = next((rank for rank, source_id in enumerate(ids[:5], 1) if source_id in judged), None)
                result = {"question_id": item["id"], "category": item["evaluation_category"],
                          "retrieved_source_ids": ids, "latency_ms": round(latency, 3),
                          "judged_evidence_ids": sorted(judged),
                          "judgment_completeness": judgment["judgment_completeness"] if judgment else item["judgment_completeness"],
                          "hit_rate_at_5": int(first is not None) if judged else None,
                          "mrr_at_5": round(1 / first, 4) if first else (0 if judged else None),
                          "reviewed_subset_coverage_at_20": round(len(judged.intersection(ids[:20])) / len(judged), 4) if judged else None,
                          "evidence_group_coverage_at_20": round(sum(bool(set(group) & set(ids[:20])) for group in groups) / len(groups), 4) if groups else None,
                          "full_corpus_recall_at_20": None,
                          "graded_ndcg_at_5": None}
                results[strategy].append(result)
    aggregates: dict[str, dict] = {}
    for strategy, rows in results.items():
        answerable = [row for row in rows if row["hit_rate_at_5"] is not None]
        latencies = [row["latency_ms"] for row in rows]
        aggregates[strategy] = {"questions": len(rows), "answerable_questions": len(answerable),
                                "judged_hit_rate_at_5": round(statistics.mean(row["hit_rate_at_5"] for row in answerable), 4),
                                "judged_mrr_at_5": round(statistics.mean(row["mrr_at_5"] for row in answerable), 4),
                                "reviewed_subset_coverage_at_20": round(statistics.mean(row["reviewed_subset_coverage_at_20"] for row in answerable), 4),
                                "evidence_group_coverage_at_20": round(statistics.mean(row["evidence_group_coverage_at_20"] for row in answerable if row["evidence_group_coverage_at_20"] is not None), 4) if split == "development" else None,
                                "retrieval_latency_p50_ms": round(_percentile(latencies, .5), 3),
                                "retrieval_latency_p95_ms": round(_percentile(latencies, .95), 3)}
    return {"dataset_version": "v2", "split": split, "split_version": manifest["split_version"],
            "source_sha256": manifest["source_sha256"], "benchmark_sha256": manifest["benchmark_sha256"],
            "strategies": aggregates, "query_embedding_latency_ms": [round(x, 3) for x in query_embedding_latency_ms],
            "per_question": results,
            "limitations": "Development judgments are source-reviewed subsets, not exhaustive. Group coverage is reported for broad questions. Full recall and graded nDCG are unavailable. No answer quality is measured."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "heldout_test"], default="development")
    parser.add_argument("--include-paid-vectors", action="store_true", help="May send paid query embedding calls; requires prior approval and server-side opt-in")
    parser.add_argument("--heldout-final", action="store_true", help="One-time final held-out evaluation after retrieval is locked")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    result = run(args.split, include_paid_vectors=args.include_paid_vectors, heldout_final=args.heldout_final)
    if args.save:
        path = ROOT / "evals/v2/results" / f"{args.split}-{'all' if args.include_paid_vectors else 'keyword'}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and args.split == "heldout_test":
            raise FileExistsError("Held-out results already exist; refusing to overwrite.")
        path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["strategies"], indent=2))
