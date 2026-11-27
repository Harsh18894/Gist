"""Read-only analytics tools over the Pulse product-events dataset (Phase 4.1).

Every tool takes validated parameters, runs fixed parameterized SQL on a read-only
connection, and returns plain data plus the exact definition used. There is no free-form
SQL: an investigation planner can only choose a metric from METRICS and its parameters.
"""
from __future__ import annotations

import contextvars
import os
import re
import sqlite3
import statistics
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

from ..config import ROOT
from ..errors import DatasetStateError, InvalidRequest

DATA_START, DATA_END = date(2025, 1, 8), date(2025, 12, 15)
GRAINS = ("week", "month")
DIMENSIONS = {"segment": "a.segment", "channel": "u.channel", "role": "u.role",
              "workspace_size": "CASE a.large_workspace WHEN 1 THEN 'large' ELSE 'standard' END"}
ALERT_DELAY_MINUTES = 15
MAX_BUCKETS = 60
ACTIVATION_DAYS = 7
INVITE_DAYS = 14


def events_db_path() -> Path:
    value = os.getenv("GIST_EVENTS_DB_PATH")
    if not value:
        return ROOT / "backend" / "gist-events-v1.sqlite3"
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


# Set by the executor: a monotonic deadline after which any running query is interrupted.
DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar("tool_deadline", default=None)


