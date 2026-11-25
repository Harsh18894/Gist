"""Bounded paid answer-quality check on gist-phase2.1-benchmark-3-reviewed.

Generates at most one answer per benchmark question (24) through the real Ask
Gist paid path (`service.answer`, mode "openai"), keeps the raw model text even
when Gist rejects it, runs deterministic checks, and writes a claim-review CSV
for the human reviewer. It runs once: an existing result file stops it. Query
embeddings come from the exact-question cache; generation is paid behind the
existing approval flags and shared $0.50 ledger, with a per-run stop at $0.02.
No retrieval or prompt setting is tuned from these results.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/scripts"))

from app.database import connection  # noqa: E402
from app.rag.budget import summary as spend_summary  # noqa: E402
from app.rag.provider import PaidApiDisabled, ProviderError  # noqa: E402
from app.rag.service import answer, cited_source_ids  # noqa: E402
from app.schemas import AskRequest  # noqa: E402
import import_phase21_review as review  # noqa: E402

RESULTS = ROOT / "evals/phase21/results"
RESULT = RESULTS / "benchmark3-answers.json"
REVIEW_CSV = RESULTS / "benchmark3-answer-claim-review.csv"
MAX_ANSWERS = 24
RUN_STOP_USD = 0.02


def checks(question: dict, response: dict, raw: str | None) -> dict:
    unanswerable = question["category"] == "unanswerable"
    cited = sorted(cited_source_ids(raw or "") or set())
    retrieved = [s["source_id"] for s in response["retrieved_sources"]]
    relevant = set(question["relevant_source_ids"])
    negatives = set(question["hard_negative_source_ids"])
    covered = [bool(set(group) & set(cited)) for group in question["evidence_groups"]]
    # Gist's final status decides abstention; a partial answer that names a gap is not an abstention.
    abstained = response["status"] == "insufficient_evidence"
    return {"expected_abstention": unanswerable, "abstained": abstained,
            "abstention_correct": abstained == unanswerable,
            "gist_status": response["status"],
            "model_called": raw is not None,
            "raw_cited_source_ids": cited,
            "cited_ids_all_retrieved": set(cited) <= set(retrieved),
            "cited_relevant": sorted(set(cited) & relevant),
            "cited_hard_negatives": sorted(set(cited) & negatives),
            "cited_unjudged": sorted(set(cited) - relevant - negatives - set(question["partial_source_ids"])),
            "evidence_groups_cited": f"{sum(covered)}/{len(covered)}" if covered else None,
            "retrieved_relevant_in_context": sorted(set(retrieved) & relevant)}


def run(*, development_only: bool = False, label: str | None = None) -> dict:
    """Answer every question once (original run) or, with a label, the development split only."""
    result_path = RESULTS / f"benchmark3-answers-{label}.json" if label else RESULT
    review_path = RESULTS / f"benchmark3-answer-claim-review-{label}.csv" if label else REVIEW_CSV
    if label and not development_only:
        raise ValueError("Labelled reruns are development-only; the held-out answers were already run once.")
    if result_path.exists():
        raise FileExistsError("The benchmark-3 answer check already ran; it is not rerun.")
    if os.getenv("GIST_DATASET_VERSION") != "v2":
        raise RuntimeError("Set GIST_DATASET_VERSION=v2.")
    manifest = review.verify()
    questions = json.loads((review.OUT / "benchmark.json").read_text())["questions"]
    if development_only:
        questions = [q for q in questions if q["id"] in set(manifest["development_ids"]) and q["split"] == "development"]
    if len(questions) > MAX_ANSWERS:
        raise ValueError("More questions than the approved answer bound.")
    spend_start = spend_summary()["committed_or_reserved_usd"]
    rows = []
    errors: list[dict] = []
    with connection() as db:
        if dict(db.execute("SELECT key,value FROM dataset_meta")).get("source_sha256") != manifest["source_sha256"]:
            raise ValueError("The v2 index does not match the benchmark's frozen corpus.")
        texts = dict(db.execute("SELECT id,content FROM sources"))
        for question in questions:
            if spend_summary()["committed_or_reserved_usd"] - spend_start > RUN_STOP_USD:
                raise RuntimeError("Per-run spend stop reached; remaining questions were not answered.")
            captured: list[str] = []
            started = time.perf_counter()
            try:
                result = answer(db, AskRequest(question=question["question"], mode="openai"),
                                audit_generated=captured.append)
            except (ProviderError, PaidApiDisabled) as exc:
                # Stop, but keep every answer already paid for. Billing for this one may be uncertain.
                errors.append({"question_id": question["id"], "error": type(exc).__name__, "message": str(exc)})
                break
            response = result.model_dump()
            raw = captured[0] if captured else None
            rows.append({"question_id": question["id"], "split": question["split"], "category": question["category"],
                         "question": question["question"], "expected_answer": question["expected_answer_or_abstention"],
                         "raw_model_answer": raw, "gist_answer": response["answer"],
                         "citations": [c["source_id"] for c in response["citations"]],
                         "retrieved_source_ids": [s["source_id"] for s in response["retrieved_sources"]],
                         "input_tokens": response["input_tokens"], "output_tokens": response["output_tokens"],
                         "estimated_cost_usd": response["estimated_cost_usd"],
                         "latency_ms": round((time.perf_counter() - started) * 1000),
                         **checks(question, response, raw)})
    spent = round(spend_summary()["committed_or_reserved_usd"] - spend_start, 8)
    answerable = [r for r in rows if not r["expected_abstention"]]
    summary = {"questions": len(rows), "stopped_early": bool(errors), "model_calls": sum(r["model_called"] for r in rows),
               "abstention_correct": sum(r["abstention_correct"] for r in rows),
               "unanswerable_abstained": f"{sum(r['abstained'] for r in rows if r['expected_abstention'])}/"
                                         f"{sum(r['expected_abstention'] for r in rows)}",
               "answerable_answered_by_gist": f"{sum(r['gist_status'] == 'answered' for r in answerable)}/{len(answerable)}",
               "answerable_partial_by_gist": f"{sum(r['gist_status'] == 'partial' for r in answerable)}/{len(answerable)}",
               "answerable_wrongly_refused": f"{sum(r['gist_status'] == 'insufficient_evidence' for r in answerable)}/{len(answerable)}",
               "answers_rejected_by_gist_after_generation": sum(r["model_called"] and r["gist_status"] == "insufficient_evidence" for r in rows),
               "answers_citing_a_hard_negative": sum(bool(r["cited_hard_negatives"]) for r in rows),
               "answers_with_cited_ids_outside_context": sum(not r["cited_ids_all_retrieved"] for r in rows),
               "run_estimated_cost_usd": spent,
               "latency_p50_ms": sorted(r["latency_ms"] for r in rows)[len(rows) // 2]}
    result = {"benchmark_version": review.BENCHMARK_VERSION, "pipeline": "service.answer mode=openai (v2 hybrid, Phase 2.2 answer path)" if label else "service.answer mode=openai (locked v2 hybrid)",
              "model": os.getenv("GIST_LLM_MODEL", "gpt-6-luna"), "summary": summary, "errors": errors, "answers": rows,
              "limitations": ("Deterministic checks verify abstention, citation IDs and label overlap only. "
                              "Claim-level support requires the human review CSV. One sample per question.")}
    RESULTS.mkdir(parents=True, exist_ok=True)
    with result_path.open("x") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    with review_path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["question_id", "split", "category", "question", "expected_answer", "generated_answer",
                         "gist_status", "cited_source_ids", "cited_source_texts", "auto_flags",
                         "claims_supported (all/some/none/n_a)", "unsupported_claims", "correct_abstention (yes/no)",
                         "overall (good/acceptable/poor)", "reviewer_comments", "reviewer_name", "review_date (YYYY-MM-DD)"])
        for r in rows:
            flags = [name for name, bad in (("cites_hard_negative", r["cited_hard_negatives"]),
                                            ("cites_outside_context", not r["cited_ids_all_retrieved"]),
                                            ("wrong_abstention", not r["abstention_correct"])) if bad]
            writer.writerow([r["question_id"], r["split"], r["category"], r["question"], r["expected_answer"],
                             r["raw_model_answer"] or r["gist_answer"], r["gist_status"], "; ".join(r["raw_cited_source_ids"]),
                             "\n\n".join(f"[{sid}] {texts.get(sid, '')}" for sid in r["raw_cited_source_ids"]),
                             "; ".join(flags), "", "", "", "", "", "", ""])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm-paid", action="store_true", required=True)
    parser.add_argument("--development-only", action="store_true")
    parser.add_argument("--label", help="Required for development reruns, e.g. phase22-dev")
    args = parser.parse_args()
    result = run(development_only=args.development_only, label=args.label)
    print(json.dumps(result["summary"], indent=2))
    print("Saved results under evals/phase21/results/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
