"""Phase 4.4 held-out investigation benchmark: freeze (lock), verify, and run exactly once.

  lock            write evals/phase44/lock.json (refuses if it exists)
  run [--paid]    verify the lock; without --paid a dry run with a cost estimate; with --paid run once
                  (exclusive create of the results file; needs the paid flags and a spend cap)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GIST_DATASET_VERSION", "v2")
from app.investigate import executor, model, tools  # noqa: E402
from app.rag import provider  # noqa: E402
from app.rag.budget import summary as spend  # noqa: E402
from scripts.run_investigation_dev import estimate, score  # noqa: E402

DIR = ROOT / "evals/phase44"
QUESTIONS, LOCK, RESULT = DIR / "heldout-questions.json", DIR / "lock.json", DIR / "results" / "heldout-run.json"
ANSWER_KEY = ROOT / "evals/phase4/events-answer-key.json"
CODE = ["backend/app/investigate/model.py", "backend/app/investigate/plan.py", "backend/app/investigate/executor.py",
        "backend/app/investigate/tools.py", "backend/app/investigate/audit.py", "backend/app/rag/provider.py",
        "backend/scripts/run_investigation_dev.py", "backend/scripts/heldout_investigations.py"]
RUN_STOP_USD = 0.08


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events_hash() -> str:
    with sqlite3.connect(f"file:{tools.events_db_path()}?mode=ro", uri=True) as db:
        return db.execute("SELECT value FROM meta WHERE key = 'content_sha256'").fetchone()[0]


def fingerprint() -> dict:
    return {"questions_sha256": _sha(QUESTIONS), "answer_key_sha256": _sha(ANSWER_KEY), "events_content_sha256": _events_hash(),
            "prompt_version": model.PROMPT_VERSION, "code_sha256": {p: _sha(ROOT / p) for p in CODE}}


def verify() -> dict:
    if not LOCK.exists():
        raise SystemExit("No lock: run `lock` first.")
    lock = json.loads(LOCK.read_text())
    now = fingerprint()
    diff = [k for k in now if now[k] != lock["fingerprint"][k]]
    if diff:
        raise SystemExit(f"Lock mismatch in {diff}; the frozen benchmark or its code changed. Not running.")
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lock")
    run = sub.add_parser("run")
    run.add_argument("--paid", action="store_true")
    args = parser.parse_args()
    if args.cmd == "lock":
        with LOCK.open("x") as handle:   # exclusive create: a lock is written once
            json.dump({"locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fingerprint": fingerprint(),
                       "criteria": {"planted_found_min": 4, "planted_total": 6, "decoy_no_high_product_change": 4,
                                    "decoy_top_type_min": 3, "reports_passed_min": 8, "cost_max_usd": 0.08}}, handle, indent=2)
        print(f"Locked {LOCK.relative_to(ROOT)}")
        return 0
    lock = verify()
    questions = json.loads(QUESTIONS.read_text())["questions"]
    print(json.dumps({"prompt_version": model.PROMPT_VERSION, **estimate(questions)}, indent=2))
    if not args.paid:
        print("Lock verified. Dry run: no API calls made.")
        return 0
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    handle = RESULT.open("x")          # exclusive create: the held-out set runs exactly once
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
        expect = q["expect"] if q["expect"]["kind"] == "planted" else {**q["expect"], "kind": "decoy"}
        s = score(expect, entry)
        rows.append({"id": q["id"], "question": q["question"], "expect": q["expect"], "investigation_id": entry["id"],
                     "planner": entry["planner"], "status": entry["status"], "report_status": entry["report"]["status"],
                     "report_problems": entry["report"].get("problems"), "cost_usd": entry["cost_usd"], "score": s,
                     "report": entry["report"].get("report"), "report_raw_if_withheld": entry["report"].get("raw")})
        print(f"{q['id']}: planner={entry['planner']} report={entry['report']['status']} pass={s.get('pass')} {s.get('types', '')}")
    planted = [r for r in rows if r["expect"]["kind"] == "planted"]
    others = [r for r in rows if r["expect"]["kind"] != "planted"]
    totals = {"questions_run": len(rows), "reports_passed": sum(r["score"]["report_passed"] for r in rows),
              "planted_found": sum(r["score"]["pass"] for r in planted), "planted_total": len(planted),
              "decoy_no_high_product_change": sum(bool(r["score"].get("no_high_product_change")) for r in others),
              "decoy_top_type_ok": sum(bool(r["score"].get("top_type_ok")) for r in others), "decoy_total": len(others),
              "planner_fallbacks": sum(r["planner"] != "model" for r in rows),
              "run_cost_usd": round(spend()["committed_or_reserved_usd"] - start, 6), "ledger": spend()}
    c = lock["criteria"]
    totals["criteria"] = {"planted": totals["planted_found"] >= c["planted_found_min"],
                          "decoy_no_high": totals["decoy_no_high_product_change"] == c["decoy_no_high_product_change"],
                          "decoy_top_type": totals["decoy_top_type_ok"] >= c["decoy_top_type_min"],
                          "reports": totals["reports_passed"] >= c["reports_passed_min"],
                          "cost": totals["run_cost_usd"] <= c["cost_max_usd"], "no_uncertain": not totals["ledger"]["uncertain_requests"],
                          "all_questions_run": len(rows) == len(questions)}
    totals["pass"] = all(totals["criteria"].values())
    json.dump({"lock": lock, "totals": totals, "rows": rows}, handle, indent=2, ensure_ascii=False)
    handle.close()
    print(json.dumps({k: v for k, v in totals.items() if k != "ledger"}, indent=1))
    print(f"Saved {RESULT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
