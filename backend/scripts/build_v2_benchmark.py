"""Author-curated Pulse v2 benchmark blueprints, independent of retrieval output."""
from __future__ import annotations

import json
from pathlib import Path

# Reference IDs name the scenario model or published documents, never search terms.
DIRECT = [
    ("Which release introduced the owner checklist before invitations?", ["release-01"], "The February 5 checklist clarifies owner verification before invites."),
    ("When did portfolio filters become available?", ["release-02"], "March 5, 2025."),
    ("What default selection did the April summary change use?", ["release-03"], "Shared boards were selected by default."),
    ("How are seats archived during a billing cycle counted?", ["release-04"], "They remain counted until the cycle closes."),
    ("What changed in the June connector release?", ["release-05"], "Reconnect flow and sync status display changed."),
    ("Where is the shared starter gallery located?", ["release-06"], "In the workspace menu."),
    ("What did the August portfolio update target?", ["release-07"], "A faster aggregation path for large workspaces."),
    ("What should remain timely after project alert controls are adjusted?", ["release-08"], "Critical and direct-mention alerts."),
    ("Does the team invitation specification say every invitee verifies the owner?", ["prd-01"], "No. The owner verification should not repeat for each invitee."),
    ("Which two portfolio concerns are separated in the product specification?", ["prd-02"], "Large-workspace loading and visible filter state."),
    ("Does the connector specification treat spreadsheet import as live sync?", ["prd-03"], "No; CSV import mapping is a separate workflow."),
    ("What evidence does finance need beyond an invoice adjustment line?", ["prd-04"], "Invoice-time seat evidence."),
    ("Which two notification failure modes does the specification separate?", ["prd-05"], "Too many routine digests and delayed urgent alerts."),
    ("What controls whether a person may copy a team starter?", ["prd-06"], "Workspace role permissions."),
    ("Did any customer say a replacement sign-in email had gone stale?", ["RESET_LOGIN"], "Yes; a customer reported an expired or stale password-reset link."),
]

SEMANTIC = [
    ("What evidence suggests people invited to a workspace can get stuck even when its owner has completed setup?", ["INVITE_LOOP"], "Invitees report loops or repeated setup despite an owner-complete checklist."),
    ("Find a customer account of a credential recovery message arriving too late to be useful.", ["RESET_LOGIN"], "A password-reset link expired or became stale."),
    ("Is there evidence that corporate identity configuration, rather than a password, blocked access?", ["SSO_SETUP"], "SAML certificate, callback, domain, or tenant settings caused sign-in problems."),
    ("What did teams observe when their sales system appeared connected but work items were absent?", ["CRM_SYNC"], "A green or successful sync status accompanied missing or stale records."),
    ("Find evidence that a one-off spreadsheet upload placed data in incorrect fields.", ["CSV_MAPPING"], "CSV column mapping put values in the wrong fields."),
    ("How did people with many shared boards react to the spring email summary behavior?", ["DIGEST_NOISE"], "They received too many routine emails, especially across several boards."),
    ("Can a calmer inbox coincide with a missed escalation?", ["ALERT_DELAY"], "Yes; later reports describe delayed urgent alerts or mentions."),
    ("Find a report of leadership waiting on a cross-project view before a meeting.", ["DASH_SLOW"], "Large-workspace portfolio loading delayed review meetings."),
    ("Did anyone mistake a hidden selection for absent chart data?", ["DASH_FILTER"], "Yes; an applied or hidden filter led to an incorrect impression of missing data."),
    ("Why might finance see more billed people than the current active roster?", ["SEAT_BILL"], "Archived seats remain billed until the cycle ends; invoice and current roster may differ."),
    ("Did anyone recreate a standard board because they could not locate the starter?", ["TEMPLATE_FIND"], "Yes; people missed the gallery and rebuilt a board."),
    ("Find a case where the shared starter was visible but unusable to a teammate.", ["TEMPLATE_ACCESS"], "A role restriction disabled duplication despite visible templates."),
    ("Are there customer accounts of work being done in spreadsheets while a connected sales feed lagged?", ["CRM_SYNC"], "Yes; teams used spreadsheets when connector updates were missing."),
    ("Find complaints about repeated entry steps from people other than workspace owners.", ["INVITE_LOOP"], "Invited team members, not only owners, faced repeat steps."),
    ("Did anyone need to amend member permissions to use a board starter?", ["TEMPLATE_ACCESS"], "Changing a member role resolved template copying for at least one customer."),
]

