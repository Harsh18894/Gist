"""$0 development-only retrieval trials on gist-phase2.1-benchmark-3-reviewed.

Reads query vectors from the exact-question cache filled by the approved paid
baseline run. A cache miss stops the run: this script never calls an API.
Held-out questions are never selected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/scripts"))

from app.rag.candidate_v3 import CandidateConfig, retrieve  # noqa: E402
from app.rag.provider import EMBED_MODEL  # noqa: E402
from app.rag.retrieval import Filters, hybrid_search  # noqa: E402
import evaluate_benchmark3_dev as evaluation  # noqa: E402

DB = ROOT / "backend/gist-v2.sqlite3"
TRIALS: dict[str, CandidateConfig | None] = {
    "T0_locked_hybrid": None,
    "T1_source_rrf_equal": CandidateConfig(),
    "T2_vector_weight_1_5": CandidateConfig(vector_weight=1.5),
    "T3_vector_weight_2": CandidateConfig(vector_weight=2.0),
    "T4_document_slot": CandidateConfig(document_slot=True),
    "T5_generic_decomposition": CandidateConfig(decompose=True),
    "T6_mmr_0_7": CandidateConfig(mmr_lambda=0.7),
    # Round 2: only neighbours of the round-1 leader, to limit tuning on 15 questions.
    "T7_mmr_0_5": CandidateConfig(mmr_lambda=0.5),
    "T8_mmr_0_85": CandidateConfig(mmr_lambda=0.85),
    "T9_mmr_0_7_vector_2": CandidateConfig(mmr_lambda=0.7, vector_weight=2.0),
}


def cached_vector(db: sqlite3.Connection, question: str) -> np.ndarray:
    meta = dict(db.execute("SELECT key,value FROM dataset_meta WHERE key IN ('version','source_sha256')"))
    key = hashlib.sha256(json.dumps([meta["version"], meta["source_sha256"], EMBED_MODEL, question],
                                    ensure_ascii=False).encode()).hexdigest()
    row = db.execute("SELECT dimensions,vector FROM query_embedding_cache WHERE cache_key=?", (key,)).fetchone()
    if not row:
        raise LookupError("Query vector is not cached; this $0 runner will not make a paid call.")
    vector = np.frombuffer(row[1], dtype=np.float32)
    if len(vector) != row[0] or not np.isfinite(vector).all():
        raise ValueError("Cached query vector is invalid.")
    return vector.copy()


def run(trials: dict[str, CandidateConfig | None]) -> dict:
    manifest, questions = evaluation.development_questions()
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        if dict(db.execute("SELECT key,value FROM dataset_meta")).get("source_sha256") != manifest["source_sha256"]:
            raise ValueError("The v2 index does not match the benchmark's frozen corpus.")
        db.row_factory = sqlite3.Row
        kinds = {row[0]: row[1] for row in db.execute("SELECT id,kind FROM sources")}
        vectors = {q["id"]: cached_vector(db, q["question"]) for q in questions}
        rows: dict[str, list[dict]] = {name: [] for name in trials}
        for question in questions:
            for name, config in trials.items():
                started = time.perf_counter()
                if config is None:
                    ids = [hit.source_id for hit in hybrid_search(db, question["question"], Filters(), model=EMBED_MODEL,
                                                                  query_vector=vectors[question["id"]], limit=20)]
                    trace = {"subqueries": []}
                else:
                    ids, trace = retrieve(db, question["question"], Filters(), vectors[question["id"]], EMBED_MODEL, config)
                rows[name].append({"question_id": question["id"], "category": question["category"],
                                   "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                                   "subqueries": len(trace.get("subqueries", [])), "trace": trace,
                                   **evaluation.score(question, ids[:20], kinds)})
    reference = rows[next(iter(trials))]
    changes = {}
    for name, values in rows.items():
        changes[name] = {"improved": [], "regressed": []}
        for base, row in zip(reference, values):
            if not row["answerable"]:
                continue
            delta = (row["hit_at_5"] - base["hit_at_5"], row["mrr_at_5"] - base["mrr_at_5"],
                     row["evidence_group_coverage_at_20"] - base["evidence_group_coverage_at_20"])
            if any(value < 0 for value in delta):
                changes[name]["regressed"].append(row["question_id"])
            elif any(value > 0 for value in delta):
                changes[name]["improved"].append(row["question_id"])
    return {"benchmark_version": "gist-phase2.1-benchmark-3-reviewed", "split": "development",
            "questions_sha256": manifest["questions_sha256"], "api_calls": 0,
            "trials": {name: (asdict(config) if config else "locked v2 hybrid_search") for name, config in trials.items()},
            "strategies": {name: evaluation.aggregate(values) for name, values in rows.items()},
            "per_question_changes_vs_reference": changes, "per_question": rows,
            "limitations": ("Development only, 15 answerable questions with non-exhaustive owner-reviewed labels; "
                            "trials were chosen with these questions visible, so the winner's score is optimistic.")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--trials", help="Comma-separated subset of trial names")
    args = parser.parse_args()
    target = evaluation.RESULTS / f"benchmark3-development-trials-{args.label}.json"
    if target.exists():
        raise FileExistsError(f"{target} exists; use a new label.")
    selected = TRIALS if not args.trials else {name: TRIALS[name] for name in args.trials.split(",")}
    result = run(selected)
    target.write_text(json.dumps(result, indent=2) + "\n")
    for name, values in result["strategies"].items():
        change = result["per_question_changes_vs_reference"][name]
        print(f"{name:28} hit5={values['judged_hit_rate_at_5']:.3f} mrr5={values['mrr_at_5']:.3f} "
              f"group20={values['evidence_group_coverage_at_20']:.3f} cov20={values['reviewed_coverage_at_20']:.3f} "
              f"incomplete={values['questions_with_incomplete_groups_at_20']} subq={values['subqueries_total']} "
              f"p50={values['retrieval_latency_p50_ms']:.1f}ms +{change['improved']} -{change['regressed']}")
    print(f"Saved {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
