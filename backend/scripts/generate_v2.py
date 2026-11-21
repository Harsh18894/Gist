"""Generate fictional Pulse v2 from a fixed scenario model; no network or AI calls."""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261027
START = datetime(2025, 1, 8, 9, tzinfo=timezone.utc)
END = datetime(2025, 12, 15, 18, tzinfo=timezone.utc)
SEGMENTS = ("Individual", "SMB", "Mid-market", "Enterprise")
TIERS = dict(zip(SEGMENTS, ("Starter", "Team", "Business", "Enterprise")))

# This model is authoring data. Issue IDs and certainty never enter the indexed corpus.
SCENARIOS = {
    "INVITE_LOOP": dict(area="Onboarding", category="Verification friction", feature="team invitations", onset="2025-02-06", end=None, segments=("SMB", "Mid-market", "Enterprise"),
        lines=["The invite looked fine until Maya clicked it; she wound up back at the same setup screen.", "Three new analysts have been waiting since Monday. The email link opens, then asks them to start over.", "Why does every person we add need to go through that company check again?", "I can get in. Nobody I invited yesterday can.", "Our new hire finished the form twice and still isn't in the workspace.", "The join button just sends people in a circle. We're onboarding six folks this week.", "We assumed the admin had missed a step, but the checklist is marked complete on her side.", "Invite says accepted; member list says pending. Which one is right?", "We've lost half a day getting a contractor through the front door.", "It finally worked on the third link. That is a rough first impression.", "The checklist is clearer now, but the invited-user handoff is still awkward.", "Could someone tell me why a second person has to repeat what our owner already did?"]),
    "RESET_LOGIN": dict(area="Onboarding", category="Account access", feature="password reset", onset="2025-01-08", end=None, segments=SEGMENTS,
        lines=["I used the reset email, changed my password, and the old one is still the only one that works.", "Can you check the password email? It landed in spam, so I thought I was locked out.", "Sign-in failed this morning after I reset my password. I may have copied the wrong value.", "The reset link expired while I was on a call.", "We need clearer guidance when a password link has timed out.", "Not a team invite problem; I can see the login form, but my new password is rejected.", "I got back in after requesting another reset. The first email was stale.", "Does the reset link work across devices? I opened it on my phone and returned to desktop.", "Our designer couldn't log in; she had typed her old password into the new-password field.", "The sign-in message says invalid credentials, which doesn't explain an expired reset token."]),
    "SSO_SETUP": dict(area="Onboarding", category="Account access", feature="single sign-on", onset="2025-01-08", end=None, segments=("Mid-market", "Enterprise"),
        lines=["Our IdP sends an assertion but Pulse says this domain isn't allowed.", "Login stopped after we changed the SAML certificate in our identity provider.", "The SSO screen loads, then returns a tenant mismatch. Password login still works.", "We discovered our IT team had entered the wrong callback URL.", "Can someone check the domain mapping for our second subsidiary?", "The error looks like a failed sign-in but our admin says the identity configuration is incomplete.", "We use Okta for everyone; one region is being sent to the wrong workspace.", "Please stop suggesting password resets for this one. The SAML response itself is rejected.", "The SSO change worked once our team corrected the certificate.", "A contractor on a different domain can't use our company login."]),
    "CRM_SYNC": dict(area="Integrations", category="Integration failures", feature="CRM connector", onset="2025-06-06", end="2025-10-10", segments=("SMB", "Mid-market", "Enterprise"),
        lines=["The CRM tile is green, but the newest accounts never showed up in our board.", "Sales moved an opportunity at 10; the task in Pulse is still yesterday's version.", "We reconnected twice after the connector change and the queue still hasn't caught up.", "A successful sync stamp is misleading when records are absent.", "The connector looks connected. Why are the tasks from the East region missing?", "Our launch checklist depended on CRM updates; the handoff is now being done by spreadsheet.", "I can't tell whether Pulse skipped these records or the CRM never sent them.", "It recovered overnight after support walked us through reconnecting.", "We saw a gap after the June refresh, then a backfill on Friday.", "The same sales account appears in CRM but not in our project view.", "Any way to show a failed-record count instead of only the last successful timestamp?", "The integration is stable again this week; keeping an eye on the queue."]),
    "CSV_MAPPING": dict(area="Integrations", category="Import mapping", feature="CSV import", onset="2025-01-08", end=None, segments=SEGMENTS,
        lines=["Our CSV import finished, but owner names landed in the due-date column.", "The file uploaded; it just put the wrong people on every task.", "We mapped Account ID to the custom field and it was silently treated as a name.", "This isn't a live CRM sync. It's the one-time spreadsheet upload that scrambled labels.", "Can we preview a sample before importing 2,000 rows?", "The import report said success even though two columns were swapped.", "I fixed the header names and tried again. The second import looks right.", "Date cells from the sheet became blank on the board.", "Our contractor exported a CSV with semicolons; Pulse read it as one column.", "I need a way to undo yesterday's spreadsheet import."]),
    "DIGEST_NOISE": dict(area="Notifications", category="Notification overload", feature="project digest", onset="2025-04-06", end="2025-09-05", segments=SEGMENTS,
        lines=["I woke up to 38 project emails; I thought the point of a digest was fewer messages.", "Each shared board seems to send its own summary now. My inbox is basically Pulse.", "I turned the digest on for one project and somehow heard from all six.", "Can we choose which boards contribute to the morning email?", "There are too many pings for routine card edits.", "The April change made it easier to scan updates but harder to ignore low-priority projects.", "I'm getting separate mail for things that happened in the same hour.", "Please give us a quiet setting for the projects we're merely observing.", "The digest works well for my one-board workspace, honestly.", "Our PM loves the new summaries; engineering muted everything after the third day.", "The new per-project control in September finally lets me calm down the weekly noise.", "I don't mind a summary, but the default should not include every shared space."]),
    "ALERT_DELAY": dict(area="Notifications", category="Alert delivery", feature="critical alerts", onset="2025-09-06", end=None, segments=("SMB", "Mid-market", "Enterprise"),
        lines=["The project is quiet now, including the one alert I actually needed before our review.", "A task was marked urgent at noon; nobody was notified until evening.", "After changing the notification sliders, mentions stopped arriving on mobile.", "Our on-call person missed a critical update. The routine summaries were fine.", "We're seeing fewer emails, but the high-priority one came hours late.", "Did the new controls suppress direct mentions too?", "I like the calmer inbox; I don't like discovering an escalation in tomorrow's digest.", "The test mention arrived immediately for me. Two teammates say theirs never did.", "We disabled a board's routine alerts, and now even urgent ones are delayed.", "Can support tell us whether the event was queued or never emitted?"]),
    "DASH_SLOW": dict(area="Dashboard", category="Slow performance", feature="portfolio dashboard", onset="2025-01-08", end=None, segments=("Mid-market", "Enterprise"),
        lines=["Portfolio view takes long enough that our Monday meeting starts without it.", "Changing the date range hangs when I include all 40 projects.", "A small workspace loads quickly; our regional roll-up does not.", "The executive board spun for 18 seconds during the review.", "We ended up exporting data because the portfolio screen kept loading.", "It only feels slow when I switch to the full-year view.", "The August loading update was a relief for our large workspace.", "Our COO can finally open the overview before the meeting begins.", "A chart loads fast for me, but my colleague has a much larger workspace.", "We were told to clear cache, but this happens on three machines."]),
    "DASH_FILTER": dict(area="Dashboard", category="Feature discoverability", feature="portfolio filters", onset="2025-03-06", end=None, segments=SEGMENTS,
        lines=["The numbers are fine. I just can't work out where the region selector went.", "We thought the portfolio had no filter until someone showed us the little funnel.", "The view is fast, but the controls are buried above the chart.", "Could the date range be more visible for new managers?", "I spent ten minutes looking for the team filter. It was tucked into a menu.", "The chart wasn't missing data; we'd left a previous filter applied.", "Nice new filter options, though the active state is hard to notice.", "Our PM thought the report was broken because only one workspace was selected.", "It would help to show the current filter in exported screenshots.", "Nothing is slow here; we simply couldn't find the setting."]),
    "SEAT_BILL": dict(area="Billing", category="Billing confusion", feature="seat invoice", onset="2025-01-08", end=None, segments=("SMB", "Mid-market", "Enterprise"),
        lines=["We archived two collaborators but the invoice still counts them. Is that expected?", "Finance asked why the May total rose even though headcount didn't.", "The seat adjustment line helps, but I can't trace it to actual people.", "Our renewal estimate doesn't match the amount charged for this month.", "Support explained that archived seats remain billable until the cycle closes; the UI should say that.", "I had compared last month's roster with this month's invoice, so part of this was on me.", "Can we download a list of seats counted at invoice time?", "The breakdown is easier to read now; the mid-cycle change is still opaque.", "We moved a contractor out on the 27th and got billed for the whole cycle.", "The invoice and admin page show different seat totals on the same day."]),
    "TEMPLATE_FIND": dict(area="Collaboration", category="Feature discoverability", feature="shared templates", onset="2025-07-06", end=None, segments=SEGMENTS,
        lines=["The gallery exists? We rebuilt the same kickoff board by hand.", "I only found the template menu after support sent a screenshot.", "Could templates appear when I create a project, rather than several clicks later?", "The new gallery is useful once you know where it lives.", "Our new PM assumed there were no shared starters in Pulse.", "I searched for the launch plan inside projects, never thought to check the workspace menu.", "The docs say templates are shared, but the entry point is easy to miss.", "Once we found it, setup went from an hour to ten minutes.", "Why does a new user see a blank board before the team's standard templates?", "The gallery is helpful; discoverability is the remaining rough edge."]),
    "TEMPLATE_ACCESS": dict(area="Collaboration", category="Template permissions", feature="shared templates", onset="2025-07-06", end=None, segments=("SMB", "Mid-market", "Enterprise"),
        lines=["I can see the kickoff template, but the duplicate button is greyed out.", "The gallery is easy to find now; my teammate doesn't have permission to use it.", "Our guest sees the shared plan but can't create a board from it.", "Admin access works, contributor access doesn't. Is that intended?", "We tried showing the new hire where templates live; she found them and still couldn't start.", "The menu isn't missing. The role policy seems to block copying.", "Support said our workspace restricts template duplication to editors.", "Can viewers request access from the gallery instead of getting a disabled button?", "One department can copy the template; another is under a different role rule.", "Changing the member role fixed it, though we need a better error message."]),
}

