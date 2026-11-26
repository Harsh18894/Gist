"""Phase 2.3 development answer runs: benchmark-3 development split plus consumed benchmark v4.

Both sets are development data. v4's held-out run is already consumed, so it is now used
for development only. Each run answers every selected question once through the real paid
Ask path with the chosen context retriever (`GIST_PAID_RETRIEVER`), and records
deterministic checks: status, abstention, citation scope, hard negatives, and evidence groups
in context and cited. Results are immutable per label. A per-run spend stop applies.
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
from app.rag.budget import summary as spend_summary  # noqa: E402
from app.rag.provider import PaidApiDisabled, ProviderError  # noqa: E402
from app.rag.service import answer, paid_retriever  # noqa: E402
from app.schemas import AskRequest  # noqa: E402
import import_phase21_review as review  # noqa: E402
from run_benchmark3_answers import checks  # noqa: E402

RESULTS = ROOT / "evals/phase23/results"
RUN_STOP_USD = 0.03


def questions() -> list[dict]:
    """Benchmark-3 development questions plus all of consumed v4, tagged by source set."""
    selected = []
    b3 = review.verify(review.OUT)
    for q in json.loads((review.OUT / "benchmark.json").read_text())["questions"]:
        if q["id"] in set(b3["development_ids"]) and q["split"] == "development":
            selected.append({**q, "set": "benchmark3-dev"})
    _draft, v4_dir, _version = review.TARGETS["v4"]
    review.verify(v4_dir)
    if not (ROOT / "evals/phase22/results/benchmark4-final.json").exists():
        raise RuntimeError("v4 may be used for development only after its one-time final run.")
    selected += [{**q, "set": "benchmark4-consumed"} for q in json.loads((v4_dir / "benchmark.json").read_text())["questions"]]
    return selected


def _groups(question: dict, ids: list[str]) -> str | None:
    groups = question["evidence_groups"]
    return f"{sum(bool(set(g) & set(ids)) for g in groups)}/{len(groups)}" if groups else None


def _ratio(values: list[str | None]) -> float | None:
    pairs = [tuple(map(int, v.split("/"))) for v in values if v]
    return round(sum(a for a, _ in pairs) / sum(b for _, b in pairs), 4) if pairs else None


def summarize(rows: list[dict]) -> dict:
    def part(subset: list[dict]) -> dict:
        answerable = [r for r in subset if not r["expected_abstention"]]
        return {"questions": len(subset), "answerable": len(answerable),
                "full": sum(r["gist_status"] == "answered" for r in answerable),
                "partial": sum(r["gist_status"] == "partial" for r in answerable),
                "wrong_refusals": sum(r["gist_status"] == "insufficient_evidence" for r in answerable),
                "unanswerable_declined": f"{sum(r['abstained'] for r in subset if r['expected_abstention'])}/"
                                         f"{sum(r['expected_abstention'] for r in subset)}",
                "evidence_groups_in_context": _ratio([r["groups_in_context"] for r in answerable]),
                "evidence_groups_cited": _ratio([r["evidence_groups_cited"] for r in answerable]),
                "answers_citing_hard_negative": sum(bool(r["cited_hard_negatives"]) and not r["abstained"] for r in subset),
                "answers_citing_outside_context": sum(not r["cited_ids_all_retrieved"] for r in subset)}
    result = {"all": part(rows)}
    for key in ("set", "category"):
        for value in sorted({r[key] for r in rows}):
            result[f"{key}:{value}"] = part([r for r in rows if r[key] == value])
    return result


def run(label: str) -> dict:
    target = RESULTS / f"dev-answers-{label}.json"
    if target.exists():
        raise FileExistsError(f"{target} exists; development results are immutable per label.")
    if os.getenv("GIST_DATASET_VERSION") != "v2":
        raise RuntimeError("Set GIST_DATASET_VERSION=v2.")
    retriever = paid_retriever()
    selected = questions()
    start = spend_summary()["committed_or_reserved_usd"]
    rows, errors = [], []
    with connection() as db:
        for question in selected:
            if spend_summary()["committed_or_reserved_usd"] - start > RUN_STOP_USD:
                errors.append({"question_id": question["id"], "error": "per-run spend stop"})
                break
            captured: list[str] = []
            started = time.perf_counter()
            try:
                result = answer(db, AskRequest(question=question["question"], mode="openai"), audit_generated=captured.append)
            except (ProviderError, PaidApiDisabled) as exc:
                errors.append({"question_id": question["id"], "error": type(exc).__name__, "message": str(exc)})
                break
            response = result.model_dump()
            raw = captured[0] if captured else None
            context = [s["source_id"] for s in response["retrieved_sources"]]
            rows.append({"question_id": question["id"], "set": question["set"], "category": question["category"],
                         "question": question["question"], "expected_answer": question["expected_answer_or_abstention"],
                         "raw_model_answer": raw, "gist_answer": response["answer"], "context_source_ids": context,
                         "groups_in_context": _groups(question, context), "output_tokens": response["output_tokens"],
                         "latency_ms": round((time.perf_counter() - started) * 1000), **checks(question, response, raw)})
    output = {"label": label, "retriever": retriever, "data": "development only (benchmark-3 dev + consumed v4)",
              "estimated_cost_usd": round(spend_summary()["committed_or_reserved_usd"] - start, 8),
              "errors": errors, "summary": summarize(rows) if rows else None, "answers": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    with target.open("x") as handle:
        handle.write(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--confirm-paid", action="store_true", required=True)
    args = parser.parse_args()
    result = run(args.label)
    print(json.dumps({"retriever": result["retriever"], "cost": result["estimated_cost_usd"], "errors": result["errors"],
                      "summary": {k: v for k, v in (result["summary"] or {}).items() if not k.startswith("category:")}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
