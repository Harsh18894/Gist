"""Generate deterministic, wholly synthetic Pulse source data and benchmark."""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
EVALS = ROOT / "evals"
SEED = 4172025

SEGMENTS = ["Individual", "SMB", "Mid-market", "Enterprise"]
AREAS = ["Onboarding", "Dashboard", "Integrations", "Billing", "Notifications", "Collaboration"]
THEMES = [
    ("Verification friction", "Onboarding", "workspace verification", [
        "The workspace verification step asks our invited teammates to repeat setup before joining.",
        "Verification links expire before our admin finishes onboarding the team.",
        "We completed verification quickly; the new checklist made setup clearer.",
        "I may have missed a verification email, but the invite flow still felt confusing." ]),
    ("Integration failures", "Integrations", "CRM sync", [
        "Our CRM sync disconnected after the June connector update and tasks stopped arriving.",
        "The CRM connector reports success, but the latest accounts are missing in Pulse.",
        "The connector recovered after reconnecting; sync is now reliable for our team.",
        "Not sure whether the missing tasks came from Pulse or our CRM permissions." ]),
    ("Notification overload", "Notifications", "notification digest", [
        "The April digest change sends too many separate alerts across shared projects.",
        "Our team needs per-project notification controls; daily digest still floods inboxes.",
        "The new digest helps me keep up without opening Pulse all day.",
        "Alerts seem duplicated, though two projects might have the same task name." ]),
    ("Slow performance", "Dashboard", "portfolio dashboard", [
        "The portfolio dashboard takes several seconds to load for our large workspace.",
        "Switching dashboard filters stalls during our weekly review.",
        "Dashboard speed has improved for my smaller workspace this month.",
        "The dashboard felt slow once, but my connection may have caused it." ]),
    ("Billing confusion", "Billing", "seat billing", [
        "The invoice does not explain why archived collaborators count toward seats.",
        "I cannot reconcile the seat adjustment with the billing page total.",
        "The updated invoice breakdown made our renewal much easier to review.",
        "I might be comparing last month's seats with this month's invoice." ]),
    ("Feature discoverability", "Collaboration", "shared templates", [
        "We found shared templates only after support pointed us to the workspace menu.",
        "It is hard to discover collaboration templates during project setup.",
        "The template gallery makes collaboration easier to start.",
        "I expected templates on the dashboard, though they may already be in the sidebar." ]),
]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def generate() -> None:
    DATA.mkdir(exist_ok=True)
    (DATA / "prds").mkdir(exist_ok=True)
    (DATA / "release-notes").mkdir(exist_ok=True)
    EVALS.mkdir(exist_ok=True)
    rng = random.Random(SEED)
    start = datetime(2025, 1, 5, 9, 0, tzinfo=timezone.utc)
    feedback: list[dict] = []
    for i in range(400):
        day = (i * 343) // 400
        moment = start + timedelta(days=day, hours=rng.randrange(12), minutes=rng.randrange(60))
        weights = [14, 16, 15, 17, 14, 15]
        if moment.month >= 4:
            weights[2] += 11
        if moment.month >= 6:
            weights[1] += 13
        theme_index = rng.choices(range(6), weights=weights)[0]
        category, area, feature, examples = THEMES[theme_index]
        segment = rng.choices(SEGMENTS, weights=[17, 29, 28, 26])[0]
        if category in ("Integration failures", "Slow performance") and rng.random() < .46:
            segment = "Enterprise"
        tone = rng.choices([0, 1, 2, 3], weights=[35, 40, 15, 10])[0]
        if theme_index == 2 and moment.date().isoformat() < "2025-04-05" and tone == 0:
            tone = 1
        if theme_index == 1 and moment.date().isoformat() < "2025-06-05" and tone == 0:
            tone = 1
        positive_release_dates = {0: "2025-02-05", 2: "2025-04-05", 4: "2025-05-05", 5: "2025-07-05"}
        if tone == 2 and theme_index in positive_release_dates and moment.date().isoformat() < positive_release_dates[theme_index]:
            tone = 1
        text = examples[tone]
        if category == "Notification overload" and tone < 2 and rng.random() < .23:
            area = "Collaboration"  # the same issue crosses product areas
        if category == "Feature discoverability" and tone < 2 and rng.random() < .18:
            area = "Onboarding"
        feedback.append({
            "id": f"FB-{i+1:04d}", "timestamp": moment.isoformat(),
            "customer_segment": segment,
            "subscription_tier": {"Individual": "Starter", "SMB": "Team", "Mid-market": "Business", "Enterprise": "Enterprise"}[segment],
            "product_area": area, "feedback_channel": rng.choice(["In-app", "Email", "Survey", "Interview", "Community"]),
            "feedback_text": text, "sentiment": "Positive" if tone == 2 else "Mixed" if tone == 3 else "Negative",
            "issue_category": category, "related_feature": feature,
        })
    tickets: list[dict] = []
    for i in range(120):
        source = feedback[(i * 3 + 7) % len(feedback)]
        moment = datetime.fromisoformat(source["timestamp"]) + timedelta(hours=4 + i % 28)
        tickets.append({
            "id": f"SUP-{i+1:04d}", "timestamp": moment.isoformat(),
            "customer_segment": source["customer_segment"], "subscription_tier": source["subscription_tier"],
            "product_area": source["product_area"], "subject": f"Help with {source['related_feature']}",
            "description": source["feedback_text"],
            "severity": "High" if source["customer_segment"] == "Enterprise" and source["sentiment"] == "Negative" else "Medium" if source["sentiment"] == "Negative" else "Low",
            "issue_category": source["issue_category"], "related_feature": source["related_feature"],
            "status": rng.choice(["Open", "Investigating", "Resolved"]),
        })
    write_jsonl(DATA / "feedback.jsonl", feedback)
    write_jsonl(DATA / "support-tickets.jsonl", tickets)
    for index, (category, area, feature, _) in enumerate(THEMES, 1):
        (DATA / "prds" / f"prd-{index:02d}.md").write_text(
            f"# Pulse PRD {index:02d}: {feature.title()}\n\n> SYNTHETIC DATA — fictional Pulse product.\n\n"
            f"Published: 2025-01-{index+7:02d}\nProduct area: {area}\nIssue category: {category}\n\n"
            f"## Problem\nCustomers need a clearer, more reliable {feature} experience.\n\n"
            f"## Initial scope\nImprove {feature} visibility, recovery guidance, and admin controls.\n\n"
            "## Success signal\nFewer related support tickets and clearer customer feedback after release.\n",
            encoding="utf-8")
    releases = [
        ("2025-02-05", "Workspace verification checklist", "Onboarding", "The checklist explains verification steps before invitations are sent."),
        ("2025-03-05", "Portfolio dashboard filters", "Dashboard", "New filters let admins review work across projects."),
        ("2025-04-05", "Notification digest update", "Notifications", "The digest groups project events, but defaults are enabled for all shared projects."),
        ("2025-05-05", "Seat invoice breakdown", "Billing", "Invoices show a line item for seat adjustments."),
        ("2025-06-05", "CRM connector refresh", "Integrations", "The connector refresh changes the reconnect flow and sync status display."),
        ("2025-07-05", "Shared template gallery", "Collaboration", "Templates are available from the workspace menu."),
        ("2025-08-05", "Dashboard loading update", "Dashboard", "Large workspace dashboard requests use a faster aggregation path."),
        ("2025-09-05", "Notification project controls", "Notifications", "Admins can tune notifications by project."),
    ]
    for index, (date, title, area, detail) in enumerate(releases, 1):
        (DATA / "release-notes" / f"release-{index:02d}.md").write_text(
            f"# Pulse release {index:02d}: {title}\n\n> SYNTHETIC DATA — fictional Pulse product.\n\n"
            f"Published: {date}\nProduct area: {area}\n\n## Changes\n{detail}\n",
            encoding="utf-8")
    benchmarks: list[dict] = []
    for index, (date, title, area, _) in enumerate(releases, 1):
        benchmarks.append({"id": f"Q-{len(benchmarks)+1:02d}", "dataset_version": "v1", "question": f"What did Pulse release on {date}?", "expected_answer": title, "source_ids": [f"release-{index:02d}"]})
    for index, (category, area, feature, _) in enumerate(THEMES, 1):
        benchmarks.append({"id": f"Q-{len(benchmarks)+1:02d}", "dataset_version": "v1", "question": f"Which product area owns the {feature} PRD?", "expected_answer": area, "source_ids": [f"prd-{index:02d}"]})
        benchmarks.append({"id": f"Q-{len(benchmarks)+1:02d}", "dataset_version": "v1", "question": f"What issue category does the {feature} PRD address?", "expected_answer": category, "source_ids": [f"prd-{index:02d}"]})
    (EVALS / "questions.json").write_text(json.dumps({"synthetic": True, "dataset_version": "v1", "questions": benchmarks}, indent=2) + "\n", encoding="utf-8")
    (DATA / "README.md").write_text("# Synthetic Pulse data\n\nAll records and documents in this directory are generated fiction for Gist. No real customer data is included. Run `python backend/scripts/generate_data.py` to regenerate deterministically.\n", encoding="utf-8")


if __name__ == "__main__":
    generate()