CONTEXT = [
    "This is from a new team member, not the workspace owner.", "We are in the middle of a launch, so timing matters.",
    "Our admin is in another time zone and hasn't seen this yet.", "I checked with two colleagues and they had different results.",
    "We can work around it for now, but I wanted the team to know.", "Happened once yesterday and again this morning.",
    "Happy to send a screen recording if that helps.", "Our pilot group is small, so this is anecdotal.",
    "I'm reporting this after our weekly planning session.", "I may be missing a setting; please point me to it if so.",
    "The rest of the product has been fine for us.", "This came up while we were training new staff.",
    "I don't know if anyone else in our company has seen it.", "We have multiple workspaces, and only one seems affected.",
]
AMBIGUOUS = [
    "It isn't working again. I was in the middle of setup.", "Same thing as yesterday, I think?", "I pressed the button and waited. Nothing useful happened.",
    "Not sure if this is on our side or yours, but the team is blocked.", "The page looked odd this morning. Haven't managed to repeat it.",
    "Anyone else seeing a delay? Might be my wifi.", "I got an error once, then it went away.",
    "This feels off after the update, although I can't pin down what changed.", "Still stuck. Will send more details when I have them.",
]
SUPPORT_REPLY = [
    "Support: We asked for a timestamp and workspace ID; cause is not established yet.",
    "Support: We checked the account settings. The customer will retry after their next team meeting.",
    "Support: We reproduced the behavior in one workspace, but not in the smaller test workspace.",
    "Support: We shared a temporary workaround and requested a follow-up if it recurs.",
    "Support: We need logs before attributing this to the recent release.",
]

