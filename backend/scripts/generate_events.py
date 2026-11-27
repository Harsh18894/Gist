"""Generate the fictional Pulse product-events dataset (events-v1). Fixed seed; no network or AI calls.

The timeline and release dates match Pulse v2. Planted effects follow the v2 scenario model;
decoys (a sign-up mix shift, a tracking outage, a holiday dip) test whether an investigation
blames the wrong thing. The answer key is written to evals/phase4/, never into the database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261127
VERSION = "events-v1"
DEFAULT_DB = ROOT / "backend" / "gist-events-v1.sqlite3"
ANSWER_KEY = ROOT / "evals" / "phase4" / "events-answer-key.json"
START = datetime(2025, 1, 8, 9)
END = datetime(2025, 12, 15, 18)
ACCOUNT_CREATION_END = datetime(2025, 12, 1)
SEGMENTS = ("Individual", "SMB", "Mid-market", "Enterprise")
SEGMENT_WEIGHTS = (0.25, 0.30, 0.28, 0.17)
TIERS = dict(zip(SEGMENTS, ("Starter", "Team", "Business", "Enterprise")))
TEAM_SIZE = {"Individual": (1, 1), "SMB": (2, 6), "Mid-market": (4, 12), "Enterprise": (6, 18)}
RELEASES = [  # identical to Pulse v2 release notes (tested)
    ("release-01", "2025-02-05", "Workspace verification checklist"), ("release-02", "2025-03-05", "Portfolio filters"),
    ("release-03", "2025-04-05", "Project digest update"), ("release-04", "2025-05-05", "Invoice breakdown"),
    ("release-05", "2025-06-05", "CRM connector refresh"), ("release-06", "2025-07-05", "Shared template gallery"),
    ("release-07", "2025-08-05", "Portfolio loading update"), ("release-08", "2025-09-05", "Per-project notification controls"),
]
STEPS = ("profile_completed", "workspace_joined", "first_project_viewed", "first_task_created")

# ---- Planted effects and decoys (authoring data; mirrored in the answer key, never stored in the database)
INVITE_LOOP_START = datetime(2025, 2, 6)
CRM_WINDOW = (datetime(2025, 6, 6), datetime(2025, 10, 10, 23, 59))
ALERT_DELAY_START = datetime(2025, 9, 6)
DASH_FIX = datetime(2025, 8, 5)
DIGEST_WINDOW = (datetime(2025, 4, 6), datetime(2025, 9, 5, 23, 59))
TEMPLATE_START = datetime(2025, 7, 6)
CAMPAIGN = (datetime(2025, 10, 13), datetime(2025, 11, 9, 23, 59))
OUTAGE_DAYS = {date(2025, 11, 18), date(2025, 11, 19)}
HOLIDAY_DAYS = {date(2025, 11, 27), date(2025, 11, 28)}
BASE_ACCOUNTS, CAMPAIGN_ACCOUNTS = 600, 200
ACCEPT = (0.88, 0.62)                       # invitation acceptance: before / after the invite loop (team accounts)
OWNER_ACTIVATION = {"Individual": 0.35, "SMB": 0.74, "Mid-market": 0.76, "Enterprise": 0.78}
MEMBER_ACTIVATION = (0.72, 0.58)            # invited admins/members: before / after the invite loop
VIEWER_ACTIVATION = 0.40
CRM_FAILURE = (0.02, 0.18)
OUTAGE_LOSS = 0.85


def _fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _workday_time(rng: random.Random, day: datetime) -> datetime:
    return day.replace(hour=0, minute=0, second=0) + timedelta(hours=rng.uniform(7.5, 19.5))


def _random_time(rng: random.Random, start: datetime, end: datetime) -> datetime:
    """Uniform over the window, re-drawn to favour weekdays and thin the holiday days."""
    while True:
        t = start + timedelta(seconds=rng.uniform(0, (end - start).total_seconds()))
        keep = (0.35 if t.weekday() >= 5 else 1.0) * (0.45 if t.date() in HOLIDAY_DAYS else 1.0)
        if rng.random() < keep:
            return t


def _lognormal(rng: random.Random, median: float, sigma: float) -> float:
    return round(math.exp(rng.gauss(math.log(median), sigma)), 1)


def build(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    accounts, users, events = [], [], []

    def event(t: datetime, user: str | None, account: str, name: str, step=None, target=None, value=None, status=None):
        if START <= t <= END:
            events.append([t, user, account, name, step, target, value, status])

    specs = [(rng.choices(SEGMENTS, SEGMENT_WEIGHTS)[0], _random_time(rng, START, ACCOUNT_CREATION_END), None)
             for _ in range(BASE_ACCOUNTS)]
    specs += [("Individual", _random_time(rng, *CAMPAIGN), "paid_campaign") for _ in range(CAMPAIGN_ACCOUNTS)]
    specs.sort(key=lambda s: s[1])
    for n, (segment, created, forced_channel) in enumerate(specs, 1):
        aid = f"ACC-{n:04d}"
        team = segment != "Individual"
        channel = forced_channel or ("sales" if segment in ("Mid-market", "Enterprise") and rng.random() < 0.5
                                     else rng.choices(("organic", "partner"), (0.8, 0.2))[0])
        crm = team and rng.random() < {"SMB": 0.3, "Mid-market": 0.5, "Enterprise": 0.6}[segment]
        large = segment == "Enterprise" and rng.random() < 0.6 or segment == "Mid-market" and rng.random() < 0.25
        restricted = team and rng.random() < (0.2 if segment == "SMB" else 0.4)
        mutes = team and rng.random() < 0.4
        accounts.append((aid, segment, TIERS[segment], _fmt(created), channel, int(crm), int(large), int(restricted)))
        size = rng.randint(*TEAM_SIZE[segment])
        members = []
        for i in range(size):
            uid = f"{aid}-U{i + 1:02d}"
            if i == 0:
                role, invited, inviter = "owner", None, None
                signup = created
            else:
                role = rng.choices(("admin", "member", "viewer"), (0.1, 0.7, 0.2))[0]
                invited = created + timedelta(days=rng.expovariate(1 / 20))
                if invited > END:
                    continue
                event(invited, members[0], aid, "invite_sent", target=uid)   # the owner invites (signed up at creation)
                loop = invited >= INVITE_LOOP_START
                if rng.random() < ACCEPT[loop]:
                    signup = invited + timedelta(hours=rng.expovariate(1 / (40 if loop else 18)))
                    if signup.date() in HOLIDAY_DAYS and rng.random() < 0.55:
                        signup += timedelta(days=4)
                    for _ in range(rng.randint(1, 2) if loop else 0):   # repeated checks happen before acceptance
                        event(invited + (signup - invited) * rng.uniform(0.1, 0.9), uid, aid, "invite_verification_repeated")
                    event(signup, uid, aid, "invite_accepted")
                else:
                    signup = None
            if signup is not None and signup > END:
                signup = None
            users.append((uid, aid, role, _fmt(invited) if invited else None, _fmt(signup) if signup else None,
                          channel if role == "owner" else "invite"))
            members.append(uid)
            if signup is None:
                continue
            event(signup + timedelta(minutes=2), uid, aid, "signup_completed")
            if role == "owner":
                p = OWNER_ACTIVATION[segment]
            elif role == "viewer":
                p = VIEWER_ACTIVATION
            else:
                p = MEMBER_ACTIVATION[team and invited is not None and invited >= INVITE_LOOP_START]
            activated = rng.random() < p
            reached = len(STEPS) if activated else rng.randint(0, len(STEPS) - 1)
            t = signup
            for step in STEPS[:reached]:
                t += timedelta(hours=rng.uniform(0.2, 30) if step == "first_task_created" else rng.uniform(0.05, 6))
                event(min(t, signup + timedelta(days=6, hours=20)), uid, aid, "onboarding_step_completed", step=step)
            # Weekly usage after sign-up
            week = signup + timedelta(days=7)
            while week < END:
                if rng.random() < (0.72 if activated else 0.12):
                    for _ in range(rng.randint(1, 3)):
                        event(_random_time(rng, week, min(week + timedelta(days=7), END)), uid, aid, "session_started")
                    if rng.random() < (0.7 if team else 0.4):
                        t = _random_time(rng, week, min(week + timedelta(days=7), END))
                        median = (9000 if t < DASH_FIX else 3200) if large else 1200
                        event(t, uid, aid, "dashboard_viewed", value=_lognormal(rng, median, 0.35))
                    if team:
                        in_window = DIGEST_WINDOW[0] <= week <= DIGEST_WINDOW[1]
                        event(_random_time(rng, week, min(week + timedelta(days=7), END)), uid, aid, "digest_emails_sent",
                              value=float(max(0, round(rng.gauss(7 if in_window else 2, 1.2)))))
                    if week >= TEMPLATE_START and rng.random() < 0.18:
                        t = _random_time(rng, week, min(week + timedelta(days=7), END))
                        if restricted and role in ("member", "viewer") and rng.random() < 0.5:
                            event(t, uid, aid, "template_duplicate_denied")
                        else:
                            event(t, uid, aid, "template_used")
                week += timedelta(days=7)
        # Account-level activity: CRM sync runs and critical alerts
        day = created + timedelta(days=1)
        while team and day < END:
            if crm:
                for _ in range(3):
                    t = _random_time(rng, day, min(day + timedelta(days=7), END))
                    failed = rng.random() < CRM_FAILURE[CRM_WINDOW[0] <= t <= CRM_WINDOW[1]]
                    event(t, None, aid, "crm_sync_run", status="failed" if failed else "success",
                          value=float(rng.randint(5, 200) if failed else 0))
            for _ in range(rng.choice((0, 1, 1, 2, 2, 3))):
                t = _random_time(rng, day, min(day + timedelta(days=7), END))
                delayed = mutes and t >= ALERT_DELAY_START
                event(t, None, aid, "critical_alert_delivered", value=_lognormal(rng, 120 if delayed else 1.2, 0.5))
            if mutes and day <= datetime(2025, 9, 5) < day + timedelta(days=7):
                event(datetime(2025, 9, 8, 10), members[0], aid, "notification_settings_changed")
            day += timedelta(days=7)

    # Tracking outage decoy: most events on these days are never recorded.
    events = [e for e in events if not (e[0].date() in OUTAGE_DAYS and rng.random() < OUTAGE_LOSS)]
    events.sort(key=lambda e: (e[0], e[2], e[1] or "", e[3]))
    rows = [(i + 1, _fmt(e[0]), *e[1:]) for i, e in enumerate(events)]
    return {"accounts": accounts, "users": users, "events": rows}


SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE releases (id TEXT PRIMARY KEY, released_on TEXT NOT NULL, title TEXT NOT NULL);
CREATE TABLE accounts (id TEXT PRIMARY KEY, segment TEXT NOT NULL, tier TEXT NOT NULL, created_at TEXT NOT NULL,
  channel TEXT NOT NULL, crm_connected INTEGER NOT NULL, large_workspace INTEGER NOT NULL, template_restricted INTEGER NOT NULL);
CREATE TABLE users (id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), role TEXT NOT NULL,
  invited_at TEXT, signup_at TEXT, channel TEXT NOT NULL);
CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, user_id TEXT REFERENCES users(id),
  account_id TEXT NOT NULL REFERENCES accounts(id), name TEXT NOT NULL, step TEXT, target_user_id TEXT, value REAL, status TEXT);
CREATE INDEX idx_events_name_ts ON events(name, ts);
CREATE INDEX idx_events_user ON events(user_id);
CREATE INDEX idx_events_target ON events(target_user_id);
"""


