"""Generalization cases for the evidence gate (`app.rag.evidence.assess`).

These cases are hand-written from the gate's *policy* — abstain when a question
demands a kind of fact the retrieved evidence does not state — and are
deliberately independent of `evals/`. Do not copy benchmark questions or
benchmark source text into this file; it exists to catch rules that only fit
the benchmark wording.
"""
import pytest

from app.rag.evidence import assess
from app.rag.retrieval import Hit


def _hits(*texts: str) -> list[Hit]:
    return [Hit(f"case-{i}:000", f"case-{i}", "Case", "feedback", "case.txt", None,
                None, None, text, 1.0, 1, None) for i, text in enumerate(texts)]


# (question, evidence texts, expected sufficient)
CASES = {
    # --- person attribution: needs a named individual in a responsible role
    "person/team-paraphrase": ("Who on the team caused the CRM sync bug?",
                               ["The CRM sync bug dropped contacts after the update."], False),
    "person/developer": ("Which developer broke the billing export?",
                         ["Billing export broke after the release."], False),
    "person/teammate": ("Which teammate introduced the dashboard regression?",
                        ["Dashboard regression since Tuesday."], False),
    "person/unnamed-teammate": ("Who introduced the dashboard regression?",
                                ["Dashboard regression since Tuesday; a teammate blamed the new chart library."], False),
    "person/named-engineer": ("Which engineer introduced the dashboard regression?",
                              ["Engineer Priya introduced the dashboard regression in the chart refactor."], True),
    "person/named-subject": ("Who broke the billing export?",
                             ["Release note: Marco broke the billing export when renaming columns."], True),
    "person/approved-unnamed": ("Who approved the refund policy change?",
                                ["The refund policy changed in March after a pricing review."], False),
    "person/approved-named": ("Who approved the refund policy change?",
                              ["Finance memo: lead Dana approved the refund policy change in March."], True),
    "person/control-reported": ("Who reported CRM sync failures?",
                                ["Enterprise admins reported CRM sync failures after reconnecting."], True),
    "person/control-affected": ("Who is affected by the digest change?",
                                ["SMB teams are affected by the digest change."], True),

    # --- money: needs a stated amount
    "money/how-much-make": ("How much money did the annual plan launch make?",
                            ["Customers liked the annual plan launch."], False),
    "money/sales": ("What were sales from the annual plan launch?",
                    ["Customers liked the annual plan launch."], False),
    "money/earn": ("How much did the onboarding update earn?",
                   ["The onboarding update shortened setup."], False),
    "money/income": ("What income did the template gallery generate?",
                     ["Template gallery adoption grew quickly."], False),
    "money/stated": ("How much revenue did the annual plan launch generate?",
                     ["Finance note: the annual plan launch generated $12,400 in new revenue."], True),
    "money/control-how-much-slower": ("How much slower is the dashboard after August?",
                                      ["The dashboard is much slower after the August update."], True),
    "money/control-sales-records": ("Did the connector drop sales records?",
                                    ["The connector dropped sales records during sync."], True),

    # --- aggregate counts: needs an explicitly stated total
    "count/in-total": ("How many sync failures were there in total?",
                       ["Another sync failure this morning."], False),
    "count/exact-number": ("What is the exact number of failed imports?",
                           ["Our import failed again."], False),
    "count/population": ("How many enterprise customers hit the verification loop?",
                         ["Two of our admins hit the verification loop."], False),
    "count/population-reports": ("How many reports mention CRM sync?",
                                 ["Another CRM sync report from an admin."], False),
    "count/stated-total": ("How many sync failures were there in total?",
                           ["Support summary: 37 sync failures in total were logged across all workspaces."], True),
    "count/control-document-fact": ("How many steps does the onboarding checklist have?",
                                    ["The onboarding checklist has five steps."], True),
    "count/complete-qualifier": ("What is the complete count of failed invoice exports?",
                                 ["Two invoice exports failed for us this week."], False),
    "count/full-number-everyone": ("Give the full number of dropped webhooks for every workspace.",
                                   ["Our webhook dropped twice yesterday."], False),
    "count/entire-stated": ("What is the entire count of dropped webhooks?",
                            ["Platform report: 12 dropped webhooks in total across all workspaces."], True),

    # --- causation: needs a stated cause
    "cause/why-did": ("Why did imports fail for SMB teams?",
                      ["Imports failed for our SMB team again."], False),
    "cause/reason-for": ("What is the reason for the dashboard slowdown?",
                         ["Dashboard slowdown is painful."], False),
    "cause/led-to": ("What led to the duplicate invoices?",
                     ["We got duplicate invoices this month."], False),
    "cause/stated-because": ("Why did imports fail?",
                             ["Imports fail because the CSV header was misconfigured."], True),
    "cause/stated-due-to": ("What is the reason for the dashboard slowdown?",
                            ["The dashboard slowdown happened due to the disabled widget cache."], True),
    "cause/control-why-like": ("Why do customers like the weekly digest?",
                               ["We like the weekly digest because it is calmer."], True),

    # --- universal claims: mixed evidence answers "no, it was mixed"
    "universal/mixed-single-term-hits": ("Did everyone love the redesign?",
                                         ["Love it!", "Hated the redesign."], True),
    "universal/one-sided-single-term-hits": ("Did everyone love the redesign?",
                                             ["Love it!", "Love the colors."], False),
    "universal/mixed-covering-hits": ("Did all teams find the weekly digest helpful?",
                                      ["The weekly digest is helpful for us.",
                                       "The digest is noisy and annoying; we turned it off."], True),

    # --- named product processes: evidence must be about the same process
    "process/password-not-invitation": ("Was invitation verification blocked?",
                                        ["My password reset link expired."], False),
    "process/invitee-synonyms": ("Was invitation verification blocked?",
                                 ["Invitees were sent back to the join form."], True),
    "process/import-not-connector": ("Is the CRM connector failing?",
                                     ["The CSV import is failing for CRM exports."], False),
    "process/tickets-not-alerts": ("Are urgent alerts delayed?",
                                   ["Urgent tickets are delayed in the queue."], False),
    "process/alerts-synonym": ("Are urgent alerts delayed?",
                               ["Urgent notifications are delayed by an hour."], True),

    # --- ordinary questions that must keep working
    "control/ui-release-date": ("What did Pulse release on 2025-04-05?",
                                ["Pulse release 03: Notification digest update. Published: 2025-04-05."], True),
    "control/ui-crm-sync": ("What are customers saying about CRM sync?",
                            ["CRM sync keeps failing for our enterprise workspace."], True),
    "control/ui-prd-owner-area": ("Which product area owns the shared templates PRD?",
                                  ["Shared templates PRD. Product area: Collaboration."], True),
    "control/off-topic": ("Is the CRM connector failing?",
                          ["The billing page shows seat totals."], False),
}


@pytest.mark.parametrize("question,texts,expected", CASES.values(), ids=CASES.keys())
def test_evidence_gate_generalizes(question, texts, expected):
    result = assess(question, _hits(*texts))
    assert result.sufficient is expected, result.reason


def test_insufficient_results_name_the_rule():
    assert assess("How much money did the launch make?", _hits("The launch went well.")).rule == "money"
    assert assess("Who on the team caused the bug?", _hits("The bug is back.")).rule == "person"
    assert assess("Is the CRM connector failing?", _hits("The CSV import is failing for CRM.")).rule == "process"
    assert assess("CRM sync failure", _hits("CRM sync failure again.")).rule == "sufficient"