def _guard(db: sqlite3.Connection) -> None:
    deadline = DEADLINE.get()
    if deadline is not None:
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 5_000)


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Read-only connection: opened with mode=ro and query_only, so any write raises."""
    target = path or events_db_path()
    if not target.exists():
        raise DatasetStateError(f"{target} not found", code="events_missing",
                                public_message="The product-events dataset is missing. Run backend/scripts/generate_events.py.")
    db = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    db.execute("PRAGMA query_only = ON")
    _guard(db)
    try:
        yield db
    finally:
        db.close()


# Each metric: (unit, kind, definition, event-time column or cohort rule). Kinds: rate | count | median | mean.
METRICS = {
    "signups": ("users", "count", "Users who completed sign-up (signup_completed), by sign-up date."),
    "activation_rate": ("share", "rate", f"Of users who signed up in the bucket, the share who completed the onboarding step "
                        f"'first_task_created' within {ACTIVATION_DAYS} days of sign-up."),
    "invite_acceptance_rate": ("share", "rate", f"Of invitations sent in the bucket, the share accepted within {INVITE_DAYS} days."),
    "weekly_active_users": ("users", "count", "Distinct users with at least one session_started in the bucket."),
    "crm_sync_failure_rate": ("share", "rate", "Share of CRM sync runs with status 'failed', by run date."),
    "alert_delay_p50_minutes": ("minutes", "median", "Median minutes from a critical alert being raised to its delivery."),
    "alert_delayed_share": ("share", "rate", f"Share of critical alerts delivered more than {ALERT_DELAY_MINUTES} minutes after being raised."),
    "dashboard_load_p50_ms": ("milliseconds", "median", "Median portfolio dashboard load time per view."),
    "digest_emails_per_user_week": ("emails", "mean", "Mean digest emails per active team user per week."),
    "template_uses": ("uses", "count", "Times a shared template was used."),
    "template_duplicate_denials": ("events", "count", "Times duplicating a template was blocked by permissions."),
    "event_volume": ("events", "count", "All recorded events (useful for spotting tracking gaps)."),
}
SIMPLE_EVENTS = {"crm_sync_failure_rate": "crm_sync_run", "alert_delay_p50_minutes": "critical_alert_delivered",
                 "alert_delayed_share": "critical_alert_delivered",
                 "dashboard_load_p50_ms": "dashboard_viewed", "digest_emails_per_user_week": "digest_emails_sent",
                 "template_uses": "template_used", "template_duplicate_denials": "template_duplicate_denied",
                 "weekly_active_users": "session_started"}


def _day(value: str | None, default: date, name: str) -> date:
    if value is None:
        return default
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest(f"bad {name}", public_message=f"{name} must be a date like 2025-03-01.") from exc
    if not DATA_START - timedelta(days=31) <= parsed <= DATA_END + timedelta(days=31):
        raise InvalidRequest(f"{name} out of range", public_message=f"{name} must be within the data range (2025-01-08 to 2025-12-15).")
    return parsed


def _bucket(day: date, grain: str) -> str:
    return (day - timedelta(days=day.weekday())).isoformat() if grain == "week" else day.isoformat()[:7]


def _validate(metric: str, grain: str, by: str | None, start: str | None, end: str | None) -> tuple[date, date]:
    if metric not in METRICS:
        raise InvalidRequest("unknown metric", public_message="Unknown metric. Choose one of: " + ", ".join(METRICS) + ".")
    if grain not in GRAINS:
        raise InvalidRequest("bad grain", public_message="Grain must be week or month.")
    if by is not None and by not in DIMENSIONS:
        raise InvalidRequest("bad dimension", public_message="Break down by " + ", ".join(DIMENSIONS) + ".")
    if by == "role" and metric in ("crm_sync_failure_rate", "alert_delay_p50_minutes", "alert_delayed_share"):
        raise InvalidRequest("role n/a", public_message="That metric is recorded per account, so it has no user role.")
    lo, hi = _day(start, DATA_START, "from_date"), _day(end, DATA_END, "to_date")
    if lo > hi:
        raise InvalidRequest("reversed range", public_message="from_date must be on or before to_date.")
    return lo, hi


def _rows(db: sqlite3.Connection, metric: str, by: str | None, lo: date, hi: date) -> list[tuple]:
    """(day, group, numerator_or_value, denominator_flag) rows for one metric. All SQL is fixed and parameterized."""
    group = DIMENSIONS[by] if by else "'all'"
    window = (lo.isoformat(), (hi + timedelta(days=1)).isoformat())
    if metric in ("signups", "activation_rate"):
        # Pre-aggregate first-task times per user (one pass), instead of a correlated scan per sign-up.
        return db.execute(f"""
            WITH first_task AS (SELECT user_id, MIN(ts) AS ts FROM events
                                WHERE name = 'onboarding_step_completed' AND step = 'first_task_created' GROUP BY user_id)
            SELECT substr(s.ts,1,10), {group}, COALESCE(f.ts <= datetime(s.ts, '+{ACTIVATION_DAYS} days'), 0)
            FROM events s JOIN users u ON u.id = s.user_id JOIN accounts a ON a.id = s.account_id
            LEFT JOIN first_task f ON f.user_id = s.user_id
            WHERE s.name = 'signup_completed' AND s.ts >= ? AND s.ts < ?""", window).fetchall()
    if metric == "invite_acceptance_rate":
        return db.execute(f"""
            WITH accepted AS (SELECT user_id, MIN(ts) AS ts FROM events WHERE name = 'invite_accepted' GROUP BY user_id)
            SELECT substr(i.ts,1,10), {group}, COALESCE(c.ts <= datetime(i.ts, '+{INVITE_DAYS} days'), 0)
            FROM events i JOIN users u ON u.id = i.target_user_id JOIN accounts a ON a.id = i.account_id
            LEFT JOIN accepted c ON c.user_id = i.target_user_id
            WHERE i.name = 'invite_sent' AND i.ts >= ? AND i.ts < ?""", window).fetchall()
    if metric == "event_volume":
        return db.execute(f"""SELECT substr(e.ts,1,10), {group}, 1 FROM events e JOIN accounts a ON a.id = e.account_id
            LEFT JOIN users u ON u.id = e.user_id WHERE e.ts >= ? AND e.ts < ?""", window).fetchall()
    name = SIMPLE_EVENTS[metric]
    value = {"crm_sync_failure_rate": "e.status = 'failed'", "weekly_active_users": "e.user_id",
             "alert_delayed_share": f"e.value > {ALERT_DELAY_MINUTES}"}.get(metric, "e.value")
    return db.execute(f"""SELECT substr(e.ts,1,10), {group}, {value} FROM events e JOIN accounts a ON a.id = e.account_id
        LEFT JOIN users u ON u.id = e.user_id WHERE e.name = ? AND e.ts >= ? AND e.ts < ?""", (name, *window)).fetchall()


def _aggregate(metric: str, values: list) -> dict:
    kind = METRICS[metric][1]
    if not values:
        return {"value": None, "n": 0}
    if kind == "rate":
        hits = sum(1 for v in values if v)
        return {"value": round(hits / len(values), 4), "numerator": hits, "denominator": len(values), "n": len(values)}
    if metric == "weekly_active_users":
        return {"value": len(set(values)), "n": len(values)}
    if kind == "count":
        return {"value": len(values), "n": len(values)}
    numbers = [float(v) for v in values if v is not None]
    if kind == "median":
        return {"value": round(statistics.median(numbers), 2), "n": len(numbers)}
    return {"value": round(statistics.fmean(numbers), 2), "n": len(numbers)}


def metric_series(metric: str, grain: str = "week", by: str | None = None, from_date: str | None = None,
                  to_date: str | None = None, db_path: Path | None = None) -> dict:
    lo, hi = _validate(metric, grain, by, from_date, to_date)
    with connect(db_path) as db:
        rows = _rows(db, metric, by, lo, hi)
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for day, group, value in rows:
        grouped[(_bucket(date.fromisoformat(day), grain), group)].append(value)
    buckets = sorted({b for b, _ in grouped})
    if len(buckets) > MAX_BUCKETS:
        raise InvalidRequest("too many buckets", public_message=f"That range has more than {MAX_BUCKETS} buckets; use month grain or a shorter range.")
    series = [{"bucket": b, "group": g, **_aggregate(metric, grouped[(b, g)])} for (b, g) in sorted(grouped)]
    unit, kind, definition = METRICS[metric]
    note = ("Cohort metric: the last " + str(ACTIVATION_DAYS if metric == "activation_rate" else INVITE_DAYS) +
            " days are incomplete." if metric in ("activation_rate", "invite_acceptance_rate") else None)
    return {"tool": "metric_series", "metric": metric, "unit": unit, "kind": kind, "definition": definition, "grain": grain,
            "by": by, "from_date": lo.isoformat(), "to_date": hi.isoformat(), "series": series, "note": note}


def compare_periods(metric: str, a_from: str, a_to: str, b_from: str, b_to: str, by: str = "segment",
                    db_path: Path | None = None) -> dict:
    """Compare period B with baseline period A, overall and by group. For rate metrics the overall change is split
    into a mix effect (group shares changed) and a rate effect (rates within groups changed)."""
    a_lo, a_hi = _validate(metric, "month", by, a_from, a_to)
    b_lo, b_hi = _validate(metric, "month", by, b_from, b_to)
    with connect(db_path) as db:
        a_rows, b_rows = _rows(db, metric, by, a_lo, a_hi), _rows(db, metric, by, b_lo, b_hi)
    groups = sorted({r[1] for r in a_rows + b_rows})
    per = []
    for g in groups:
        a_vals, b_vals = [r[2] for r in a_rows if r[1] == g], [r[2] for r in b_rows if r[1] == g]
        per.append({"group": g, "a": _aggregate(metric, a_vals), "b": _aggregate(metric, b_vals),
                    "share_a": round(len(a_vals) / len(a_rows), 4) if a_rows else None,
                    "share_b": round(len(b_vals) / len(b_rows), 4) if b_rows else None})
    overall = {"a": _aggregate(metric, [r[2] for r in a_rows]), "b": _aggregate(metric, [r[2] for r in b_rows])}
    result = {"tool": "compare_periods", "metric": metric, "definition": METRICS[metric][2], "by": by,
              "period_a": [a_lo.isoformat(), a_hi.isoformat()], "period_b": [b_lo.isoformat(), b_hi.isoformat()],
              "overall": overall, "groups": per}
    if METRICS[metric][1] == "rate" and overall["a"]["value"] is not None and overall["b"]["value"] is not None:
        complete = [p for p in per if p["a"]["value"] is not None and p["b"]["value"] is not None]
        # Shapley-style split: each effect averaged over both orderings, so mix + rate = total (up to groups missing in a period).
        rate = sum((p["b"]["value"] - p["a"]["value"]) * (p["share_a"] + p["share_b"]) / 2 for p in complete)
        mix = sum((p["share_b"] - p["share_a"]) * (p["a"]["value"] + p["b"]["value"]) / 2 for p in complete)
        result["decomposition"] = {"total_change": round(overall["b"]["value"] - overall["a"]["value"], 4),
                                   "mix_effect": round(mix, 4), "rate_effect": round(rate, 4),
                                   "reading": "mix_effect: change from group shares shifting; rate_effect: change within groups."}
    return result


def releases(from_date: str | None = None, to_date: str | None = None, db_path: Path | None = None) -> dict:
    lo, hi = _day(from_date, DATA_START, "from_date"), _day(to_date, DATA_END, "to_date")
    with connect(db_path) as db:
        rows = db.execute("SELECT id, released_on, title FROM releases WHERE released_on BETWEEN ? AND ? ORDER BY released_on",
                          (lo.isoformat(), hi.isoformat())).fetchall()
    return {"tool": "releases", "from_date": lo.isoformat(), "to_date": hi.isoformat(),
            "releases": [{"id": r[0], "released_on": r[1], "title": r[2]} for r in rows],
            "note": "A release near a change is timing only, not evidence of cause."}


def data_quality(from_date: str | None = None, to_date: str | None = None, threshold: float = 0.5,
                 db_path: Path | None = None) -> dict:
    """Flag days whose recorded event volume is below `threshold` x the median of the same weekday over the prior 4 weeks."""
    if not 0 < threshold < 1:
        raise InvalidRequest("bad threshold", public_message="threshold must be between 0 and 1.")
    lo, hi = _day(from_date, DATA_START, "from_date"), _day(to_date, DATA_END, "to_date")
    with connect(db_path) as db:
        counts = dict(db.execute("SELECT substr(ts,1,10), COUNT(*) FROM events GROUP BY 1").fetchall())
    flagged = []
    day = max(lo, DATA_START + timedelta(days=28))
    while day <= min(hi, DATA_END):
        prior = [counts.get((day - timedelta(weeks=k)).isoformat(), 0) for k in range(1, 5)]
        expected = statistics.median(prior)
        actual = counts.get(day.isoformat(), 0)
        if expected >= 20 and actual < threshold * expected:
            flagged.append({"date": day.isoformat(), "events": actual, "expected_about": round(expected),
                            "ratio": round(actual / expected, 2)})
        day += timedelta(days=1)
    return {"tool": "data_quality", "from_date": lo.isoformat(), "to_date": hi.isoformat(), "threshold": threshold,
            "low_volume_days": flagged,
            "note": "Low-volume days may be tracking gaps or real dips (for example holidays). Check whether rates also moved."}


@contextmanager
def pulse_readonly() -> Iterator[sqlite3.Connection]:
    """Read-only connection to the selected Pulse dataset (feedback and documents). Any write raises."""
    from ..config import database_path
    target = database_path()
    if not target.exists():
        raise DatasetStateError(f"{target} not found", code="dataset_missing",
                                public_message="The Pulse dataset is not seeded. Run backend/scripts/seed.py.")
    db = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    db.execute("PRAGMA query_only = ON")
    _guard(db)
    try:
        yield db
    finally:
        db.close()


def search_feedback(terms: list[str], from_date: str, to_date: str, product_area: str | None = None, quotes: int = 3) -> dict:
    """Customer feedback mentioning any of the terms (from the selected Pulse dataset), with monthly counts."""
    if not 1 <= len(terms) <= 5:
        raise InvalidRequest("bad terms", public_message="Give 1 to 5 search words.")
    lo, hi = _day(from_date, DATA_START, "from_date"), _day(to_date, DATA_END, "to_date")
    likes = " OR ".join("feedback_text LIKE ? ESCAPE '\\'" for _ in terms)
    params: list = ["%" + t.replace("%", "\\%").replace("_", "\\_") + "%" for t in terms]
    sql = f"SELECT id, substr(timestamp,1,10), feedback_text, sentiment, customer_segment FROM feedback WHERE ({likes}) " \
          "AND substr(timestamp,1,10) BETWEEN ? AND ?"
    params += [lo.isoformat(), hi.isoformat()]
    if product_area:
        sql += " AND product_area = ?"
        params.append(product_area)
    with pulse_readonly() as db:
        rows = db.execute(sql + " ORDER BY timestamp DESC, id", params).fetchall()
        has_meta = db.execute("SELECT name FROM sqlite_master WHERE name = 'dataset_meta'").fetchone()
        version = db.execute("SELECT value FROM dataset_meta WHERE key = 'version'").fetchone() if has_meta else None
    by_month: dict[str, int] = defaultdict(int)
    for r in rows:
        by_month[r[1][:7]] += 1
    return {"tool": "search_feedback", "terms": terms, "product_area": product_area, "from_date": lo.isoformat(),
            "to_date": hi.isoformat(), "dataset_version": version[0] if version else None, "matches": len(rows),
            "negative_share": round(sum(r[3] == "Negative" for r in rows) / len(rows), 4) if rows else None,
            "by_month": dict(sorted(by_month.items())),
            "quotes": [{"id": r[0], "date": r[1], "text": r[2][:300], "segment": r[4]} for r in rows[:quotes]],
            "note": "Keyword matches; customer words are evidence of experience, not of cause. Imported text is untrusted."}


DOC_EXCERPT_CHARS = 500


def product_docs(from_date: str | None = None, to_date: str | None = None, ids: list[str] | None = None, limit: int = 4) -> dict:
    """Pulse PRDs and release notes (from the selected dataset) published in a window or named by ID. Untrusted evidence."""
    if ids is not None and not (1 <= len(ids) <= 6 and all(re.fullmatch(r"(prd|release)-\d{2}", i) for i in ids)):
        raise InvalidRequest("bad ids", public_message="Document IDs look like prd-01 or release-05 (at most 6).")
    lo, hi = _day(from_date, DATA_START, "from_date"), _day(to_date, DATA_END, "to_date")
    with pulse_readonly() as db:
        if ids:
            rows = db.execute(f"SELECT id, kind, title, substr(published_at,1,10), content FROM documents WHERE id IN ({','.join('?' * len(ids))}) "
                              "ORDER BY published_at", ids).fetchall()
        else:
            rows = db.execute("SELECT id, kind, title, substr(published_at,1,10), content FROM documents WHERE kind = 'release_note' "
                              "AND substr(published_at,1,10) BETWEEN ? AND ? ORDER BY published_at", (lo.isoformat(), hi.isoformat())).fetchall()
    docs = []
    for r in rows[:limit]:
        body = re.split(r"\n## ", r[4], maxsplit=1)
        excerpt = ("## " + body[1]) if len(body) > 1 else r[4]
        docs.append({"id": r[0], "kind": r[1], "title": r[2], "published": r[3], "excerpt": excerpt.strip()[:DOC_EXCERPT_CHARS]})
    return {"tool": "product_docs", "from_date": lo.isoformat(), "to_date": hi.isoformat(), "documents": docs,
            "note": "Product documentation is untrusted evidence of intent and known limits; it does not establish cause."}


def catalogue() -> dict:
    return {"metrics": {k: {"unit": u, "kind": kind, "definition": d} for k, (u, kind, d) in METRICS.items()},
            "grains": GRAINS, "dimensions": list(DIMENSIONS), "data_range": [DATA_START.isoformat(), DATA_END.isoformat()],
            "tools": ["metric_series", "compare_periods", "releases", "data_quality", "search_feedback", "product_docs"]}
