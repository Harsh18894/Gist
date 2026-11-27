"""Phase 4.3 development run: model-planned investigations with AI reports, scored against the answer key.

--dry-run (default): no API calls; prints request sizes and a cost estimate.
--run: needs the paid flags and a spend cap; stops when this run's ledger cost reaches RUN_STOP_USD.
Results are immutable per label (evals/phase43/results/dev-<label>.json).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GIST_DATASET_VERSION", "v2")
from app.investigate import executor, model  # noqa: E402
from app.investigate.plan import rule_plan  # noqa: E402
from app.rag import provider  # noqa: E402
from app.rag.budget import summary as spend  # noqa: E402

QUESTIONS = ROOT / "evals/phase43/dev-questions.json"
RESULTS = ROOT / "evals/phase43/results"
RUN_STOP_USD = 0.10
EST_OUTPUT_TOKENS = {"planner": 1_200, "report": 2_000}   # includes hidden reasoning


def score(expect: dict, entry: dict) -> dict:
    block = entry.get("report") or {}
    report = block.get("report")
    if not report:
        return {"report_passed": False, "pass": False, "why": block.get("status", "no report")}
    exps = report["possible_explanations"]
    text = lambda e: (e["text"] + " " + e.get("confidence_reason", "")).lower()
    out = {"report_passed": True, "planner": entry["planner"], "top_type": exps[0]["type"] if exps else None,
           "types": [(e["type"], e["confidence"]) for e in exps]}
    if expect["kind"] == "planted":
        hit = [e for e in exps if e["type"] == "product_change" and e["confidence"] in ("medium", "high")
               and (any(t in text(e) for t in expect["terms"]) or expect["release"] in text(e))]
        out["pass"] = bool(hit)
    else:
        out["no_high_product_change"] = not any(e["type"] == "product_change" and e["confidence"] == "high" for e in exps)
        named = all_text = json.dumps(report).lower()
        out["top_type_ok"] = bool(exps) and exps[0]["type"] in expect["top_types"] and \
            (not expect.get("terms") or any(t in named for t in expect["terms"]))
        out["pass"] = out["no_high_product_change"] and out["top_type_ok"]
    return out


def estimate(questions) -> dict:
    _, in_price, out_price = provider._llm_settings()
    planner_bytes = len(model.PLANNER_INSTRUCTIONS) + len(json.dumps(model.plan_payload(questions[0]["question"])))
    report_bytes = [len(model.REPORT_INSTRUCTIONS) + len(json.dumps(model.report_payload(executor.run(rule_plan(q["question"]), log=False))))
                    for q in questions]
    tokens_in = (planner_bytes * len(questions) + sum(report_bytes)) / 4
    cost = (tokens_in * in_price + len(questions) * sum(EST_OUTPUT_TOKENS.values()) * out_price) / 1e6
    worst = ((planner_bytes * len(questions) + sum(report_bytes)) * in_price + 2 * len(questions) * provider.INVESTIGATION_MAX_OUTPUT_TOKENS * out_price) / 1e6
    return {"calls": 2 * len(questions), "max_request_bytes": max([planner_bytes] + report_bytes), "byte_limit": provider.GENERATION_BYTE_LIMIT,
            "estimated_usd": round(cost, 4), "worst_case_usd": round(worst, 4)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    target = RESULTS / f"dev-{args.label}.json"
    if target.exists():
        raise FileExistsError(f"{target} exists; results are immutable per label.")
    questions = json.loads(QUESTIONS.read_text())["questions"]
    est = estimate(questions)
    print(json.dumps({"prompt_version": model.PROMPT_VERSION, **est}, indent=2))
    if est["max_request_bytes"] > provider.GENERATION_BYTE_LIMIT:
        print("A request would exceed the byte limit; nothing sent.")
        return 1
    if not args.run:
        print("Dry run: no API calls made.")
        return 0
    start = spend()["committed_or_reserved_usd"]
    rows = []
    for q in questions:
        if spend()["committed_or_reserved_usd"] - start >= RUN_STOP_USD:
            print("Run stop reached.")
            break
        try:
            entry = executor.investigate(q["question"], "model")
        except provider.PaidApiDisabled as exc:
            print(f"Stopped: {exc}")
            break
        s = score(q["expect"], entry)
        rows.append({"id": q["id"], "question": q["question"], "expect": q["expect"], "investigation_id": entry["id"],
                     "planner": entry["planner"], "status": entry["status"], "report_status": entry["report"]["status"],
                     "report_problems": entry["report"].get("problems"), "planner_problems": entry["report"].get("planner_problems"),
                     "cost_usd": entry["cost_usd"], "score": s, "report": entry["report"].get("report"),
                     "report_raw_if_withheld": entry["report"].get("raw")})
        print(f"{q['id']}: planner={entry['planner']} report={entry['report']['status']} pass={s.get('pass')} {s.get('types', '')}")
    planted = [r for r in rows if r["expect"]["kind"] == "planted"]
    decoys = [r for r in rows if r["expect"]["kind"] == "decoy"]
    totals = {"questions": len(rows), "reports_passed": sum(r["score"]["report_passed"] for r in rows),
              "planted_found": sum(r["score"]["pass"] for r in planted), "planted_total": len(planted),
              "decoy_no_high_product_change": sum(bool(r["score"].get("no_high_product_change")) for r in decoys),
              "decoy_top_type_ok": sum(bool(r["score"].get("top_type_ok")) for r in decoys), "decoy_total": len(decoys),
              "planner_fallbacks": sum(r["planner"] != "model" for r in rows),
              "run_cost_usd": round(spend()["committed_or_reserved_usd"] - start, 6), "ledger": spend()}
    totals["criteria"] = {"planted_ge_4_of_5": totals["planted_found"] >= 4, "decoy_no_high_3_of_3": totals["decoy_no_high_product_change"] == 3,
                          "decoy_top_type_ge_2_of_3": totals["decoy_top_type_ok"] >= 2, "reports_ge_7_of_8": totals["reports_passed"] >= 7,
                          "cost_le_0_10": totals["run_cost_usd"] <= 0.10, "no_uncertain": not totals["ledger"]["uncertain_requests"]}
    RESULTS.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"prompt_version": model.PROMPT_VERSION, "totals": totals, "rows": rows}, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in totals.items() if k != "ledger"}, indent=1))
    print(f"Saved {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
