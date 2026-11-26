"""Draft Phase 3.5 experiment suggestions, one guarded paid call per opportunity.

--dry-run (default) makes no API call: it builds every input, checks size limits and
prints a cost estimate. --run needs GIST_ENABLE_PAID_API=true, GIST_PAID_EVAL_APPROVED=true,
an OPENAI_API_KEY and a GIST_MAX_API_SPEND_USD cap, and stops once this run's recorded
cost reaches RUN_STOP_USD. Drafts that already match their evidence are skipped, so an
interrupted run resumes without paying twice.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import experiments as ex  # noqa: E402
from app.database import connection  # noqa: E402
from app.opportunities import build  # noqa: E402
from app.priorities import dataset_key  # noqa: E402
from app.rag import provider  # noqa: E402
from app.rag.budget import summary as spend_summary  # noqa: E402

RUN_STOP_USD = 0.06
EST_OUTPUT_TOKENS = 700


def plan(db) -> list[tuple[dict, dict, str]]:
    key = dataset_key(db)
    store = ex.load(key.split(":", 1)[0])
    todo = []
    for card in build(db)["opportunities"]:
        data = ex.payload(db, card)
        digest = ex.input_hash(data)
        saved = store["drafts"].get(card["id"])
        if saved and saved.get("input_hash") == digest and saved.get("dataset_key") == key:
            continue
        todo.append((card, data, digest))
    return todo


def estimate(todo) -> dict:
    model, in_price, out_price = provider._llm_settings()
    bytes_in = [len(json.dumps(d, ensure_ascii=True).encode()) + len(ex.INSTRUCTIONS.encode()) for _, d, _ in todo]
    tokens_in = sum(b / 4 for b in bytes_in)   # ~4 bytes per token for English JSON
    cost = (tokens_in * in_price + len(todo) * EST_OUTPUT_TOKENS * out_price) / 1_000_000
    return {"model": model, "calls": len(todo), "max_request_bytes": max(bytes_in, default=0),
            "byte_limit": provider.GENERATION_BYTE_LIMIT, "estimated_usd": round(cost, 4),
            "worst_case_usd": round((sum(bytes_in) * in_price + len(todo) * provider.JUDGE_MAX_OUTPUT_TOKENS * out_price) / 1_000_000, 4)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="make paid calls (requires approval flags)")
    parser.add_argument("--ledger-start", type=float, help="ledger total before this approved run began (for resumed runs)")
    args = parser.parse_args()
    with connection() as db:
        key = dataset_key(db)
        version = key.split(":", 1)[0]
        todo = plan(db)
        est = estimate(todo)
        print(json.dumps({"dataset_key": key, "prompt_version": ex.PROMPT_VERSION, **est}, indent=2))
        if est["max_request_bytes"] > provider.GENERATION_BYTE_LIMIT:
            print("A request exceeds the byte limit; nothing sent.")
            return 1
        if not args.run:
            print("Dry run: no API calls made.")
            return 0
        path = ex.generated_path(version)
        store = ex.load(version)
        store.update({"dataset_key": key, "prompt_version": ex.PROMPT_VERSION, "instructions": ex.INSTRUCTIONS})
        start = args.ledger_start if args.ledger_start is not None else spend_summary()["committed_or_reserved_usd"]
        spent = 0.0
        for card, data, digest in todo:
            if spent >= RUN_STOP_USD:
                print(f"Run stop reached (${spent:.4f}); remaining drafts left for a later approved run.")
                break
            try:
                text, usage = provider.suggest(db, ex.INSTRUCTIONS, data)
                draft, problems = ex.check(text, data)
            except provider.ProviderError as exc:
                # A billed, complete-but-truncated response is recorded as a failed draft (not retried);
                # any other provider error may leave billing uncertain, so the run stops.
                if "incomplete" not in str(exc):
                    print(f"Stopped at {card['id']}: {exc}")
                    break
                text, usage = None, {"model": provider._llm_settings()[0], "input_tokens": None, "output_tokens": None,
                                     "estimated_cost_usd": None}
                draft, problems = None, ["model output incomplete (hit the output-token limit)"]
            except provider.PaidApiDisabled as exc:
                print(f"Stopped at {card['id']}: {exc}")
                break
            spent = spend_summary()["committed_or_reserved_usd"] - start
            store["drafts"][card["id"]] = {
                "dataset_key": key, "input_hash": digest, "prompt_version": ex.PROMPT_VERSION, "model": usage["model"],
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "draft": draft, "problems": problems, "raw": text if problems else None,
                "usage": {k: usage[k] for k in ("input_tokens", "output_tokens", "estimated_cost_usd")}}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n")   # saved after every call
            print(f"{card['id']}: {'ok' if not problems else 'FAILED ' + '; '.join(problems)} (run total ${spent:.5f})")
    passed = sum(1 for d in store["drafts"].values() if not d["problems"])
    print(json.dumps({"run_cost_usd": round(spent, 6), "drafts": len(store["drafts"]), "passed_checks": passed,
                      "ledger": spend_summary()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
