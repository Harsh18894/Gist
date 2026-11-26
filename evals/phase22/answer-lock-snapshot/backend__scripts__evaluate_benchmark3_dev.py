"""Development-only retrieval comparison on gist-phase2.1-benchmark-3-reviewed.

Compares keyword, vector, the locked original hybrid, and the Phase 2.1 candidate
on the 18 development questions. Held-out questions are filtered out before any
retrieval and there is no option to include them. Learned modes use one cached
query embedding per question; a cache miss is a paid call behind the existing
approval flags and shared $0.50 ledger. `--offline` runs keyword only at $0.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/scripts"))

from app.database import connection  # noqa: E402
from app.rag.evidence import assess  # noqa: E402
from app.rag.phase21 import InvestigationConfig, investigate  # noqa: E402
from app.rag.provider import EMBED_MODEL, embed_query_cached  # noqa: E402
from app.rag.retrieval import Filters, hits_for_ids, hybrid_search, keyword_search, semantic_search  # noqa: E402
import import_phase21_review as review  # noqa: E402

RESULTS = ROOT / "evals/phase21/results"
CANDIDATE = InvestigationConfig(vector_weight=0.35, document_boost=0.75,
                                focused_subqueries=True, evidence_quota=True)
STRATEGIES = ("keyword", "vector", "hybrid_locked", "phase21_candidate")


def development_questions(benchmark_dir: Path = review.OUT) -> tuple[dict, list[dict]]:
    manifest = review.verify(benchmark_dir)
    benchmark = json.loads((benchmark_dir / "benchmark.json").read_text())
    selected = [q for q in benchmark["questions"] if q["split"] == "development"]
    if [q["id"] for q in selected] != manifest["development_ids"] or any(q["split"] != "development" for q in selected):
        raise ValueError("Development selection does not match the frozen manifest.")
    return manifest, selected


def _sources(db, chunk_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(hit.source_id for hit in hits_for_ids(db, chunk_ids, "keyword")))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def score(question: dict, ids: list[str], kinds: dict[str, str]) -> dict:
    relevant = set(question["relevant_source_ids"])
    negatives = set(question["hard_negative_source_ids"])
    partial = set(question["partial_source_ids"])
    top5, top20 = ids[:5], ids[:20]
    first = next((rank for rank, sid in enumerate(top5, 1) if sid in relevant), None)
    first_any = next((rank for rank, sid in enumerate(top20, 1) if sid in relevant), None)
    row = {"retrieved_source_ids": top20,
           "top5_kinds": [kinds.get(sid) for sid in top5],
           "duplicate_source_ids": len(ids) - len(set(ids)),
           "hard_negatives_in_top5": sorted(negatives & set(top5)),
           "hard_negatives_above_first_relevant": sorted(
               sid for sid in top20[:(first_any - 1) if first_any else 20] if sid in negatives),
           "partial_sources_in_top5": sorted(partial & set(top5))}
    if not relevant:
        return {**row, "answerable": False}
    groups = question["evidence_groups"]
    covered = [bool(set(group) & set(top20)) for group in groups]
    return {**row, "answerable": True,
            "hit_at_5": int(first is not None), "mrr_at_5": round(1 / first, 4) if first else 0.0,
            "first_relevant_rank_at_20": first_any,
            "reviewed_coverage_at_20": round(len(relevant & set(top20)) / len(relevant), 4),
            "evidence_group_coverage_at_20": round(sum(covered) / len(groups), 4),
            "missed_evidence_groups": [index + 1 for index, ok in enumerate(covered) if not ok],
            "documents_relevant": sorted(sid for sid in relevant if kinds.get(sid) in {"prd", "release_note"}),
            "documents_relevant_retrieved_at_20": sorted(
                sid for sid in relevant & set(top20) if kinds.get(sid) in {"prd", "release_note"})}


def aggregate(rows: list[dict]) -> dict:
    answerable = [row for row in rows if row["answerable"]]
    mean = lambda key: round(statistics.mean(row[key] for row in answerable), 4)
    by_category: dict[str, dict] = {}
    for category in sorted({row["category"] for row in answerable}):
        subset = [row for row in answerable if row["category"] == category]
        by_category[category] = {"questions": len(subset),
                                 "hit_at_5": round(statistics.mean(r["hit_at_5"] for r in subset), 4),
                                 "evidence_group_coverage_at_20": round(statistics.mean(
                                     r["evidence_group_coverage_at_20"] for r in subset), 4)}
    latencies = [row["latency_ms"] for row in rows]
    return {"questions": len(rows), "answerable_questions": len(answerable),
            "judged_hit_rate_at_5": mean("hit_at_5"), "mrr_at_5": mean("mrr_at_5"),
            "reviewed_coverage_at_20": mean("reviewed_coverage_at_20"),
            "evidence_group_coverage_at_20": mean("evidence_group_coverage_at_20"),
            "questions_with_no_relevant_in_top20": sum(row["first_relevant_rank_at_20"] is None for row in answerable),
            "questions_with_incomplete_groups_at_20": sum(bool(row["missed_evidence_groups"]) for row in answerable),
            "hard_negative_in_top5_questions": sum(bool(row["hard_negatives_in_top5"]) for row in rows),
            "duplicate_source_results": sum(row["duplicate_source_ids"] for row in rows),
            "subqueries_total": sum(row.get("subqueries", 0) for row in rows),
            "retrieval_latency_p50_ms": round(_percentile(latencies, .5), 3),
            "retrieval_latency_p95_ms": round(_percentile(latencies, .95), 3),
            "by_category": by_category}


def run(*, offline: bool, benchmark_dir: Path = review.OUT) -> dict:
    manifest, questions = development_questions(benchmark_dir)
    strategies = ("keyword",) if offline else STRATEGIES
    if os.getenv("GIST_DATASET_VERSION") != "v2":
        raise RuntimeError("Set GIST_DATASET_VERSION=v2.")
    rows: dict[str, list[dict]] = {name: [] for name in strategies}
    embedding: list[dict] = []
    with connection() as db:
        meta = dict(db.execute("SELECT key,value FROM dataset_meta"))
        if meta.get("source_sha256") != manifest["source_sha256"]:
            raise ValueError("The v2 index does not match the benchmark's frozen corpus.")
        if not offline:
            learned = db.execute("SELECT COUNT(*) FROM embeddings WHERE model=?", (EMBED_MODEL,)).fetchone()[0]
            if learned != db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]:
                raise RuntimeError("Learned source vectors are incomplete.")
        kinds = dict(db.execute("SELECT id,kind FROM sources"))
        for question in questions:
            vector = None
            if not offline:
                started = time.perf_counter()
                vector, usage = embed_query_cached(db, question["question"])
                embedding.append({"question_id": question["id"], "cache_hit": usage.get("cache_hit", False),
                                  "input_tokens": usage.get("input_tokens", 0),
                                  "estimated_cost_usd": usage.get("estimated_cost_usd", 0.0),
                                  "latency_ms": round((time.perf_counter() - started) * 1000, 3)})
            for name in strategies:
                started = time.perf_counter()
                extra: dict = {}
                if name == "keyword":
                    ids = _sources(db, keyword_search(db, question["question"], Filters(), limit=50))
                elif name == "vector":
                    ids = _sources(db, [cid for cid, _ in semantic_search(db, vector, EMBED_MODEL, Filters(), limit=50)])
                elif name == "hybrid_locked":
                    hits = hybrid_search(db, question["question"], Filters(), model=EMBED_MODEL,
                                         query_vector=vector, limit=20)
                    ids = [hit.source_id for hit in hits]
                    gate = assess(question["question"], hits[:5])
                    extra = {"evidence_gate_top5_sufficient": gate.sufficient, "evidence_gate_reason": gate.reason}
                else:
                    found, trace = investigate(db, question["question"], Filters(), CANDIDATE,
                                               vector=vector, model=EMBED_MODEL)
                    ids = [hit.source_id for hit in found]
                    extra = {"question_type": trace["question_type"], "subqueries": len(trace["subqueries"]),
                             "subquery_text": trace["subqueries"]}
                latency = (time.perf_counter() - started) * 1000
                rows[name].append({"question_id": question["id"], "category": question["category"],
                                   "latency_ms": round(latency, 3), **extra,
                                   **score(question, ids[:20], kinds)})
    return {"benchmark_version": review.BENCHMARK_VERSION, "split": "development",
            "questions_sha256": manifest["questions_sha256"], "source_sha256": manifest["source_sha256"],
            "embedding_model": None if offline else EMBED_MODEL,
            "candidate_config": CANDIDATE.__dict__,
            "strategies": {name: aggregate(values) for name, values in rows.items()},
            "query_embeddings": embedding,
            "per_question": rows,
            "limitations": ("Development split only. Relevance labels are owner-reviewed, non-exhaustive subsets, so "
                            "full Recall@K is not reported. Phase 2.1 subquery vocabulary was written while older v2 "
                            "development questions were visible; candidate scores may be optimistic. Retrieval only; "
                            "no answers were generated.")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="Keyword only; no learned vectors or API calls")
    parser.add_argument("--label", required=True, help="Result name, e.g. baseline")
    args = parser.parse_args()
    target = RESULTS / f"benchmark3-development-{args.label}.json"
    if target.exists():
        raise FileExistsError(f"{target} exists; results are kept immutable. Use a new label.")
    result = run(offline=args.offline)
    RESULTS.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({name: {key: value for key, value in values.items() if key != "by_category"}
                      for name, values in result["strategies"].items()}, indent=2))
    print(f"Saved {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
