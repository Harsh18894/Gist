"""Benchmark v4 draft 2: structural fixes after the Codex AI pre-review of draft 1.

Draft 1 (`benchmark-v4-draft.json`) is kept unchanged. Changes, all made before any
human review, retrieval or answer run on these questions:
- Q-002/005/010/012/014/016/018/020 expected answers tightened (no extra claims).
- Q-010 reworded: blank dates and delimiter parsing are not "wrong place" errors.
- Q-011/015/020 split groups that mixed distinct evidence needs.
- Q-013/017: V2-FB-0012 also reports missing the workspace menu, so it supports
  discovery difficulty; it was wrongly selected as a hard negative in draft 1.
- Q-014 group 2 keeps only explicit archived-seat complaints.
- Q-018 adds release-05 as the date anchor for "after the June refresh".
The owner review pack shows the AI pre-review in read-only columns.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
import create_benchmark4 as base  # noqa: E402

VERSION = "gist-phase2.2-benchmark-4-draft-2"
DRAFT = base.OUT_DIR / "benchmark-v4-draft-2.json"
QUESTIONS_CSV = base.OUT_DIR / "Gist_Benchmark4_Draft2_Questions_for_Human_Review.csv"
SOURCES_CSV = base.OUT_DIR / "Gist_Benchmark4_Draft2_Sources_for_Human_Review.csv"
PREREVIEW = base.OUT_DIR / "ai-prereview"

B: list[dict] = []
q = lambda *args, **kw: base.q(*args, into=B, **kw)

q("direct", "Can a team keep shared boards out of the project digest?",
  [["doc:release-03"]], [("Please give us a quiet setting for the projects", None, None)],
  "Yes. Since the April 5 digest update, shared boards are selected by default and teams can opt out (release-03).")
q("direct", "Did the March portfolio filter release change how fast portfolio views load?",
  [["doc:release-02"]], ["doc:release-07"],
  "No. The March 5 portfolio-filter release (release-02) states it did not change loading performance.")
q("direct", "Who can tune routine project alerts after the September release?",
  [["doc:release-08"]], ["doc:release-03"],
  "Admins can tune routine project alerts (release-08).")
q("direct", "Does the invoice seat-adjustment line identify which people were billed?",
  [["doc:prd-04"], [("seat adjustment line helps", None, None)]], ["doc:release-04"],
  "No. The PRD says the May line item does not identify people by itself, and customers say they cannot trace the line to actual people.")
q("semantic", "Find someone who was told to wipe their browser data but saw the problem on several computers.",
  [[("We were told to clear cache", None, None)]], [("It only feels slow when I switch to the full-year view", None, None)],
  "Yes. Customers say they were told to clear the cache but the problem happens on three machines; the reports do not always name the symptom.")
q("semantic", "Is there a newcomer who completed the joining form twice and still could not get in?",
  [[("finished the form twice", None, None)]], [("changed my password, and the old one", None, None)],
  "Yes. Several reports say a new hire finished the form twice and still is not in the workspace.")
q("semantic", "Did anyone ask for a way to reverse a file import they ran the previous day?",
  [[("need a way to undo yesterday", None, None)]], [("It recovered overnight", None, None)],
  "Yes. Customers asked for a way to undo yesterday's spreadsheet import. This is a request; no source says an undo exists.")
q("semantic", "Find a report of someone outside the company's email domain being unable to use the corporate login.",
  [[("A contractor on a different domain", None, None)]], [("domain isn't allowed", None, None)],
  "Customers report that a contractor on a different domain cannot use the company login.",
  "Domain-allowlist reports are close but do not say the blocked person used an outside domain.")
q("multi_source", "What different identity-provider problems, besides a wrong callback URL, did customers report?",
  [[("changed the SAML certificate", None, None)], [("domain isn't allowed", None, None)],
   [("one region is being sent to the wrong workspace", None, None)]],
  [("changed my password, and the old one", None, None)],
  "Three distinct SSO problems: login stopping after a SAML certificate change, the IdP assertion rejected because the domain is not allowed, and one region routed to the wrong workspace. Password-reset reports are a different problem; timing does not establish that the certificate change caused an outage.")
q("multi_source", "What mapping or parsing problems did customers report after one-time spreadsheet imports?",
  [[("owner names landed in the due-date", None, None)], [("treated as a name", None, None)],
   [("Date cells from the sheet became blank", None, None)], [("semicolons", None, None)]],
  ["doc:release-05"],
  "Owner names landed in the due-date column; an Account ID mapped to a custom field was treated as a name; date cells became blank; and a semicolon-delimited CSV was read as one column. These are import problems, not live CRM sync.")
q("multi_source", "What did customers ask to control about project emails, and what controls did Pulse ship?",
  [[("quiet setting for the projects", None, None)], [("Can we choose which boards contribute", None, None)],
   ["doc:release-03"], ["doc:release-08"]],
  [("high-priority one came hours late", None, None)],
  "Customers asked for a quiet setting for projects they only observe and to choose which boards feed the morning email. Pulse shipped an opt-out for shared boards in the April digest (release-03) and admin tuning of routine project alerts in September (release-08). Whether these met every request is not established.")
q("multi_source", "Why did finance see a whole-cycle seat charge for someone removed late in the month, and what would help them trace it?",
  [["doc:release-04"], [("moved a contractor out on the 27th", None, None)],
   ["doc:prd-04", ("download a list of seats counted", None, None)]],
  [("Our renewal estimate doesn't match", None, None)],
  "Release-04 says seats archived mid-cycle remain counted until the cycle closes, matching a customer billed for a contractor moved out on the 27th. Invoice-time seat evidence would help trace it: PRD-04 calls for it and customers request a downloadable list of seats counted. No source says that list is available.")
q("temporal", "When did the shared template gallery ship, and did customers still struggle to find templates afterwards?",
  [["doc:release-06"], [("I only found the template menu", "2025-07-05", None),
                         ("useful once you know where it lives", "2025-07-05", None), "id:V2-FB-0012"]],
  [("duplicate button is greyed out", None, None)],
  "The gallery shipped on 2025-07-05 in the workspace menu (release-06). Later reports say customers found the menu only after support sent a screenshot or searched inside projects without checking the workspace menu. Timing does not show the release caused the difficulty.")
q("temporal", "Were archived-seat billing complaints reported before the May invoice breakdown?",
  [["doc:release-04"], [("We archived two collaborators", None, "2025-05-04")]],
  [("breakdown is easier to read", None, None)],
  "Yes. January to March 2025 reports say archived collaborators were still counted on invoices, before the May 5 invoice breakdown (release-04).")
q("temporal", "What did customers say about the portfolio filter controls after the March filter release?",
  [["doc:release-02"], [("Nice new filter options", "2025-03-05", None)], [("the little funnel", "2025-03-05", None)],
   [("controls are buried above the chart", "2025-03-05", None)]],
  [("We were told to clear cache", None, None)],
  "After the March 5 release (release-02), customers liked the new options but found the active state hard to notice, missed the small funnel icon, and said the controls are buried above the chart.")
q("temporal", "Were urgent alerts reported as late before the September per-project controls, or only afterwards?",
  [["doc:release-08"], [("urgent at noon", "2025-09-05", None), ("even urgent ones are delayed", "2025-09-05", None),
                         ("high-priority one came hours late", "2025-09-05", None)]],
  [("38 project emails", None, None)],
  "The reports that describe late urgent alerts are dated after the September 5 release (release-08), which says later delay reports are under investigation. These dates do not establish causation or rule out earlier reports worded differently.",
  "Absence of earlier reports is checked only for these phrases.")
q("contradictory", "Do customers agree that the new template gallery is easy to find?",
  [[("gallery is easy to find now", None, None)], [("I only found the template menu", None, None),
                                                  ("useful once you know where it lives", None, None), "id:V2-FB-0012"]],
  [("Support said our workspace restricts template duplication", None, None)],
  "No. Some say the gallery is easy to find now; others found the menu only after support sent a screenshot or searched inside projects without checking the workspace menu.")
q("contradictory", "Did the CRM connector stay unreliable after the June refresh?",
  [[("reconnected twice after the connector change", None, None)],
   [("It recovered overnight", None, None), ("stable again this week", None, None)], ["doc:release-05"]],
  [("need a way to undo yesterday", None, None)],
  "Mixed. After the June 5 refresh (release-05), one customer's queue was still behind after two reconnections, while others described overnight recovery or stability that week. These reports do not establish lasting reliability.")
q("contradictory", "Did customers see the invoice breakdown as a clear improvement?",
  [[("breakdown is easier to read", None, None)], [("seat adjustment line helps", None, None)]],
  [("We archived two collaborators", None, None)],
  "Partly. Customers say the breakdown is easier to read, yet the mid-cycle change is still opaque and the adjustment line cannot be traced to actual people.")
q("contradictory", "Did the owner checklist settle onboarding for invited team members?",
  [["doc:release-01"], [("checklist is clearer now", None, None)], [("finished the form twice", "2025-02-05", None)]],
  [("changed my password, and the old one", None, None)],
  "Not fully. Release-01 says invited users should not need to verify the owner again, but later reports describe a repeat step. Customers say the checklist is clearer while the invited-user handoff is still awkward, and new hires who finished the form twice still could not get in; those reports do not attribute it to the checklist.")
q("unanswerable", "What percentage of enterprise customers use single sign-on?",
  [], [("changed the SAML certificate", None, None)],
  "Abstain. No source gives an SSO adoption rate; individual SSO reports are not a percentage.")
q("unanswerable", "How many engineering hours did the August portfolio loading change take?",
  [], ["doc:release-07"], "Abstain. The release describes the change but no source states engineering effort.")
q("unanswerable", "Which customer cancelled their subscription because of the digest change?",
  [], [("engineering muted everything", None, None)],
  "Abstain. Reports describe frustration and muting, but no source records a cancellation.")
q("unanswerable", "On what date is the next Pulse release scheduled?",
  [], ["doc:release-08"], "Abstain. The documents describe past releases only; no future release date is stated.")


def load_prereview() -> dict:
    notes: dict = {}
    with (PREREVIEW / "Benchmark4_AI_questions.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            comment = " ".join(x for x in (row["ai_question_comments"], row["ai_corrected_answer"] and
                                           f"Suggested answer: {row['ai_corrected_answer']}") if x)
            notes[row["question_id"]] = {"decision": row["ai_question_decision"], "comment": comment}
    with (PREREVIEW / "Benchmark4_AI_sources.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            notes[(row["question_id"], row["source_id"])] = {"verdict": row["ai_source_verdict"],
                                                            "quote": row["supporting_quote"],
                                                            "comment": row["ai_source_comments"]}
    return notes


def main() -> int:
    for path in (DRAFT, QUESTIONS_CSV, SOURCES_CSV):
        if path.exists():
            raise FileExistsError(f"{path} exists; drafts are not overwritten.")
    draft, q_rows, s_rows = base.build(B, VERSION, ai=load_prereview())
    draft["derived_from"] = {"benchmark_version": base.VERSION,
                             "file": "evals/phase22/benchmark-v4-draft.json",
                             "ai_prereview": "evals/phase22/ai-prereview/ (Codex, draft-1 numbering)"}
    DRAFT.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n")
    for path, rows in ((QUESTIONS_CSV, q_rows), (SOURCES_CSV, s_rows)):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"version": VERSION, "questions": len(q_rows), "source_rows": len(s_rows),
                      "rows_without_ai_prereview": sum(r["ai_prereview_verdict (read-only)"] == "(not pre-reviewed)" for r in s_rows),
                      "max_similarity": draft["max_similarity_to_earlier_questions"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
