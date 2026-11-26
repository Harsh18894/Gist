"""ONE-TIME Phase 2.3 final exam on gist-phase2.3-benchmark-5-reviewed (24 held-out questions).

Runs only after `lock_benchmark5.py verify` passes and refuses to run again once a
result exists. For each question it records the top-20 retrieval ranking with the
same context retriever the locked answer path uses, then one answer through the real
Ask Gist paid path (`service.answer`, mode "openai"). It writes a blind claim-review
sheet for the owner. Query embeddings are paid on a cache miss; generation is paid.
Both stay behind the approval flags and shared $0.50 ledger, with a per-run stop.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/scripts"))

from app.database import connection  # noqa: E402
from app.rag.budget import summary as spend_summary  # noqa: E402
from app.rag.provider import EMBED_MODEL, PaidApiDisabled, ProviderError, embed_query_cached  # noqa: E402
from app.rag.retrieval import Filters, hybrid_search  # noqa: E402
from app.rag.service import PAID_CONTEXT_SOURCES, answer, paid_retriever  # noqa: E402
from app.schemas import AskRequest  # noqa: E402
import evaluate_benchmark3_dev as evaluation  # noqa: E402
import import_phase21_review as review  # noqa: E402
from lock_benchmark5 import verify_lock  # noqa: E402
from run_benchmark3_answers import checks  # noqa: E402

DRAFT_PATH, BENCHMARK_DIR, VERSION = review.TARGETS["v5"]
RESULTS = ROOT / "evals/phase23/results"
RESULT = RESULTS / "benchmark5-final.json"
REVIEW_CSV = RESULTS / "benchmark5-final-answer-review.csv"
RUN_STOP_USD = 0.02


def final_questions() -> tuple[dict, list[dict]]:
    manifest = review.verify(BENCHMARK_DIR)
    benchmark = json.loads((BENCHMARK_DIR / "benchmark.json").read_text())
    questions = [q for q in benchmark["questions"] if q["id"] in set(manifest["heldout_ids"])]
    if len(questions) != 24 or any(q["split"] != "heldout" for q in questions):
        raise ValueError("Final-exam selection does not match the frozen v5 manifest.")
    return manifest, questions


def run() -> dict:
    lock = verify_lock()
    if RESULT.exists():
        raise FileExistsError("The v5 final exam already ran once; it must not be rerun.")
    if os.getenv("GIST_DATASET_VERSION") != "v2":
        raise RuntimeError("Set GIST_DATASET_VERSION=v2.")
    if os.getenv("GIST_LLM_MODEL", lock["answer_config"]["llm_model"]) != lock["answer_config"]["llm_model"]:
        raise RuntimeError("GIST_LLM_MODEL differs from the locked answer model.")
    if paid_retriever() != lock["answer_config"]["paid_retriever"]:
        raise RuntimeError("GIST_PAID_RETRIEVER differs from the locked retriever.")
    manifest, questions = final_questions()
    start = spend_summary()["committed_or_reserved_usd"]
    retrieval, answers, errors = [], [], []
    with connection() as db:
        if dict(db.execute("SELECT key,value FROM dataset_meta")).get("source_sha256") != manifest["source_sha256"]:
            raise ValueError("The v2 index does not match the benchmark's frozen corpus.")
        kinds = dict(db.execute("SELECT id,kind FROM sources"))
        texts = dict(db.execute("SELECT id,content FROM sources"))
        for question in questions:
            if spend_summary()["committed_or_reserved_usd"] - start > RUN_STOP_USD:
                errors.append({"question_id": question["id"], "error": "per-run spend stop"})
                break
            try:
                vector, usage = embed_query_cached(db, question["question"])
                started = time.perf_counter()
                ids = [h.source_id for h in hybrid_search(db, question["question"], Filters(), model=EMBED_MODEL,
                                                          query_vector=vector, limit=20)]
                latency = round((time.perf_counter() - started) * 1000, 3)
                retrieval.append({"question_id": question["id"], "category": question["category"], "latency_ms": latency,
                                  "context_ids": ids[:PAID_CONTEXT_SOURCES],
                                  "relevant_in_context": sorted(set(ids[:PAID_CONTEXT_SOURCES]) & set(question["relevant_source_ids"])),
                                  "query_embedding_cache_hit": usage.get("cache_hit", False),
                                  **evaluation.score(question, ids, kinds)})
                captured: list[str] = []
                started = time.perf_counter()
                result = answer(db, AskRequest(question=question["question"], mode="openai"), audit_generated=captured.append)
            except (ProviderError, PaidApiDisabled) as exc:
                errors.append({"question_id": question["id"], "error": type(exc).__name__, "message": str(exc)})
                break
            response = result.model_dump()
            raw = captured[0] if captured else None
            answers.append({"question_id": question["id"], "category": question["category"], "question": question["question"],
                            "expected_answer": question["expected_answer_or_abstention"], "raw_model_answer": raw,
                            "gist_answer": response["answer"], "citations": [c["source_id"] for c in response["citations"]],
                            "retrieved_source_ids": [s["source_id"] for s in response["retrieved_sources"]],
                            "input_tokens": response["input_tokens"], "output_tokens": response["output_tokens"],
                            "latency_ms": round((time.perf_counter() - started) * 1000), **checks(question, response, raw)})
    answerable = [a for a in answers if not a["expected_abstention"]]
    unanswerable = [a for a in answers if a["expected_abstention"]]
    summary = {"questions_answered": len(answers), "stopped_early": bool(errors),
               "unanswerable_declined": f"{sum(a['abstained'] for a in unanswerable)}/{len(unanswerable)}",
               "answerable_full": sum(a["gist_status"] == "answered" for a in answerable),
               "answerable_partial": sum(a["gist_status"] == "partial" for a in answerable),
               "answerable_wrongly_refused": f"{sum(a['gist_status'] == 'insufficient_evidence' for a in answerable)}/{len(answerable)}",
               "answers_citing_hard_negative": sum(bool(a["cited_hard_negatives"]) for a in answers),
               "answers_citing_outside_context": sum(not a["cited_ids_all_retrieved"] for a in answers),
               "estimated_cost_usd": round(spend_summary()["committed_or_reserved_usd"] - start, 8)}
    output = {"benchmark_version": VERSION, "run": "one-time final", "lock_sha256": lock["lock_sha256"],
              "questions_sha256": manifest["questions_sha256"],
              "label_provenance": "Owner-written labels (single reviewer).", "paid_retriever": paid_retriever(),
              "retrieval": evaluation.aggregate(retrieval) if retrieval else None, "answers_summary": summary,
              "errors": errors, "per_question_retrieval": retrieval, "per_question_answers": answers,
              "limitations": ("24 held-out questions (20 answerable): directional evidence. Owner-written, non-exhaustive "
                              "labels. Answer quality requires the owner's claim review of the CSV sheet.")}
    RESULTS.mkdir(parents=True, exist_ok=True)
    with RESULT.open("x") as handle:  # exclusive create: a second run cannot overwrite
        handle.write(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    with REVIEW_CSV.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["question_id", "split", "category", "question", "expected_answer", "generated_answer", "gist_status",
                         "cited_source_ids", "cited_source_texts", "auto_flags", "claims_supported (all/some/none/n_a)",
                         "unsupported_claims", "correct_abstention (yes/no)", "overall (good/acceptable/poor)",
                         "reviewer_comments", "reviewer_name", "review_date (YYYY-MM-DD)"])
        for a in answers:
            flags = [name for name, bad in (("cites_hard_negative", a["cited_hard_negatives"]),
                                            ("cites_outside_context", not a["cited_ids_all_retrieved"]),
                                            ("wrong_abstention", not a["abstention_correct"])) if bad]
            writer.writerow([a["question_id"], "heldout", a["category"], a["question"], a["expected_answer"],
                             a["raw_model_answer"] or a["gist_answer"], a["gist_status"], "; ".join(a["raw_cited_source_ids"]),
                             "\n\n".join(f"[{sid}] {texts.get(sid, '')}" for sid in a["raw_cited_source_ids"]),
                             "; ".join(flags), "", "", "", "", "", "", ""])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--final", action="store_true", required=True, help="Confirms the single approved final run")
    parser.add_argument("--confirm-paid", action="store_true", required=True)
    parser.parse_args()
    result = run()
    print(json.dumps({"retrieval": {k: v for k, v in (result["retrieval"] or {}).items() if k != "by_category"},
                      "answers": result["answers_summary"], "errors": result["errors"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