MULTI = [
    ("How should an investigator distinguish three reasons someone cannot sign in?", ["INVITE_LOOP", "RESET_LOGIN", "SSO_SETUP", "prd-01"], "Invitation handoff, password recovery, and SSO configuration are distinct. Inspect context before assigning cause."),
    ("What changed in July, and why could someone still fail to start from a shared board?", ["release-06", "TEMPLATE_FIND", "TEMPLATE_ACCESS"], "The gallery launched; discoverability and role permissions remained separate barriers."),
    ("How could customer reactions to the April email change differ with workspace size?", ["release-03", "DIGEST_NOISE"], "Shared boards were included by default; one-board users could like it while multi-board users received too many summaries."),
    ("What evidence separates stale sales records from a corrupted spreadsheet import?", ["CRM_SYNC", "CSV_MAPPING", "prd-03"], "Live connector reports absent or stale records; CSV upload reports wrong field mapping."),
    ("How did the August performance release relate to earlier large-workspace complaints?", ["release-07", "DASH_SLOW"], "The release targeted large-workspace aggregation after earlier slow-view complaints; improvement reports exist but are not universal."),
    ("Why might a dashboard look wrong even when it loads quickly?", ["DASH_FILTER", "release-02", "DASH_SLOW"], "A hidden or stale filter can make data appear absent, separate from slow loading."),
    ("What evidence would explain a discrepancy between finance's invoice and the admin roster?", ["SEAT_BILL", "release-04", "prd-04"], "Mid-cycle archived seats remain counted and invoice-time seat evidence is needed."),
    ("How did September controls address one alert complaint while leaving another concern to investigate?", ["release-08", "DIGEST_NOISE", "ALERT_DELAY"], "Per-project controls reduced routine noise; later reports of delayed critical alerts require investigation."),
    ("What supports a cautious timeline for missing sales tasks after the June connector change?", ["release-05", "CRM_SYNC"], "Reports followed the refresh, but the release notes and reports do not prove the update caused missing records."),
    ("Where can a PM find evidence that onboarding and collaboration problems overlap?", ["INVITE_LOOP", "TEMPLATE_FIND", "prd-01", "prd-06"], "Invitation handoff and starter discovery can both interrupt initial team setup, but they have different mechanisms."),
]

CONTRADICTION = [
    ("Did the spring summaries make everyone's inbox worse?", ["DIGEST_NOISE", "release-03"], "No. Some customers liked the digest, while others with many boards saw too much email."),
    ("Was every large-workspace portfolio view still slow after August?", ["DASH_SLOW", "release-07"], "No universal conclusion. Some reported relief; later performance needs separate evidence."),
    ("Can all failed sign-ins be attributed to the owner checklist?", ["INVITE_LOOP", "RESET_LOGIN", "SSO_SETUP"], "No. Password recovery and SSO settings also account for access reports."),
    ("Did a green connector status prove all sales records arrived?", ["CRM_SYNC", "release-05"], "No. Customers reported missing records despite successful status; root cause remains uncertain."),
    ("Do the later notification reports prove the September controls delayed urgent alerts?", ["ALERT_DELAY", "release-08"], "No. Reports occurred afterward, but causation is not established."),
]

UNANSWERABLE = [
    ("What percentage of real Pulse customers churned because of the invite loop?", "Abstain: no real customers or churn data exist in this synthetic corpus."),
    ("Which engineer introduced the CRM missing-record defect?", "Abstain: no engineer attribution or confirmed causal defect is documented."),
    ("How much revenue did the August loading update generate?", "Abstain: revenue impact is not provided."),
    ("What is the exact global count of urgent alerts lost after September 5?", "Abstain: no complete alert telemetry or global count is present."),
    ("Which specific user's account was compromised during the SSO configuration failures?", "Abstain: compromise is not documented."),
]

# Question-specific, author-reviewed evidence anchors. The scenario annotations
# form candidate pools; they are too broad to serve as relevance judgments for
# narrowly worded questions. These cues are applied to the source corpus, never
# to retriever output. The resulting source IDs are frozen with the benchmark.
EVIDENCE_CUES: dict[int, list[str]] = {
    15: ["The first email was stale"],
    16: ["the checklist is marked complete", "Nobody I invited yesterday can"],
    17: ["reset link expired"],
    18: ["SAML certificate", "wrong callback URL"],
    19: ["CRM tile is green", "successful sync stamp"],
    20: ["owner names landed", "two columns were swapped"],
    21: ["38 project emails", "Each shared board seems to send"],
    22: ["high-priority one came hours late"],
    23: ["Monday meeting starts without it", "executive board spun"],
    24: ["chart wasn't missing data", "report was broken because only one workspace"],
    25: ["archived two collaborators", "archived seats remain billable"],
    26: ["gallery exists? We rebuilt", "assumed there were no shared starters"],
    27: ["duplicate button is greyed out", "doesn't have permission to use it"],
    28: ["handoff is now being done by spreadsheet"],
    29: ["second person has to repeat", "Nobody I invited yesterday can"],
    30: ["Changing the member role fixed it"],
    31: ["the checklist is marked complete", "reset link expired", "SAML certificate"],
    32: ["gallery exists? We rebuilt", "duplicate button is greyed out"],
    33: ["38 project emails", "digest works well for my one-board"],
    34: ["CRM tile is green", "owner names landed"],
    35: ["Monday meeting starts without it", "August loading update was a relief"],
    36: ["chart wasn't missing data", "portfolio screen kept loading"],
    37: ["archived two collaborators", "archived seats remain billable"],
    38: ["38 project emails", "high-priority one came hours late"],
    39: ["gap after the June refresh", "CRM tile is green"],
    40: ["Nobody I invited yesterday can", "gallery exists? We rebuilt"],
    41: ["38 project emails", "digest works well for my one-board"],
    42: ["August loading update was a relief", "portfolio screen kept loading"],
    43: ["the checklist is marked complete", "reset link expired", "SAML certificate"],
    44: ["CRM tile is green", "integration is stable again"],
    45: ["high-priority one came hours late", "test mention arrived immediately"],
}