def content_hash(data: dict) -> str:
    digest = hashlib.sha256()
    for table in ("accounts", "users", "events"):
        for row in data[table]:
            digest.update(json.dumps(row, separators=(",", ":")).encode())
    return digest.hexdigest()


def write(path: Path, replace: bool = False, seed: int = SEED) -> dict:
    if path.exists():
        if not replace:
            raise FileExistsError(f"{path} exists; pass --replace to rebuild it.")
        path.unlink()
    data = build(seed)
    digest = content_hash(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO releases VALUES (?,?,?)", RELEASES)
        db.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", data["accounts"])
        db.executemany("INSERT INTO users VALUES (?,?,?,?,?,?)", data["users"])
        db.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)", data["events"])
        meta = {"version": VERSION, "seed": str(seed), "content_sha256": digest, "timezone": "UTC",
                "start": _fmt(START), "end": _fmt(END), "synthetic": "true",
                "accounts": str(len(data["accounts"])), "users": str(len(data["users"])), "events": str(len(data["events"]))}
        db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    return meta


ANSWER = {
    "dataset": VERSION, "seed": SEED,
    "note": "Authoring answer key for scoring Phase 4 investigations. Never index it or load it into the events database.",
    "planted": [
        {"id": "INVITE_LOOP", "metric": "invite_acceptance_rate", "start": "2025-02-06", "end": None, "scope": "team accounts (SMB, Mid-market, Enterprise)",
         "design": {"before": ACCEPT[0], "after": ACCEPT[1]}, "also": "invited admin/member activation 0.72 -> 0.58; repeated verification events",
         "related_release": "release-01", "v2_feedback_issue": "INVITE_LOOP"},
        {"id": "CRM_SYNC", "metric": "crm_sync_failure_rate", "start": "2025-06-06", "end": "2025-10-10", "scope": "CRM-connected team accounts",
         "design": {"before": CRM_FAILURE[0], "during": CRM_FAILURE[1], "after": CRM_FAILURE[0]}, "related_release": "release-05", "v2_feedback_issue": "CRM_SYNC"},
        {"id": "ALERT_DELAY", "metric": "alert_delayed_share (median hides it: only ~40% of accounts affected)", "start": "2025-09-06", "end": None,
         "scope": "team accounts that changed notification settings (~40%)", "design": {"median_minutes_before": 1.2, "median_minutes_after_affected": 120},
         "related_release": "release-08", "v2_feedback_issue": "ALERT_DELAY"},
        {"id": "DASH_SLOW_FIXED", "metric": "dashboard_load_p50_ms by workspace_size (overall median hides it)", "start": "2025-01-08", "end": "2025-08-05", "scope": "large workspaces",
         "design": {"median_ms_large_before": 9000, "median_ms_large_after": 3200, "median_ms_other": 1200}, "related_release": "release-07", "v2_feedback_issue": "DASH_SLOW"},
        {"id": "DIGEST_NOISE", "metric": "digest_emails_per_user_week", "start": "2025-04-06", "end": "2025-09-05", "scope": "team accounts",
         "design": {"before": 2, "during": 7, "after": 2}, "related_release": "release-03 (fixed by release-08)", "v2_feedback_issue": "DIGEST_NOISE"},
        {"id": "TEMPLATES", "metric": "template_uses / template_duplicate_denials", "start": "2025-07-06", "end": None,
         "scope": "all; denials for members/viewers in template-restricted accounts", "related_release": "release-06",
         "v2_feedback_issue": "TEMPLATE_FIND / TEMPLATE_ACCESS"},
    ],
    "decoys": [
        {"id": "SIGNUP_MIX_SHIFT", "start": "2025-10-13", "end": "2025-11-09",
         "design": f"{CAMPAIGN_ACCOUNTS} extra Individual accounts from a paid campaign with the same activation as other Individual accounts",
         "expected_reading": "overall activation falls because the mix shifts to the lowest-activation segment; rates within segments do not change; not a product defect"},
        {"id": "TRACKING_OUTAGE", "start": "2025-11-18", "end": "2025-11-19", "design": f"{int(OUTAGE_LOSS * 100)}% of events on these days were never recorded",
         "expected_reading": "a data-quality gap, not a behaviour change; activation for those sign-ups is under-measured"},
        {"id": "HOLIDAY_DIP", "start": "2025-11-27", "end": "2025-11-28", "design": "fewer sign-ups and sessions",
         "expected_reading": "lower volume, unchanged rates"},
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    meta = write(args.db, replace=args.replace)
    ANSWER_KEY.parent.mkdir(parents=True, exist_ok=True)
    ANSWER_KEY.write_text(json.dumps(ANSWER, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