MIN_LINE_DATE = {
    "The August loading update": "2025-08-05", "Our COO can finally": "2025-08-05",
    "The new per-project control in September": "2025-09-05",
    "Finance asked why the May": "2025-05-01",
    "The breakdown is easier to read now": "2025-05-05",
    "The seat adjustment line helps": "2025-05-05",
}


def _eligible_lines(scenario: dict, day: str) -> list[str]:
    return [line for line in scenario["lines"] if all(not line.startswith(prefix) or day >= minimum
            for prefix, minimum in MIN_LINE_DATE.items())]

RELEASES = [
    ("2025-02-05", "Workspace verification checklist", "Onboarding", "The checklist clarifies owner verification before team invitations. Invited users should not need to verify the owner again. Some later reports describe a repeat step; investigation remains open."),
    ("2025-03-05", "Portfolio filters", "Dashboard", "Admins can filter portfolio views by project and date. The control appears above the chart. This release did not change loading performance."),
    ("2025-04-05", "Project digest update", "Notifications", "Project summaries are grouped by board. Shared boards are selected by default; teams can opt out. Customer reactions may vary with board count."),
    ("2025-05-05", "Invoice breakdown", "Billing", "Invoices show seat adjustment line items. Seats archived mid-cycle remain counted until the billing cycle closes."),
    ("2025-06-05", "CRM connector refresh", "Integrations", "The connector has a new reconnect flow and sync status. A successful status does not prove every record arrived. Later missing-record reports are under investigation; causality is not established."),
    ("2025-07-05", "Shared template gallery", "Collaboration", "The gallery is in the workspace menu. Copying a template follows workspace role permissions; editors and admins may duplicate it."),
    ("2025-08-05", "Portfolio loading update", "Dashboard", "Large workspace aggregations use a faster path. Smaller workspaces may see little difference. Some customers still report slow views."),
    ("2025-09-05", "Per-project notification controls", "Notifications", "Admins can tune routine project alerts. Critical and direct-mention alerts are intended to remain timely; later delay reports are being investigated."),
]