# In multi-source and contradiction questions, source documents are required
# alongside customer reports when they define a release or product rule.
DOCUMENT_EVIDENCE: dict[int, list[str]] = {
    31: ["prd-01"], 32: ["release-06"], 33: ["release-03"], 34: ["prd-03"],
    35: ["release-07"], 36: ["release-02"], 37: ["release-04"],
    38: ["release-08"], 39: ["release-05"], 40: ["prd-01", "prd-06"],
    41: ["release-03"], 42: ["release-07"], 43: ["prd-01"],
    44: ["release-05"], 45: ["release-08"],
}


def build_benchmark(evals: Path, annotations: list[dict], feedback: list[dict]) -> None:
    by_issue: dict[str, list[str]] = {}
    for item in annotations:
        for issue in item.get("issue_ids", []):
            by_issue.setdefault(issue, []).append(item["source_id"])
    questions: list[dict] = []
    for category, rows in (("direct", DIRECT), ("semantic", SEMANTIC), ("multi_source", MULTI), ("contradiction_ambiguity", CONTRADICTION)):
        for question, refs, expected in rows:
            number = len(questions) + 1
            candidate_ids = sorted(set(source for ref in refs for source in by_issue.get(ref, [ref])))
            if number in EVIDENCE_CUES:
                judged = []
                for cue in EVIDENCE_CUES[number]:
                    matches = [row for row in feedback if cue.lower() in row["feedback_text"].lower()]
                    if number == 42 and "portfolio screen kept loading" in cue:
                        matches = [row for row in matches if row["timestamp"][:10] >= "2025-08-05"]
                    if number == 35 and "Monday meeting starts without it" in cue:
                        matches = [row for row in matches if row["timestamp"][:10] < "2025-08-05"]
                    if not matches:
                        raise ValueError(f"No evidence for V2-Q-{number:03d}: {cue}")
                    preferred = next((row for row in matches if len(next(a for a in annotations if a["source_id"] == row["id"])["issue_ids"]) == 1), matches[0])
                    judged.append(preferred["id"])
                ids = sorted(set(judged + DOCUMENT_EVIDENCE.get(number, [])))
            else:
                ids = candidate_ids
            representative = ids[:]
            scope = "focused" if category == "direct" else "representative" if category in {"semantic", "contradiction_ambiguity"} else "aggregate"
            questions.append({"id": f"V2-Q-{len(questions)+1:03d}", "dataset_version": "v2", "question": question,
                              "difficulty": "easy" if category == "direct" else "medium" if category == "semantic" else "hard",
                              "evaluation_category": category, "relevant_source_ids": ids,
                              "candidate_source_ids": candidate_ids,
                              "expected_evidence": refs, "expected_answer_or_abstention": expected,
                              "notes": "Corroborate with source dates; reports alone do not establish causality." if category in {"multi_source", "contradiction_ambiguity"} else "Synthetic source evidence.",
                              "relevance_scope": scope, "representative_source_ids": representative,
                              "judgment_completeness": "representative_only" if number >= 15 else "focused_document",
                              "aggregate_analysis_required": scope == "aggregate",
                              "suggested_metrics": ["hit_rate_at_5", "mrr_at_5"] if scope == "focused" else ["evidence_coverage", "mrr_at_5"]})
    for question, expected in UNANSWERABLE:
        questions.append({"id": f"V2-Q-{len(questions)+1:03d}", "dataset_version": "v2", "question": question,
                          "difficulty": "hard", "evaluation_category": "unanswerable", "relevant_source_ids": [],
                          "candidate_source_ids": [],
                          "expected_evidence": [], "expected_answer_or_abstention": expected,
                          "notes": "Must abstain; absence of evidence does not support invented facts.",
                          "relevance_scope": "none", "representative_source_ids": [], "aggregate_analysis_required": False,
                          "judgment_completeness": "abstention",
                          "suggested_metrics": ["abstention_accuracy"]})
    (evals / "questions.json").write_text(json.dumps({"synthetic": True, "dataset_version": "v2", "construction": "Human-authored question blueprints tied to scenario ground truth, not retriever results.", "questions": questions}, indent=2) + "\n", encoding="utf-8")
