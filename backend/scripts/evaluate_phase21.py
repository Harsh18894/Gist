"""Replay frozen v2 DEVELOPMENT rankings offline; never evaluate v2 held-out."""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import connection  # noqa: E402
from app.dataset import default_db_path  # noqa: E402
from app.rag.phase21 import InvestigationConfig, investigate  # noqa: E402
from app.rag.retrieval import Filters  # noqa: E402
from scripts.freeze_v2_split import verify  # noqa: E402

BASELINE = ROOT / "evals/v2/results/development-all.json"
JUDGMENTS = ROOT / "evals/v2/development-judgments.json"
OUTPUT = ROOT / "evals/phase21/development-experiments-v4.json"
EXPERIMENTS = {
    "keyword_replay": InvestigationConfig(max_subqueries=0, vector_weight=0),
    "decomposition_only": InvestigationConfig(vector_weight=0),
    "document_boost_only": InvestigationConfig(max_subqueries=0, vector_weight=0, document_boost=0.75),
    "diversity_only": InvestigationConfig(max_subqueries=0, vector_weight=0, diversity_penalty=0.25),
    "hybrid_keyword_heavy": InvestigationConfig(max_subqueries=0, vector_weight=0.35),
    "focused_decomposition": InvestigationConfig(vector_weight=0, focused_subqueries=True),
    "evidence_quota": InvestigationConfig(vector_weight=0, focused_subqueries=True, evidence_quota=True),
    "combined": InvestigationConfig(vector_weight=0.35, document_boost=0.75, diversity_penalty=0.25),
    "combined_focused_quota": InvestigationConfig(vector_weight=0.35, document_boost=0.75,
                                                    focused_subqueries=True, evidence_quota=True),
}


def _metrics(ids: list[str], judgment: dict) -> dict:
    relevant = set(judgment["reviewed_relevant_source_ids"])
    groups = [set(group) for group in judgment["evidence_groups"]]
    rank = next((position for position, source_id in enumerate(ids[:5], 1) if source_id in relevant), None)
    return {"hit_at_5": int(rank is not None) if relevant else None,
            "mrr_at_5": round(1 / rank, 4) if rank else (0 if relevant else None),
            "reviewed_coverage_at_20": round(len(relevant.intersection(ids[:20])) / len(relevant), 4) if relevant else None,
            "group_coverage_at_20": round(sum(bool(group.intersection(ids[:20])) for group in groups) / len(groups), 4) if groups else None}


def _aggregate(rows: list[dict]) -> dict:
    answerable = [row for row in rows if row["metrics"]["hit_at_5"] is not None]
    groups = [row for row in answerable if row["metrics"]["group_coverage_at_20"] is not None]
    timing = sorted(row["latency_ms"] for row in rows)
    return {"questions": len(rows), "answerable": len(answerable),
            "judged_hit_at_5": round(statistics.mean(row["metrics"]["hit_at_5"] for row in answerable), 4) if answerable else None,
            "mrr_at_5": round(statistics.mean(row["metrics"]["mrr_at_5"] for row in answerable), 4) if answerable else None,
            "reviewed_coverage_at_20": round(statistics.mean(row["metrics"]["reviewed_coverage_at_20"] for row in answerable), 4) if answerable else None,
            "group_coverage_at_20": round(statistics.mean(row["metrics"]["group_coverage_at_20"] for row in groups), 4) if groups else None,
            "p50_latency_ms": round(timing[len(timing)//2], 3),
            "p95_latency_ms": round(timing[min(len(timing)-1, int(len(timing)*.95))], 3),
            "total_subqueries": sum(row["subquery_count"] for row in rows),
            "additional_paid_calls": 0,
            "additional_api_cost_usd": 0.0,
            "projected_uncached_query_embedding_cost_usd": round(sum(
                row["projected_uncached_query_embedding_cost_usd"] for row in rows), 8)}


def run() -> dict:
    manifest = verify()
    saved = json.loads(BASELINE.read_text())
    if saved["source_sha256"] != manifest["source_sha256"] or saved["benchmark_sha256"] != manifest["benchmark_sha256"] or saved["split"] != "development":
        raise ValueError("Development replay baseline differs from frozen corpus/benchmark.")
    judgments = {item["question_id"]: item for item in json.loads(JUDGMENTS.read_text())["questions"]}
    questions = {item["id"]: item for item in json.loads((ROOT / "evals/v2/questions.json").read_text())["questions"]
                 if item["id"] in manifest["development_ids"]}
    previous = {strategy: {row["question_id"]: row for row in rows}
                for strategy, rows in saved["per_question"].items()}
    output = {"benchmark_version": "v2-baseline-1", "split": "development",
              "source_sha256": manifest["source_sha256"], "benchmark_sha256": manifest["benchmark_sha256"],
              "method": "Offline replay of saved original-query top-20 keyword/vector source IDs; additional subqueries use local FTS5. No query embedding or generation calls.",
              "limitations": "Judgments are non-exhaustive. Replay candidate pool is the saved top 20 for each original-query branch; measured trial latencies exclude paid query embedding and include Python/SQLite execution.",
              "experiments": {}}
    with connection(default_db_path("v2", ROOT)) as db:
        version = db.execute("SELECT value FROM dataset_meta WHERE key='version'").fetchone()[0]
        digest = db.execute("SELECT value FROM dataset_meta WHERE key='source_sha256'").fetchone()[0]
        if version != "v2" or digest != manifest["source_sha256"]:
            raise ValueError("Only the frozen v2 database may be used.")
        for name, config in EXPERIMENTS.items():
            rows = []
            for qid in manifest["development_ids"]:
                item = questions[qid]
                started = time.perf_counter()
                hits, trace = investigate(db, item["question"], Filters(), config,
                                          keyword_candidates=previous["keyword"][qid]["retrieved_source_ids"],
                                          vector_candidates=previous["vector"][qid]["retrieved_source_ids"])
                elapsed = (time.perf_counter() - started) * 1000
                ids = [hit.source_id for hit in hits]
                rows.append({"question_id": qid, "category": item["evaluation_category"],
                             "question_type": trace["question_type"], "source_ids": ids,
                             "source_kinds": [hit.kind for hit in hits],
                             "evidence_needs_by_source": {hit.source_id: list(hit.evidence_needs) for hit in hits if hit.evidence_needs},
                             "subqueries": trace["subqueries"], "subquery_count": len(trace["subqueries"]),
                             "additional_api_calls": 0, "estimated_additional_api_cost_usd": 0.0,
                             "projected_uncached_query_embedding_cost_usd": round(
                                 math.ceil(len(item["question"].encode()) / 4) * .02 / 1_000_000, 8),
                             "latency_ms": round(elapsed, 3), "metrics": _metrics(ids, judgments[qid])})
            categories = defaultdict(list)
            for row in rows:
                categories[row["category"]].append(row)
            output["experiments"][name] = {"config": config.__dict__, "aggregate": _aggregate(rows),
                                            "by_category": {key: _aggregate(value) for key, value in categories.items()},
                                            "per_question": rows}
    return output


if __name__ == "__main__":
    result = run()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        raise FileExistsError("Refusing to overwrite an existing Phase 2.1 development experiment result.")
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    for name, value in result["experiments"].items():
        print(name, value["aggregate"])
