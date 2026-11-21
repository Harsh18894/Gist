"""Gist data access and aggregation. All user values are bound SQL parameters."""
import sqlite3

from .schemas import Category, Page, Segment, Stats


def list_records(db: sqlite3.Connection, page: int, page_size: int,
                 category: Category | None, segment: Segment | None, query: str | None) -> Page:
    clauses: list[str] = []
    values: list[str] = []
    if category:
        clauses.append("issue_category = ?")
        values.append(category)
    if segment:
        clauses.append("customer_segment = ?")
        values.append(segment)
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # LIKE escaping is defined explicitly so search is literal.
        clauses.append("(feedback_text LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\' OR related_feature LIKE ? ESCAPE '\\')")
        values.extend([f"%{escaped}%"] * 3)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    total = db.execute(f"SELECT COUNT(*) FROM feedback{where}", values).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM feedback{where} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
        [*values, page_size, (page - 1) * page_size],
    ).fetchall()
    return Page(items=[dict(row) for row in rows], total=total, page=page,
                page_size=page_size, pages=(total + page_size - 1) // page_size)


def get_record(db: sqlite3.Connection, record_id: str) -> dict | None:
    row = db.execute("SELECT * FROM feedback WHERE id = ?", (record_id,)).fetchone()
    return dict(row) if row else None


def _breakdown(db: sqlite3.Connection, column: str) -> list[dict]:
    # Column names are internal constants, never user input.
    rows = db.execute(f"SELECT {column} AS name, COUNT(*) AS count FROM feedback GROUP BY {column} ORDER BY count DESC, name").fetchall()
    return [dict(row) for row in rows]


def get_stats(db: sqlite3.Connection) -> Stats:
    row = db.execute("""SELECT COUNT(*) AS feedback_count,
        SUM(CASE WHEN sentiment = 'Negative' THEN 1 ELSE 0 END) AS negative_feedback_count,
        SUM(CASE WHEN sentiment = 'Positive' THEN 1 ELSE 0 END) AS positive_feedback_count,
        SUM(CASE WHEN customer_segment = 'Enterprise' THEN 1 ELSE 0 END) AS enterprise_feedback_count
        FROM feedback""").fetchone()
    tickets = db.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0]
    return Stats(feedback_count=row[0], support_ticket_count=tickets,
                 negative_feedback_count=row[1], positive_feedback_count=row[2],
                 enterprise_feedback_count=row[3],
                 by_product_area=_breakdown(db, "product_area"),
                 by_category=_breakdown(db, "issue_category"),
                 by_segment=_breakdown(db, "customer_segment"))
