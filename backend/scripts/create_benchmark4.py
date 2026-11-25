"""Create the Phase 2.2 final benchmark draft (v4): 24 held-out-only questions.

Questions were written source-first from the frozen Pulse v2 product documents and
customer statements, never from retrieval output. Evidence groups are defined by
document IDs and by exact customer phrases: every source whose text contains a
group phrase (inside optional date bounds) is listed, so labels are close to
exhaustive for that phrase. Other wordings of the same evidence may still exist.
The owner review decides final labels. This script never runs retrieval and
refuses to overwrite its outputs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.dataset import fingerprint, source_dir, source_files  # noqa: E402

DB = ROOT / "backend/gist-v2.sqlite3"
OUT_DIR = ROOT / "evals/phase22"
DRAFT = OUT_DIR / "benchmark-v4-draft.json"
QUESTIONS_CSV = OUT_DIR / "Gist_Benchmark4_Questions_for_Human_Review.csv"
SOURCES_CSV = OUT_DIR / "Gist_Benchmark4_Sources_for_Human_Review.csv"
VERSION = "gist-phase2.2-benchmark-4-draft"
SIMILARITY_LIMIT = 0.72
MAX_NEGATIVES = 3  # keeps review effort bounded; evidence groups stay complete for their phrases

# Group items: "doc:<id>" or ("phrase", from_date, to_date) with inclusive ISO bounds or None.
Q = []


def q(category, question, groups, negatives, answer, note=""):
    Q.append({"category": category, "question": question, "groups": groups, "negatives": negatives,
              "answer": answer, "note": note})


# --- direct: one product-document fact
q("direct", "Can a team keep shared boards out of the project digest?",
  [["doc:release-03"]], [("Please give us a quiet setting for the projects", None, None)],
  "Yes. Since the April 5 digest update, shared boards are selected by default and teams can opt out (release-03).")
q("direct", "Did the March portfolio filter release change how fast portfolio views load?",
  [["doc:release-02"]], ["doc:release-07"],
  "No. Release-02 states it did not change loading performance; the August release-07 is the loading change.")
q("direct", "Who can tune routine project alerts after the September release?",
  [["doc:release-08"]], ["doc:release-03"],
  "Admins can tune routine project alerts (release-08).")
q("direct", "Does the invoice seat-adjustment line identify which people were billed?",
  [["doc:prd-04"], [("seat adjustment line helps", None, None)]], ["doc:release-04"],
  "No. The PRD says the May line item does not identify people by itself, and a customer says they cannot trace the line to actual people.")

# --- semantic: paraphrased customer statements
q("semantic", "Find someone who was told to wipe their browser data but saw the problem on several computers.",
  [[("We were told to clear cache", None, None)]], [("It only feels slow when I switch to the full-year view", None, None)],
  "Customers report being told to clear cache although the slow portfolio happens on three machines.")
q("semantic", "Is there a newcomer who completed the joining form twice and still could not get in?",
  [[("finished the form twice", None, None)]], [("changed my password, and the old one", None, None)],
  "Yes. Several reports say a new hire finished the form twice and still is not in the workspace.")
q("semantic", "Did anyone ask for a way to reverse a file import they ran the previous day?",
  [[("need a way to undo yesterday", None, None)]], [("It recovered overnight", None, None)],
  "Yes. Customers asked for a way to undo yesterday's spreadsheet import.")
q("semantic", "Find a report of someone outside the company's email domain being unable to use the corporate login.",
  [[("A contractor on a different domain", None, None)]], [("domain isn't allowed", None, None)],
  "Customers report that a contractor on a different domain cannot use the company login.",
  "Domain-allowlist reports are close but describe the company's own domain being rejected.")

# --- multi-source: several distinct evidence needs
q("multi_source", "What different identity-provider problems, besides a wrong callback URL, did customers report?",
  [[("changed the SAML certificate", None, None)], [("domain isn't allowed", None, None)],
   [("one region is being sent to the wrong workspace", None, None)]],
  [("changed my password, and the old one", None, None)],
  "Three distinct SSO problems: login stopping after a SAML certificate change, the IdP assertion rejected because the domain is not allowed, and one region routed to the wrong workspace. Password-reset reports are a different problem.")
q("multi_source", "In what different ways did one-time spreadsheet imports put data in the wrong place?",
  [[("owner names landed in the due-date", None, None)], [("treated as a name", None, None)],
   [("Date cells from the sheet became blank", None, None)], [("semicolons", None, None)]],
  ["doc:release-05"],
  "Owner names landed in the due-date column; an Account ID mapped to a custom field was treated as a name; date cells became blank; and a semicolon-separated CSV was read as one column. These are import mapping problems, not live CRM sync.")
q("multi_source", "What did customers ask to control about project emails, and what controls did Pulse ship?",
  [[("Can we choose which boards contribute", None, None), ("quiet setting for the projects", None, None)],
   ["doc:release-03"], ["doc:release-08"]],
  [("high-priority one came hours late", None, None)],
  "Customers asked to choose which boards feed the digest and for a quiet setting for observed projects. Pulse shipped an opt-out for shared boards in the April digest (release-03) and admin tuning of routine project alerts in September (release-08). Whether these met every request is not established.")
q("multi_source", "Why did finance see a whole-cycle seat charge for someone removed late in the month, and what would help them trace it?",
  [["doc:release-04"], [("moved a contractor out on the 27th", None, None)],
   ["doc:prd-04", ("download a list of seats counted", None, None)]],
  [("Our renewal estimate doesn't match", None, None)],
  "Release-04 says seats archived mid-cycle remain counted until the cycle closes, matching a customer billed for a contractor moved out on the 27th. Invoice-time seat evidence (PRD-04), such as a downloadable list of seats counted, would help trace it.")

# --- temporal: chronology without causal claims
q("temporal", "When did the shared template gallery ship, and did customers still struggle to find templates afterwards?",
  [["doc:release-06"], [("I only found the template menu", "2025-07-05", None),
                         ("useful once you know where it lives", "2025-07-05", None)]],
  [("duplicate button is greyed out", None, None)],
  "The gallery shipped on 2025-07-05 in the workspace menu (release-06). Later reports say it was found only after support sent a screenshot, or is useful once you know where it lives. Timing does not show the release caused the difficulty.")
q("temporal", "Were archived-seat billing complaints reported before the May invoice breakdown?",
  [["doc:release-04"], [("We archived two collaborators", None, "2025-05-04"),
                         ("download a list of seats counted", None, "2025-05-04")]],
  [("breakdown is easier to read", None, None)],
  "Yes. Reports from January to March 2025 already described archived collaborators still counted and asked for an invoice-time seat list, before the May 5 breakdown (release-04).")
q("temporal", "What did customers say about the portfolio filter controls after the March filter release?",
  [["doc:release-02"], [("Nice new filter options", "2025-03-05", None), ("the little funnel", "2025-03-05", None),
                         ("controls are buried above the chart", "2025-03-05", None)]],
  [("We were told to clear cache", None, None)],
  "After the March 5 release (release-02), customers liked the new options but found the active state hard to notice, missed the small funnel icon, and said the controls are buried above the chart.")
q("temporal", "Were urgent alerts reported as late before the September per-project controls, or only afterwards?",
  [["doc:release-08"], [("urgent at noon", "2025-09-05", None), ("even urgent ones are delayed", "2025-09-05", None),
                         ("high-priority one came hours late", "2025-09-05", None)]],
  [("38 project emails", None, None)],
  "The late-urgent-alert reports found are all dated after the September 5 release (release-08), which says later delay reports are under investigation. Timing alone does not show the controls caused the delays.",
  "Absence of earlier reports is checked only for these phrases.")

# --- contradictory: mixed or conflicting evidence
q("contradictory", "Do customers agree that the new template gallery is easy to find?",
  [[("gallery is easy to find now", None, None)], [("I only found the template menu", None, None),
                                                  ("useful once you know where it lives", None, None)]],
  [("Support said our workspace restricts template duplication", None, None)],
  "No. Some say the gallery is easy to find now; others found the menu only after support sent a screenshot or say it helps once you know where it lives.")
q("contradictory", "Did the CRM connector stay unreliable after the June refresh?",
  [[("reconnected twice after the connector change", None, None)],
   [("It recovered overnight", None, None), ("stable again this week", None, None)]],
  [("need a way to undo yesterday", None, None)],
  "Mixed. One customer reconnected twice and the queue still had not caught up; others say it recovered overnight after support helped or is stable again this week.")
q("contradictory", "Did customers see the invoice breakdown as a clear improvement?",
  [[("breakdown is easier to read", None, None)], [("seat adjustment line helps", None, None)]],
  [("We archived two collaborators", None, None)],
  "Partly. Customers say the breakdown is easier to read, yet the mid-cycle change is still opaque and the adjustment line cannot be traced to actual people.")
q("contradictory", "Did the owner checklist settle onboarding for invited team members?",
  [["doc:release-01"], [("checklist is clearer now", None, None), ("finished the form twice", "2025-02-05", None)]],
  [("changed my password, and the old one", None, None)],
  "Not fully. Release-01 says invited users should not need to verify the owner again but later reports describe a repeat step. Customers say the checklist is clearer while the invited-user handoff is still awkward, and new hires still could not get in.")

# --- unanswerable: topical sources lack the requested fact
q("unanswerable", "What percentage of enterprise customers use single sign-on?",
  [], [("changed the SAML certificate", None, None)],
  "Abstain. No source gives an SSO adoption rate; individual SSO reports are not a percentage.")
q("unanswerable", "How many engineering hours did the August portfolio loading change take?",
  [], ["doc:release-07"],
  "Abstain. The release describes the change but no source states engineering effort.")
q("unanswerable", "Which customer cancelled their subscription because of the digest change?",
  [], [("engineering muted everything", None, None)],
  "Abstain. Reports describe frustration and muting, but no source records a cancellation.")
q("unanswerable", "On what date is the next Pulse release scheduled?",
  [], ["doc:release-08"],
  "Abstain. The documents describe past releases only; no future release date is stated.")


def _matches(db, item) -> list[str]:
    if isinstance(item, str):
        source_id = item.removeprefix("doc:")
        if not db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
            raise ValueError(f"Unknown document {source_id}")
        return [source_id]
    phrase, start, end = item
    rows = db.execute("SELECT id, source_date FROM sources WHERE instr(content, ?) > 0 ORDER BY id", (phrase,)).fetchall()
    ids = [sid for sid, day in rows if (not start or (day or "") >= start) and (not end or (day or "") <= end)]
    if not ids:
        raise ValueError(f"Phrase matched nothing: {phrase!r}")
    return ids


def _describe(item) -> str:
    if isinstance(item, str):
        return f"document {item.removeprefix('doc:')}"
    phrase, start, end = item
    bounds = f" dated {start or '…'}–{end or '…'}" if start or end else ""
    return f"exact phrase '{phrase}'{bounds}"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower())


def build() -> tuple[dict, list[dict], list[dict]]:
    if len(Q) != 24 or any(sum(x["category"] == c for x in Q) != 4 for c in
                           ("direct", "semantic", "multi_source", "temporal", "contradictory", "unanswerable")):
        raise ValueError("Need exactly four questions in each of six categories.")
    corpus_sha = fingerprint(source_files(source_dir("v2", ROOT)))
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        meta = dict(db.execute("SELECT key,value FROM dataset_meta"))
        if meta.get("version") != "v2" or meta.get("source_sha256") != corpus_sha:
            raise ValueError("The v2 index does not match the frozen source corpus.")
        sources = {row[0]: row[1:] for row in db.execute("SELECT id,kind,title,source_date,segment,product_area,path,content FROM sources")}
        questions, q_rows, s_rows = [], [], []
        for number, item in enumerate(Q, 1):
            qid = f"B4-Q-{number:03d}"
            groups, why = [], {}
            for index, group in enumerate(item["groups"], 1):
                members = []
                for entry in group:
                    for sid in _matches(db, entry):
                        if sid not in members:
                            members.append(sid)
                        why.setdefault(sid, (set(), _describe(entry)))[0].add(index)
                groups.append(members)
            negatives = []
            for entry in item["negatives"]:
                for sid in _matches(db, entry):
                    if sid not in negatives and not any(sid in g for g in groups) and len(negatives) < MAX_NEGATIVES:
                        negatives.append(sid)
                        why.setdefault(sid, (set(), _describe(entry)))
            relevant = sorted({sid for g in groups for sid in g})
            questions.append({"id": qid, "split": "heldout", "category": item["category"], "question": item["question"],
                              "evidence_groups": groups, "relevant_source_ids": relevant,
                              "hard_negative_source_ids": negatives,
                              "expected_answer_or_abstention": item["answer"],
                              "judgment_completeness": "phrase_defined_groups_pending_owner_review",
                              "review_status": "human_review_required"})
            group_text = " | ".join(f"Group {i}: {', '.join(g)}" for i, g in enumerate(groups, 1))
            listed = [*relevant, *negatives]
            q_rows.append({"question_id": qid, "split": "heldout", "category": item["category"], "question": item["question"],
                           "proposed_answer_original": item["answer"], "proposed_answer_ai_reviewed": item["answer"],
                           "original_evidence_groups": group_text, "ai_reviewed_evidence_groups": group_text,
                           "original_supporting_source_ids": "; ".join(relevant), "ai_reviewed_supporting_source_ids": "; ".join(relevant),
                           "original_hard_negative_source_ids": "; ".join(negatives),
                           "ai_reviewed_hard_negative_source_ids": "; ".join(negatives),
                           "partial_or_mixed_source_ids": "", "ambiguous_negative_candidates": "", "new_alternative_source_ids": "",
                           "all_source_ids_in_source_review_csv": "; ".join(listed),
                           "ai_review_findings": item["note"] or "Groups list every source containing the stated phrase.",
                           **{column: "" for column in QUESTION_HUMAN_COLUMNS}})
            for sid in listed:
                kind, title, day, segment, area, path, content = sources[sid]
                numbers, how = why[sid]
                is_negative = sid in negatives
                s_rows.append({"question_id": qid, "split": "heldout", "category": item["category"], "question": item["question"],
                               "proposed_answer_original": item["answer"], "proposed_answer_ai_reviewed": item["answer"],
                               "source_id": sid,
                               "suggested_source_role": "Proposed hard negative (should NOT support claim)" if is_negative else "Proposed supporting evidence",
                               "ai_source_classification": "verified_hard_negative_for_specific_question" if is_negative else "supports_specified_evidence_group",
                               "how_found": how,
                               "original_evidence_group_numbers": "; ".join(map(str, sorted(numbers))),
                               "ai_reviewed_evidence_group_numbers": "; ".join(map(str, sorted(numbers))),
                               "was_original_supporting_source": "no" if is_negative else "yes",
                               "was_ai_reviewed_supporting_source": "no" if is_negative else "yes",
                               "was_original_hard_negative": "yes" if is_negative else "no",
                               "was_ai_reviewed_hard_negative": "yes" if is_negative else "no",
                               "source_type": kind, "source_title": title, "source_date": day or "", "customer_segment": segment or "",
                               "product_area": area or "", "full_source_text": content, "source_file_path": path,
                               "ai_review_notes": item["note"],
                               **{column: "" for column in SOURCE_HUMAN_COLUMNS}})
    previous = [x["question"] for x in json.loads((ROOT / "evals/v2/questions.json").read_text())["questions"]]
    previous += [x["question"] for x in json.loads((ROOT / "evals/phase21/reviewed-v3/benchmark.json").read_text())["questions"]]
    similarity = max((SequenceMatcher(None, _norm(a["question"]), _norm(b)).ratio(), a["id"], b)
                     for a in questions for b in previous)
    if similarity[0] >= SIMILARITY_LIMIT:
        raise ValueError(f"Question too similar to an earlier benchmark: {similarity}")
    canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    draft = {"benchmark_version": VERSION, "dataset_version": "v2", "synthetic": True, "source_sha256": corpus_sha,
             "questions_sha256": hashlib.sha256(canonical(questions)).hexdigest(),
             "heldout_sha256": hashlib.sha256(canonical(questions)).hexdigest(),
             "split_counts": {"development": 0, "heldout": 24},
             "max_similarity_to_earlier_questions": {"ratio": round(similarity[0], 3), "pair": [similarity[1], similarity[2]]},
             "human_review_status": "pending; owner review required before freezing",
             "label_policy": ("Groups are distinct evidence needs; members are every source containing a group phrase "
                              "(within stated dates) or the named document. Other wordings may exist."),
             "questions": questions}
    return draft, q_rows, s_rows


QUESTION_HUMAN_COLUMNS = ["question_reviewer_decision (approve/revise/unclear)", "your_corrected_answer", "your_missing_source_ids",
                          "your_question_comments", "all_evidence_groups_covered (yes/no/unclear)",
                          "judgments_are (exhaustive/reviewed_subset)", "reviewer_name", "review_date", "second_reviewer_comments",
                          "human_sign_off (yes/no)"]
SOURCE_HUMAN_COLUMNS = ["your_source_verdict (supports/partial/unsupported/unclear/hard_negative)", "your_source_comments",
                        "your_corrected_evidence_group", "human_reviewer", "review_date", "second_reviewer_resolution"]


def main() -> int:
    for path in (DRAFT, QUESTIONS_CSV, SOURCES_CSV):
        if path.exists():
            raise FileExistsError(f"{path} exists; drafts are not overwritten.")
    draft, q_rows, s_rows = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DRAFT.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n")
    for path, rows in ((QUESTIONS_CSV, q_rows), (SOURCES_CSV, s_rows)):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"version": VERSION, "questions": len(q_rows), "source_rows": len(s_rows),
                      "distinct_sources": len({r["source_id"] for r in s_rows}),
                      "max_similarity": draft["max_similarity_to_earlier_questions"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
