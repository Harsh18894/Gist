"""Create a separate, provisional Phase 2.1 question set from source-first notes.

Questions and labels require independent human review before final evaluation.
This script refuses to overwrite the artifact and never runs retrieval.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from freeze_v2_split import ROOT, source_hash

OUT = ROOT / "evals/phase21/benchmark-v2-draft.json"
VERSION = "gist-phase2.1-benchmark-2-draft"

# Split was assigned before any Phase 2.1 retrieval on these questions.
# Group members are alternative source IDs; groups themselves represent distinct
# evidence needs. They are provisional source-text judgments, not human labels.
CASES = [
    ("development", "direct", "Where does an admin find the date and project controls for a portfolio chart?",
     [["release-02"]], "Above the chart.", []),
    ("development", "direct", "How does Pulse bill a seat archived partway through the month?",
     [["release-04"]], "It remains counted until the billing cycle closes.", []),
    ("development", "direct", "Which workspace roles can duplicate a shared starter?",
     [["release-06"]], "Editors and admins.", ["V2-FB-0011"]),
    ("heldout", "direct", "Which alert classes are intended to remain timely after per-project tuning?",
     [["release-08"]], "Critical and direct-mention alerts.", ["V2-FB-0018"]),

    ("development", "semantic", "Find a customer whose account recovery email became useless during a call.",
     [["V2-FB-0098"]], "A reset link expired during the call.", ["V2-FB-0002"]),
    ("development", "semantic", "Is there a report of a company-side identity redirect setting preventing entry?",
     [["V2-FB-0063"]], "The IT team entered the wrong callback URL.", ["V2-FB-0098"]),
    ("development", "semantic", "Find a case where an empty-looking chart was actually a view setting.",
     [["V2-FB-0009", "V2-FB-0045"]], "A prior filter was still applied.", ["V2-FB-0020"]),
    ("heldout", "semantic", "Which customer says a successful one-time upload misassigned columns?",
     [["V2-FB-0041", "V2-FB-0005"]], "The spreadsheet import mapped fields incorrectly.", ["V2-FB-0028"]),

    ("development", "multi_source", "What distinct checks should support make before calling every sign-in failure the same defect?",
     [["prd-01", "V2-FB-0049", "V2-FB-0145"], ["V2-FB-0098", "V2-FB-0038"], ["V2-FB-0003", "V2-FB-0051", "V2-FB-0063"]],
     "Check invite handoff, password recovery, and SSO configuration separately.", ["V2-FB-0027"]),
    ("development", "multi_source", "How can an analyst separate missing live CRM records from a bad file upload?",
     [["prd-03", "V2-FB-0028", "V2-FB-0112"], ["V2-FB-0005", "V2-FB-0041"]],
     "Inspect connector completeness separately from CSV field mapping.", ["V2-FB-0017"]),
    ("development", "multi_source", "Which evidence separates finding a team template from being allowed to copy it?",
     [["V2-FB-0011", "V2-FB-0047"], ["V2-FB-0048", "V2-FB-0060", "release-06"]],
     "Discovery and role permissions are distinct problems.", []),
    ("heldout", "multi_source", "How should an analyst distinguish a slow portfolio page from a hidden chart selection?",
     [["V2-FB-0020", "V2-FB-0032", "prd-02"], ["V2-FB-0009", "V2-FB-0045"]],
     "Slow aggregation and persistent filters require different evidence.", ["V2-FB-0033"]),

    ("development", "temporal", "What was reported about large workspaces before the August loading change, and what later improved?",
     [["V2-FB-0020", "V2-FB-0032"], ["release-07"], ["V2-FB-0044"]],
     "Earlier large-workspace slowness preceded the faster path; a later enterprise report welcomed it. Causation is not proven by timing alone.", []),
    ("development", "temporal", "After the April digest default changed, how did two workspaces describe the outcome?",
     [["release-03"], ["V2-FB-0030"], ["V2-FB-0102"]],
     "A one-board user liked it; another reported too many emails. Both reports are later than the release.", []),
    ("development", "temporal", "What did the June connector update promise, and what later gap did a customer describe?",
     [["release-05"], ["V2-FB-0064"]],
     "The reconnect and status flow changed; a customer later reported a gap and backfill. The report does not establish the release caused it.", []),
    ("heldout", "temporal", "How do September's alert-control intent and later delayed-urgent reports relate?",
     [["release-08"], ["V2-FB-0019", "V2-FB-0067"]],
     "Urgent alerts were intended to remain timely, while later reports describe delays; causation remains unresolved.", []),

    ("development", "contradictory", "Does a healthy connector indicator establish that every sales task arrived?",
     [["release-05", "prd-03"], ["V2-FB-0028"]],
     "No. The product notes limit what status proves, and a customer saw missing tasks despite a connected state.", []),
    ("development", "contradictory", "Did customers agree that the project digest made their inbox better?",
     [["V2-FB-0030"], ["V2-FB-0102"]],
     "No. One liked it in a one-board workspace; another reported overload.", []),
    ("development", "contradictory", "Was portfolio loading uniformly slow across workspace sizes before the August update?",
     [["V2-FB-0020", "V2-FB-0068"], ["V2-FB-0032"]],
     "No. Small workspaces could be quick while larger roll-ups were slow.", []),
    ("heldout", "contradictory", "Can a visible starter still be unavailable to a teammate?",
     [["V2-FB-0048"], ["release-06"]],
     "Yes. Visibility does not grant duplication permission; roles control copying.", ["V2-FB-0047"]),

    ("development", "unanswerable", "What exact revenue increase came from the portfolio speed update?",
     [], "Abstain: no revenue outcome is provided.", ["release-07", "V2-FB-0044"]),
    ("development", "unanswerable", "Name the engineer who approved the customer's SAML callback setting.",
     [], "Abstain: no responsible engineer is identified.", ["V2-FB-0063"]),
    ("development", "unanswerable", "What is the complete count of urgent alerts lost across all Pulse customers?",
     [], "Abstain: reports do not provide an exhaustive count.", ["V2-FB-0019", "V2-FB-0067"]),
    ("heldout", "unanswerable", "Who approved the April digest default for every workspace?",
     [], "Abstain: the release note does not name an approver.", ["release-03"]),
]


def build() -> dict:
    if len(CASES) != 24:
        raise ValueError("Expected 24 draft questions")
    with sqlite3.connect(f"file:{ROOT / 'backend/gist-v2.sqlite3'}?mode=ro", uri=True) as db:
        ids = {row[0] for row in db.execute("SELECT id FROM sources")}
        meta = dict(db.execute("SELECT key,value FROM dataset_meta"))
    if meta.get("version") != "v2" or meta.get("source_sha256") != source_hash():
        raise ValueError("The source-first review requires the frozen v2 corpus")
    questions = []
    for number, (split, category, question, groups, expected, negatives) in enumerate(CASES, 1):
        references = {source for group in groups for source in group} | set(negatives)
        if not references <= ids:
            raise ValueError(f"Unknown source IDs for draft question {number}: {references - ids}")
        questions.append({"id": f"P21-Q-{number:03d}", "split": split, "category": category,
                          "question": question, "evidence_groups": groups,
                          "relevant_source_ids": sorted({source for group in groups for source in group}),
                          "hard_negative_source_ids": negatives,
                          "expected_answer_or_abstention": expected,
                          "judgment_completeness": "provisional_non_exhaustive_source_review",
                          "review_status": "independent_human_review_required"})
    raw = json.dumps(questions, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    heldout = [row for row in questions if row["split"] == "heldout"]
    heldout_raw = json.dumps(heldout, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {"benchmark_version": VERSION, "dataset_version": "v2", "synthetic": True,
            "source_sha256": source_hash(), "questions_sha256": hashlib.sha256(raw).hexdigest(),
            "heldout_sha256": hashlib.sha256(heldout_raw).hexdigest(),
            "split_counts": {"development": 18, "heldout": 6},
            "human_review_status": "pending; do not use held-out for tuning or final evaluation",
            "label_policy": "Groups are distinct evidence needs; members are alternative supporting sources. Labels are agent-prepared, non-exhaustive and require independent human adjudication.",
            "questions": questions}


if __name__ == "__main__":
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite {OUT}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    result = build()
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(result["benchmark_version"], result["split_counts"], result["questions_sha256"])
