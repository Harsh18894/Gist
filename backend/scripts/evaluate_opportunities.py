"""Evaluate Phase 3.3 ticket and document linking on Pulse v2. $0, no API calls.

Ground truth, used for scoring only:
- ticket issues come from the private v2 annotations;
- an opportunity's issue is the majority annotated issue of its primary feedback members;
- document relevance comes from evals/phase33/document-issue-key.json (agent-authored, owner review pending).

Tickets and opportunities are split by a fixed hash of their IDs. Thresholds are chosen on
the development half by rules fixed below, then the test half is scored once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import issues  # noqa: E402
from app.opportunities import LinkConfig, build  # noqa: E402

DB = ROOT / "backend/gist-v2.sqlite3"
ANNOTATIONS = ROOT / "evals/v2/source_annotations.jsonl"
DOC_KEY = ROOT / "evals/phase33/document-issue-key.json"
RESULTS = ROOT / "evals/phase33/results"
TICKET_GRID = [round(0.05 * i, 2) for i in range(8, 17)]
DOC_GRID = [round(0.05 * i, 2) for i in range(6, 15)]
TARGETS = {"ticket_precision": 0.80, "document_top1_precision": 0.75, "no_document_abstention": 0.5}


def half(identifier: str) -> str:
    return "development" if int(hashlib.sha256(identifier.encode()).hexdigest(), 16) % 2 == 0 else "test"


def truth() -> tuple[dict, dict, set]:
    rows = [json.loads(line) for line in ANNOTATIONS.read_text().splitlines() if line.strip()]
    labels = {r["source_id"]: r["issue_ids"] for r in rows}
    key = json.loads(DOC_KEY.read_text())
    return labels, key["documents"], set(key["issues_without_documents"])


def score(result: dict, labels: dict, doc_key: dict, no_doc: set, split: str) -> dict:
    opp_issue = {}
    for card in result["opportunities"]:
        votes = Counter(x for fid in card["evidence"]["feedback_ids"][:card["evidence"]["feedback_records"]] for x in labels.get(fid, []))
        opp_issue[card["id"]] = votes.most_common(1)[0][0] if votes else None
    links = [(t["id"], card["id"]) for card in result["opportunities"] for t in card["evidence"]["linked_tickets"] if half(t["id"]) == split]
    correct = [opp_issue[o] in labels.get(t, []) for t, o in links]
    split_tickets = [t for t in labels if t.startswith("V2-SUP") and half(t) == split]
    linked_by_ticket: dict[str, set] = {}
    for t, o in links:
        linked_by_ticket.setdefault(t, set()).add(opp_issue[o])
    answerable = [t for t in split_tickets if labels[t]]
    recall = [bool(linked_by_ticket.get(t, set()) & set(labels[t])) for t in answerable]
    ambiguous_linked = sum(1 for t in split_tickets if not labels[t] and t in linked_by_ticket)
    cards = [c for c in result["opportunities"] if half(c["sub_theme_id"]) == split and opp_issue[c["id"]]]
    with_doc = [c for c in cards if c["product_context"]]
    top1 = [opp_issue[c["id"]] in doc_key.get(c["product_context"][0]["id"], []) for c in with_doc]
    has_docs = [c for c in cards if opp_issue[c["id"]] not in no_doc]
    doc_recall = [any(opp_issue[c["id"]] in doc_key.get(d["id"], []) for d in c["product_context"]) for c in has_docs]
    no_doc_cards = [c for c in cards if opp_issue[c["id"]] in no_doc]
    abstain = [not c["product_context"] for c in no_doc_cards]
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    levels: dict[str, list[float]] = {}
    for c in cards:
        ids = c["evidence"]["feedback_ids"][:c["evidence"]["feedback_records"]]
        levels.setdefault(c["confidence"]["level"], []).append(sum(opp_issue[c["id"]] in labels.get(i, []) for i in ids) / len(ids))
    calibration = {lvl: {"opportunities": len(v), "mean_purity": mean(v)} for lvl, v in sorted(levels.items())}
    return {"split": split, "confidence_calibration": calibration, "ticket_links": len(links), "ticket_precision": mean(correct), "ticket_recall": mean(recall),
            "ambiguous_tickets_linked": ambiguous_linked, "opportunities": len(cards),
            "opportunities_with_document": len(with_doc), "document_top1_precision": mean(top1),
            "document_recall": mean(doc_recall), "no_document_opportunities": len(no_doc_cards),
            "no_document_abstention": mean(abstain)}


def run() -> dict:
    labels, doc_key, no_doc = truth()
    issues._cache.clear()
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        sweep = []
        for ticket_t, doc_t in product(TICKET_GRID, DOC_GRID):
            config = LinkConfig(ticket_threshold=ticket_t, document_threshold=doc_t)
            sweep.append({"config": config.__dict__, "development": score(build(db, config), labels, doc_key, no_doc, "development")})
        # Fixed selection rules (development only):
        # tickets: highest recall among thresholds with precision >= 0.85, else the most precise;
        # documents: highest mean of top-1 precision, recall and no-document abstention.
        tickets = [r for r in sweep if (r["development"]["ticket_precision"] or 0) >= 0.85]
        ticket_t = (max(tickets, key=lambda r: (r["development"]["ticket_recall"] or 0, -r["config"]["ticket_threshold"])) if tickets
                    else max(sweep, key=lambda r: r["development"]["ticket_precision"] or 0))["config"]["ticket_threshold"]
        doc_score = lambda d: sum(x or 0 for x in (d["document_top1_precision"], d["document_recall"], d["no_document_abstention"])) / 3
        doc_t = max(sweep, key=lambda r: (doc_score(r["development"]), r["config"]["document_threshold"]))["config"]["document_threshold"]
        chosen = LinkConfig(ticket_threshold=ticket_t, document_threshold=doc_t)
        result = build(db, chosen)
        dev = score(result, labels, doc_key, no_doc, "development")
        test = score(result, labels, doc_key, no_doc, "test")
    met = {k: (test[k] is not None and test[k] >= v) for k, v in TARGETS.items()}
    cal = test["confidence_calibration"]
    purity = [cal[l]["mean_purity"] for l in ("high", "medium", "low") if l in cal]
    met["confidence_monotonic"] = all(a >= b for a, b in zip(purity, purity[1:]))
    met["high_confidence_purity_0_9"] = ("high" in cal and cal["high"]["mean_purity"] >= 0.9)
    return {"data": "Pulse v2; annotations and the document key used for scoring only", "targets": TARGETS,
            "selection_rules": "tickets: max dev recall with dev precision >= 0.85; documents: max dev mean(top-1 precision, recall, abstention)",
            "chosen": {"config": chosen.__dict__, "development": dev, "test": test, "test_targets_met": met},
            "opportunities": len(result["opportunities"]), "development_sweep": sweep}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    target = RESULTS / f"linking-{args.label}.json"
    if target.exists():
        raise FileExistsError(f"{target} exists; results are immutable per label.")
    result = run()
    RESULTS.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    c = result["chosen"]
    print("config:", c["config"])
    for split in ("development", "test"):
        print(split, json.dumps({k: v for k, v in c[split].items() if k != "split"}))
    print("test targets met:", c["test_targets_met"])
    print(f"Saved {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