PRDS = [
    ("team invitation handoff", "Onboarding", "Owners need to invite staff without asking each person to repeat owner verification. A confusing handoff may block onboarding. Investigate repeat-step reports before assigning cause."),
    ("portfolio experience", "Dashboard", "Large workspaces need timely portfolio loading. Managers also need clear filter state; a hidden filter is distinct from a slow query."),
    ("CRM integration reliability", "Integrations", "Teams need to know when records are missing even if the connector reports success. CSV import mapping is a separate workflow."),
    ("seat billing clarity", "Billing", "Finance teams need invoice-time seat evidence and clear mid-cycle rules. The May line item does not identify people by itself."),
    ("notification relevance", "Notifications", "Readers need fewer routine digests without delaying urgent alerts. These are separate failure modes."),
    ("shared starter templates", "Collaboration", "Teams should find standard templates during project creation. Access to duplicate a template follows role permissions, which is a separate concern."),
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def generate(output_data: Path | None = None, output_evals: Path | None = None, *, replace: bool = False) -> dict[str, int]:
    data = output_data or ROOT / "data/v2"
    evals = output_evals or ROOT / "evals/v2"
    if not replace and any(p.exists() for p in (data / "feedback.jsonl", data / "support-tickets.jsonl", evals / "questions.json")):
        raise FileExistsError("Pulse v2 already exists; pass --replace to regenerate explicitly.")
    for folder in (data, data / "prds", data / "release-notes", evals):
        folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    scenario_ids = list(SCENARIOS)
    feedback: list[dict] = []
    annotations: list[dict] = []
    seen_text: set[str] = set()
    for i in range(400):
        sid = scenario_ids[i % len(scenario_ids)]
        scenario = SCENARIOS[sid]
        start = max(START, datetime.fromisoformat(scenario["onset"] + "T09:00:00+00:00"))
        stop = min(END, datetime.fromisoformat(scenario["end"] + "T18:00:00+00:00")) if scenario["end"] else END
        moment = start + timedelta(seconds=rng.randrange(max(1, int((stop - start).total_seconds()))))
        segment = rng.choice(scenario["segments"])
        day = moment.date().isoformat()
        options = _eligible_lines(scenario, day)
        line = options[(i // len(scenario_ids) + rng.randrange(len(options))) % len(options)]
        style = rng.choice(("brief", "context", "followup", "informal", "detailed"))
        if style == "context":
            line = f"{rng.choice(CONTEXT)} {line}"
        elif style == "followup":
            line = f"Following up on our earlier note: {line} {rng.choice(CONTEXT)}"
        elif style == "informal":
            line = line.replace("I cannot", "I can't").replace("We are", "We're")
        elif style == "detailed":
            line = f"{line} {rng.choice(CONTEXT)}"
        issue_ids = [sid]
        if i % 11 == 0:
            other = rng.choice([key for key in scenario_ids if key != sid and SCENARIOS[key]["onset"] <= day
                                and (SCENARIOS[key]["end"] is None or day <= SCENARIOS[key]["end"])])
            other_line = rng.choice(_eligible_lines(SCENARIOS[other], day))
            line += " Also: " + other_line
            issue_ids.append(other)
        if i % 13 == 0:
            line = rng.choice(AMBIGUOUS)
            issue_ids = []
        if i % 61 == 0 and i >= len(scenario_ids):
            earlier = i - len(scenario_ids)
            line = feedback[earlier]["feedback_text"]  # intentional repeat of same scenario
            issue_ids = annotations[earlier]["issue_ids"][:]
        elif line in seen_text:
            # A recurring issue can recur in different contexts, but independent
            # messages should not all be carbon copies of the same sentence.
            for detail in rng.sample(CONTEXT, len(CONTEXT)):
                candidate = f"{line} {detail}"
                if candidate not in seen_text:
                    line = candidate
                    break
        seen_text.add(line)
        category = "Unclear" if not issue_ids else "Multiple issues" if len(issue_ids) > 1 else scenario["category"]
        rid = f"V2-FB-{i+1:04d}"
        area = scenario["area"]
        if sid in {"INVITE_LOOP", "TEMPLATE_FIND"} and i % 4 == 0:
            area = "Collaboration" if sid == "INVITE_LOOP" else "Onboarding"
        positive_cues = ("finally", "stable again", "a relief", "works well", "recovered", "looks right",
                         "fixed it", "got back in", "went from an hour", "easier now")
        sentiment = "Mixed" if not issue_ids or len(issue_ids) > 1 else "Positive" if any(cue in line.lower() for cue in positive_cues) else "Negative"
        record = {"id": rid, "timestamp": moment.isoformat(), "customer_segment": segment,
                  "subscription_tier": TIERS[segment], "product_area": area,
                  "feedback_channel": rng.choice(("In-app", "Email", "Survey", "Interview", "Community")),
                  "feedback_text": line, "sentiment": sentiment,
                  "issue_category": category, "related_feature": scenario["feature"] if issue_ids else "unspecified"}
        feedback.append(record)
        annotations.append({"source_id": rid, "issue_ids": issue_ids, "ambiguous": not issue_ids,
                            "multi_issue": len(issue_ids) > 1, "style": style, "context_limited": not issue_ids or len(line.split()) < 12,
                            "scenario_onset": scenario["onset"], "scenario_end": scenario["end"],
                            "synthetic": True, "dataset_version": "v2"})
    tickets: list[dict] = []
    for i in range(120):
        parent_index = (i * 17 + 9) % len(feedback)
        parent = feedback[parent_index]
        note = rng.choice(SUPPORT_REPLY)
        timestamp = datetime.fromisoformat(parent["timestamp"]) + timedelta(hours=2 + i % 72)
        rid = f"V2-SUP-{i+1:04d}"
        description = f"Customer: {parent['feedback_text']}\n\n{note}"
        if i % 3 == 0:
            description += "\n\nCustomer follow-up: We checked another browser and a second teammate; the results were not identical."
        if i % 7 == 0:
            description += ("\n\nSupport follow-up: We compared the workspace setting with a smaller test account. "
                            "That difference is a clue, not a confirmed cause. Could you share the time of the next occurrence?"
                            "\n\nCustomer: We'll ask the team to repeat the workflow tomorrow. "
                            "For now, the workaround helps one person but hasn't resolved it for everyone."
                            "\n\nSupport: Leaving this open until we have a repeatable example and can check the event logs.")
        resolved = parent["sentiment"] == "Positive" and i % 7 != 0
        if resolved:
            description += "\n\nSupport: Customer confirmed the immediate problem cleared. Closing this case; later reports will be reviewed separately."
        tickets.append({"id": rid, "timestamp": timestamp.isoformat(), "customer_segment": parent["customer_segment"],
                        "subscription_tier": parent["subscription_tier"], "product_area": parent["product_area"],
                        "subject": f"Customer request {i+1:03d}: {parent['feedback_text'].split('.')[0][:55]}",
                        "description": description, "severity": "High" if parent["customer_segment"] == "Enterprise" and parent["sentiment"] == "Negative" else "Medium",
                        "issue_category": parent["issue_category"], "related_feature": parent["related_feature"],
                        "status": "Resolved" if resolved else rng.choice(("Open", "Investigating"))})
        ann = annotations[parent_index]
        annotations.append({"source_id": rid, "issue_ids": ann["issue_ids"], "ambiguous": ann["ambiguous"],
                            "multi_issue": ann["multi_issue"], "style": "support_conversation", "context_limited": ann["context_limited"],
                            "related_source_id": parent["id"], "scenario_onset": ann["scenario_onset"],
                            "scenario_end": ann["scenario_end"], "synthetic": True, "dataset_version": "v2"})
    _write_jsonl(data / "feedback.jsonl", feedback)
    _write_jsonl(data / "support-tickets.jsonl", tickets)
    for index, (title, area, body) in enumerate(PRDS, 1):
        (data / "prds" / f"prd-{index:02d}.md").write_text(f"# Pulse PRD {index:02d}: {title.title()}\n\n> SYNTHETIC DATA — fictional Pulse product.\n\nPublished: 2025-01-{index+7:02d}\nProduct area: {area}\n\n## Problem and scope\n{body}\n", encoding="utf-8")
    for index, (published, title, area, body) in enumerate(RELEASES, 1):
        (data / "release-notes" / f"release-{index:02d}.md").write_text(f"# Pulse release {index:02d}: {title}\n\n> SYNTHETIC DATA — fictional Pulse product.\n\nPublished: {published}\nProduct area: {area}\n\n## Changes and limits\n{body}\n", encoding="utf-8")
    for index in range(6):
        annotations.append({"source_id": f"prd-{index+1:02d}", "issue_ids": [], "document_kind": "prd", "synthetic": True, "dataset_version": "v2"})
    for index in range(8):
        annotations.append({"source_id": f"release-{index+1:02d}", "issue_ids": [], "document_kind": "release_note", "synthetic": True, "dataset_version": "v2"})
    _write_jsonl(evals / "source_annotations.jsonl", annotations)
    try:
        from .build_v2_benchmark import build_benchmark
    except ImportError:  # direct script invocation
        from build_v2_benchmark import build_benchmark
    build_benchmark(evals, annotations, feedback)
    (data / "README.md").write_text("# Synthetic Pulse v2\n\nAll content is fictional. Hidden issue annotations and benchmark answers live in `evals/v2/` and must never be ingested. Generated with `python backend/scripts/generate_v2.py --replace`.\n", encoding="utf-8")
    return {"feedback": len(feedback), "tickets": len(tickets), "prds": len(PRDS), "release_notes": len(RELEASES), "annotations": len(annotations)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(json.dumps(generate(replace=args.replace), indent=2))
