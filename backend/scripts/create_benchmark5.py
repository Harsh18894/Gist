"""Create the Phase 2.3 final benchmark draft (v5): 24 held-out-only questions.

Questions were written source-first from customer statements and product-document facts
that no earlier benchmark (v2, benchmark 3, v4) used, never from retrieval output.
Temporal questions use report dates, which Phase 2.3 now sends to the model. One direct
question tests segment metadata. Evidence groups list every source containing a group
phrase within optional date bounds, or a named document. This script never runs
retrieval or answers and refuses to overwrite its outputs.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
import create_benchmark4 as base  # noqa: E402

VERSION = "gist-phase2.3-benchmark-5-draft"
OUT_DIR = ROOT / "evals/phase23"
DRAFT = OUT_DIR / "benchmark-v5-draft.json"
QUESTIONS_CSV = OUT_DIR / "Gist_Benchmark5_Questions_for_Human_Review.csv"
SOURCES_CSV = OUT_DIR / "Gist_Benchmark5_Sources_for_Human_Review.csv"
PREVIOUS = [ROOT / "evals/phase22/reviewed-v4/benchmark.json"]

B: list[dict] = []
q = lambda *args, **kw: base.q(*args, into=B, **kw)

# --- direct
q("direct", "How does the April digest update organize project summaries?",
  [["doc:release-03"]], ["doc:release-08"],
  "Project summaries are grouped by board (release-03).")
q("direct", "According to the shared-templates spec, at what point should teams find standard templates?",
  [["doc:prd-06"]], ["doc:release-06"],
  "During project creation (prd-06).")
q("direct", "What does the team-invitation spec say to do before blaming a cause for repeat-step reports?",
  [["doc:prd-01"]], ["doc:release-01"],
  "Investigate the repeat-step reports before assigning a cause (prd-01).")
q("direct", "Which customer segments reported the executive board taking 18 seconds to load?",
  [[("executive board spun for 18 seconds", None, None)]], [("Changing the date range hangs", None, None)],
  "Enterprise and Mid-market customers (from the report metadata).",
  "Answer depends on segment metadata sent with each source.")

# --- semantic
q("semantic", "Find someone whose colleague entered the previous password where the new one belonged.",
  [[("typed her old password into the new-password", None, None)]], [("changed my password, and the old one", None, None)],
  "Yes. A report says their designer could not log in because she typed her old password into the new-password field.")
q("semantic", "Did anyone see an invitation marked as taken up while the person still showed as waiting?",
  [[("Invite says accepted; member list says pending", None, None)]], [("finished the form twice", None, None)],
  "Yes. Reports say the invite shows accepted while the member list says pending.")
q("semantic", "Is there a customer who wants to check a few rows before running a large file upload?",
  [[("preview a sample before importing", None, None)]], [("need a way to undo yesterday", None, None)],
  "Yes. Customers asked to preview a sample before importing 2,000 rows.")
q("semantic", "Find a report of phone notifications for mentions stopping after someone adjusted alert settings.",
  [[("mentions stopped arriving on mobile", None, None)]], [("even urgent ones are delayed", None, None)],
  "Yes. A report says mentions stopped arriving on mobile after the notification sliders were changed.")

# --- multi-source
q("multi_source", "What different seat-billing mismatches did customers report?",
  [[("Our renewal estimate doesn't match", None, None)], [("show different seat totals on the same day", None, None)],
   [("Support explained that archived seats remain billable", None, None)]],
  [("breakdown is easier to read", None, None)],
  "Three kinds: a renewal estimate that did not match the amount charged; the invoice and admin page showing different seat totals on the same day; and archived seats remaining billable until the cycle closes, which support explained and the customer wanted the UI to state.")
q("multi_source", "Besides missing records, what other CRM connector problems or requests did customers raise?",
  [[("Sales moved an opportunity at 10", None, None)], [("handoff is now being done by spreadsheet", None, None)],
   [("failed-record count", None, None)]],
  [("I can't tell whether Pulse skipped", None, None)],
  "Stale tasks (an opportunity moved in the CRM while the Pulse task kept yesterday's version), a launch handoff falling back to spreadsheets, and a request for a failed-record count instead of only the last successful timestamp.")
q("multi_source", "What template permission problems did customers describe, and what resolved one of them?",
  [[("Our guest sees the shared plan", None, None)], [("Admin access works, contributor access doesn't", None, None)],
   [("Changing the member role fixed it", None, None)]],
  [("I only found the template menu", None, None)],
  "A guest could see the shared plan but not create a board from it, and admin access worked while contributor access did not. Changing the member role fixed one case, though the customer wanted a better error message.")
q("multi_source", "In what different ways did the project digest send more email than customers expected?",
  [[("Each shared board seems to send its own summary", None, None)], [("heard from all six", None, None)],
   [("separate mail for things that happened in the same hour", None, None)], [("too many pings for routine card edits", None, None)]],
  [("high-priority one came hours late", None, None)],
  "Each shared board sent its own summary; turning the digest on for one project produced mail from all six; separate emails arrived for things in the same hour; and routine card edits triggered too many pings.")

# --- temporal (report dates are now visible to the model)
q("temporal", "Were date-range hangs with all 40 projects reported both before and after the August loading update?",
  [["doc:release-07"], [("Changing the date range hangs", None, "2025-08-04")], [("Changing the date range hangs", "2025-08-05", None)]],
  [("It only feels slow when I switch to the full-year view", None, None)],
  "Yes. Reports of the date range hanging with all 40 projects appear before the August 5 update (release-07) and again afterwards. Timing alone does not show whether the update helped.")
q("temporal", "Relative to the February owner-checklist release, when were invites reported as accepted but still pending?",
  [["doc:release-01"], [("Invite says accepted; member list says pending", "2025-02-05", None)]],
  [("changed my password, and the old one", None, None)],
  "After it: the reports date from March to May 2025, after the February 5 release (release-01). The dates do not show that the release caused the problem.")
q("temporal", "Were greyed-out duplicate buttons on shared templates reported only after the July gallery release?",
  [["doc:release-06"], [("duplicate button is greyed out", "2025-07-05", None)]],
  [("I only found the template menu", None, None)],
  "In the reports found, yes: they date from late July 2025 onward, after the July 5 gallery release (release-06). This does not rule out differently worded earlier reports.")
q("temporal", "How does the report about an executive finally opening the overview relate in time to the August loading change?",
  [["doc:release-07"], [("Our COO can finally open the overview", None, None)]],
  [("executive board spun for 18 seconds", None, None)],
  "The report that the COO can finally open the overview before the meeting is dated November 2025, after the August 5 loading change (release-07). Timing suggests but does not prove the change helped.")

# --- contradictory
q("contradictory", "Did the template gallery save customers time?",
  [[("setup went from an hour to ten minutes", None, None)], [("blank board before the team's standard templates", None, None)]],
  [("Support said our workspace restricts template duplication", None, None)],
  "Mixed. Once found, it cut setup from an hour to ten minutes for some customers, while others said new users see a blank board before the team's standard templates.")
q("contradictory", "Does changing a SAML certificate always break single sign-on for good?",
  [[("changed the SAML certificate", None, None)], [("The SSO change worked once our team corrected the certificate", None, None)]],
  [("wrong callback URL", None, None)],
  "No. Some customers' login stopped after a certificate change, but in other reports the SSO change worked once the team corrected the certificate.")
q("contradictory", "Did one-time spreadsheet imports always fail for customers?",
  [[("put the wrong people on every task", None, None)], [("I fixed the header names and tried again", None, None)]],
  [("reconnected twice after the connector change", None, None)],
  "No. Some imports put the wrong people on every task, but at least one customer fixed the header names and the second import looked right.")
q("contradictory", "Did customers treat every seat-total mismatch as Pulse's fault?",
  [[("show different seat totals on the same day", None, None)], [("I had compared last month's roster", None, None)]],
  [("breakdown is easier to read", None, None)],
  "No. Some reported the invoice and admin page disagreeing on the same day, while another admitted part of the mismatch came from comparing last month's roster with this month's invoice.")

# --- unanswerable
q("unanswerable", "What is the average time support takes to resolve a single sign-on ticket?",
  [], [("wrong callback URL", None, None)],
  "Abstain. No source states ticket resolution times.")
q("unanswerable", "How many seats does the largest Enterprise customer pay for?",
  [], ["doc:release-04"],
  "Abstain. No source states any customer's seat count.")
q("unanswerable", "Which competitor's digest do customers compare Pulse with?",
  [], [("We use Okta for everyone", None, None)],
  "Abstain. No source names a competitor; Okta appears only as an identity provider.")
q("unanswerable", "What NPS score did Pulse receive after the template gallery launched?",
  [], [("setup went from an hour to ten minutes", None, None)],
  "Abstain. No source reports an NPS or satisfaction score.")


def main() -> int:
    for path in (DRAFT, QUESTIONS_CSV, SOURCES_CSV):
        if path.exists():
            raise FileExistsError(f"{path} exists; drafts are not overwritten.")
    previous = tuple(x["question"] for path in PREVIOUS for x in json.loads(path.read_text())["questions"])
    draft, q_rows, s_rows = base.build(B, VERSION, extra_previous=previous, id_prefix="B5-Q")
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
