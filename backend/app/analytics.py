"""Phase 3.1 deterministic product analytics. Every figure is a parameterized SQL query.

Filters are the same everywhere: an inclusive date range on the record date
(`substr(timestamp, 1, 10)`), customer segment and product area. No model calls.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

UNSPECIFIED_FEATURES = ("", "unspecified")
NEGATIVE_SENTIMENTS = ("Negative", "Mixed")
GROUP_COLUMNS = {"category": "issue_category", "area": "product_area", "segment": "customer_segment"}
METRICS = {"feedback": ("feedback", None), "negative_feedback": ("feedback", "Negative"), "tickets": ("support_tickets", None)}


@dataclass(frozen=True)
class Scope:
    from_date: str | None = None
    to_date: str | None = None
    segment: str | None = None
    product_area: str | None = None

    def __post_init__(self) -> None:
        for value in (self.from_date, self.to_date):
            if value is not None:
                date.fromisoformat(value)
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")


def where(scope: Scope, *extra: tuple[str, object]) -> tuple[str, list]:
    """WHERE clause shared by feedback and support_tickets (same column names)."""
    clauses: list[str] = []
    params: list = []
    if scope.from_date:
        clauses.append("substr(timestamp, 1, 10) >= ?")
        params.append(scope.from_date)
    if scope.to_date:
        clauses.append("substr(timestamp, 1, 10) <= ?")
        params.append(scope.to_date)
    for column, value in (("customer_segment", scope.segment), ("product_area", scope.product_area), *extra):
        if value is not None:
            clauses.append(f"{column} = ?")  # column names are internal constants
            params.append(value)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _count(db: sqlite3.Connection, table: str, scope: Scope, *extra: tuple[str, object]) -> int:
    clause, params = where(scope, *extra)
    return db.execute(f"SELECT COUNT(*) FROM {table}{clause}", params).fetchone()[0]


def _breakdown(db: sqlite3.Connection, table: str, column: str, scope: Scope) -> list[dict]:
    clause, params = where(scope)
    rows = db.execute(f"""SELECT COALESCE(NULLIF({column}, ''), '(missing)') AS name, COUNT(*) AS count
        FROM {table}{clause} GROUP BY name ORDER BY count DESC, name""", params).fetchall()
    return [{"name": row[0], "count": row[1]} for row in rows]


def summary(db: sqlite3.Connection, scope: Scope) -> dict:
    feedback = _count(db, "feedback", scope)
    negative = _count(db, "feedback", scope, ("sentiment", "Negative"))
    clause, params = where(scope)
    span = db.execute(f"SELECT MIN(substr(timestamp,1,10)), MAX(substr(timestamp,1,10)) FROM feedback{clause}", params).fetchone()
    quality = db.execute(f"""SELECT
        COALESCE(SUM(related_feature IN ('', 'unspecified')), 0),
        COALESCE(SUM(issue_category = 'Unclear'), 0),
        COALESCE(SUM(issue_category = 'Multiple issues'), 0),
        COALESCE(SUM(customer_segment IS NULL OR customer_segment = ''), 0),
        COALESCE(SUM(product_area IS NULL OR product_area = ''), 0)
        FROM feedback{clause}""", params).fetchone()
    return {"scope": scope.__dict__, "feedback_count": feedback, "ticket_count": _count(db, "support_tickets", scope),
            "negative_feedback_count": negative,
            "negative_share": round(negative / feedback, 4) if feedback else None,
            "date_range": {"first": span[0], "last": span[1]},
            "by_sentiment": _breakdown(db, "feedback", "sentiment", scope),
            "by_category": _breakdown(db, "feedback", "issue_category", scope),
            "by_segment": _breakdown(db, "feedback", "customer_segment", scope),
            "by_area": _breakdown(db, "feedback", "product_area", scope),
            "by_channel": _breakdown(db, "feedback", "feedback_channel", scope),
            "tickets_by_severity": _breakdown(db, "support_tickets", "severity", scope),
            "tickets_by_status": _breakdown(db, "support_tickets", "status", scope),
            "data_quality": {"unspecified_feature": quality[0], "unclear_category": quality[1],
                             "multiple_issues": quality[2], "missing_segment": quality[3], "missing_area": quality[4]}}


def _months(first: str, last: str) -> list[str]:
    year, month = int(first[:4]), int(first[5:7])
    months = []
    while f"{year:04d}-{month:02d}" <= last[:7]:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def trends(db: sqlite3.Connection, scope: Scope, metric: str = "feedback", group_by: str | None = None) -> dict:
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {sorted(METRICS)}")
    if group_by is not None and group_by not in GROUP_COLUMNS:
        raise ValueError(f"group_by must be one of {sorted(GROUP_COLUMNS)}")
    table, sentiment = METRICS[metric]
    extra = (("sentiment", sentiment),) if sentiment else ()
    clause, params = where(scope, *extra)
    group = GROUP_COLUMNS.get(group_by, "'All'")
    rows = db.execute(f"""SELECT substr(timestamp,1,7) AS month, COALESCE(NULLIF({group}, ''), '(missing)') AS name,
        COUNT(*) FROM {table}{clause} GROUP BY month, name""", params).fetchall()
    first = scope.from_date or min((r[0] for r in rows), default=None)
    last = scope.to_date or max((r[0] for r in rows), default=None)
    months = _months(first, last) if first and last else []
    index = {month: i for i, month in enumerate(months)}
    series: dict[str, list[int]] = {}
    for month, name, count in rows:
        series.setdefault(name, [0] * len(months))[index[month]] += count
    ordered = sorted(series.items(), key=lambda item: (-sum(item[1]), item[0]))
    return {"scope": scope.__dict__, "metric": metric, "group_by": group_by, "months": months,
            "series": [{"name": name, "counts": counts, "total": sum(counts)} for name, counts in ordered],
            "total": sum(sum(counts) for counts in series.values())}


def _release_area(content: str) -> str | None:
    match = re.search(r"^Product area:\s*(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else None


def releases(db: sqlite3.Connection, scope: Scope, window_days: int = 30) -> dict:
    """Feedback and tickets in each release's product area, `window_days` before vs from the release date."""
    if not 1 <= window_days <= 180:
        raise ValueError("window_days must be between 1 and 180")
    items = []
    for doc_id, title, published, content in db.execute(
            "SELECT id, title, published_at, content FROM documents WHERE kind = 'release_note' ORDER BY published_at, id"):
        area = _release_area(content)
        day = date.fromisoformat(published[:10])
        if (scope.product_area and area != scope.product_area) or \
                (scope.from_date and published[:10] < scope.from_date) or (scope.to_date and published[:10] > scope.to_date):
            continue
        windows = {"before": (day - timedelta(days=window_days), day - timedelta(days=1)),
                   "after": (day, day + timedelta(days=window_days - 1))}
        counts = {}
        for label, (start, end) in windows.items():
            window = Scope(start.isoformat(), end.isoformat(), scope.segment, area)
            counts[label] = {"from_date": start.isoformat(), "to_date": end.isoformat(),
                             "feedback": _count(db, "feedback", window),
                             "negative_feedback": _count(db, "feedback", window, ("sentiment", "Negative")),
                             "tickets": _count(db, "support_tickets", window)}
        items.append({"id": doc_id, "title": title, "published": published[:10], "product_area": area, **counts})
    return {"scope": scope.__dict__, "window_days": window_days, "releases": items,
            "interpretation": "Counts show association in time only, not causation."}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def repeated(db: sqlite3.Connection, scope: Scope, min_count: int = 2, limit: int = 10) -> dict:
    if not 2 <= min_count <= 50 or not 1 <= limit <= 50:
        raise ValueError("min_count must be 2–50 and limit 1–50")
    clause, params = where(scope)
    joiner = " AND " if clause else " WHERE "
    negatives = db.execute(f"""SELECT id, feedback_text FROM feedback{clause}{joiner}sentiment IN (?, ?) ORDER BY id""",
                           [*params, *NEGATIVE_SENTIMENTS]).fetchall()
    groups: dict[str, list[tuple[str, str]]] = {}
    for record_id, text in negatives:
        groups.setdefault(_normalize(text), []).append((record_id, text))
    texts = sorted(((rows[0][1], [r[0] for r in rows]) for rows in groups.values() if len(rows) >= min_count),
                   key=lambda item: (-len(item[1]), item[0]))[:limit]
    features = db.execute(f"""SELECT related_feature, issue_category, COUNT(*) AS n FROM feedback{clause}{joiner}
        sentiment = 'Negative' AND related_feature NOT IN (?, ?) GROUP BY related_feature, issue_category
        ORDER BY n DESC, related_feature LIMIT ?""", [*params, *UNSPECIFIED_FEATURES, limit]).fetchall()
    return {"scope": scope.__dict__,
            "repeated_texts": [{"text": text, "count": len(ids), "record_ids": ids} for text, ids in texts],
            "top_negative_features": [{"feature": f, "category": c, "count": n} for f, c, n in features],
            "note": "Repeated texts are exact matches after lowercasing and removing punctuation; near-duplicates are not merged."}


def list_tickets(db: sqlite3.Connection, scope: Scope, page: int, page_size: int, *,
                 severity: str | None = None, status: str | None = None, category: str | None = None) -> dict:
    clause, params = where(scope, ("severity", severity), ("status", status), ("issue_category", category))
    total = db.execute(f"SELECT COUNT(*) FROM support_tickets{clause}", params).fetchone()[0]
    rows = db.execute(f"SELECT * FROM support_tickets{clause} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
                      [*params, page_size, (page - 1) * page_size]).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size}
