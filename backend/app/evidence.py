"""Phase 3.6 Evidence Explorer: search every indexed source and show where Gist uses it.

Usage comes from the Phase 3.2 issue map and Phase 3.3 opportunities (deterministic, $0).
Each source gets exactly one status; `used_in` lists every opportunity it supports.
"""
from __future__ import annotations

import sqlite3

from . import issues
from .errors import InvalidRequest
from .opportunities import build

KINDS = ("feedback", "support_ticket", "prd", "release_note")
STATUS_LABELS = {
    "opportunity_evidence": "Main evidence for an opportunity",
    "secondary_mention": "Also mentions an opportunity's problem",
    "needs_triage": "In a vague group (needs triage)",
    "not_grouped": "Not grouped with similar feedback",
    "linked_ticket": "Ticket linked to an opportunity",
    "unlinked_ticket": "Ticket not linked to any opportunity",
    "product_context": "Product context for an opportunity",
    "unused_document": "Document not used as product context",
}
MAX_PAGE_SIZE = 50
MAX_QUERY_CHARS = 200


def usage(db: sqlite3.Connection) -> dict[str, dict]:
    """Status and opportunity links for every source ID."""
    used: dict[str, dict] = {}

    def add(source_id: str, opportunity_id: str, role: str) -> None:
        used.setdefault(source_id, {"roles": set(), "used_in": []})
        used[source_id]["roles"].add(role)
        used[source_id]["used_in"].append({"opportunity_id": opportunity_id, "role": role})

    for card in build(db)["opportunities"]:
        primary = card["evidence"]["feedback_records"]
        for i, fid in enumerate(card["evidence"]["feedback_ids"]):
            add(fid, card["id"], "opportunity_evidence" if i < primary else "secondary_mention")
        for ticket in card["evidence"]["linked_tickets"]:
            add(ticket["id"], card["id"], "linked_ticket")
        for doc in card["product_context"]:
            add(doc["id"], card["id"], "product_context")
    triage = {m["id"] for s in issues.issue_map(db)["sub_themes"] if s["needs_triage"]
              for m in s["members"] if m["membership"] == "primary"}
    result = {}
    for source_id, kind in db.execute("SELECT id, kind FROM sources"):
        roles = used.get(source_id, {}).get("roles", set())
        if kind == "feedback":
            status = next((r for r in ("opportunity_evidence", "secondary_mention") if r in roles),
                          "needs_triage" if source_id in triage else "not_grouped")
        elif kind == "support_ticket":
            status = "linked_ticket" if roles else "unlinked_ticket"
        else:
            status = "product_context" if roles else "unused_document"
        result[source_id] = {"status": status, "used_in": used.get(source_id, {}).get("used_in", [])}
    return result


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(db: sqlite3.Connection, q: str = "", kind: str | None = None, product_area: str | None = None,
           segment: str | None = None, status: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    if len(q) > MAX_QUERY_CHARS:
        raise InvalidRequest("query too long", public_message=f"Search text must be at most {MAX_QUERY_CHARS} characters.")
    if kind is not None and kind not in KINDS:
        raise InvalidRequest("bad kind", public_message="Kind must be feedback, support_ticket, prd or release_note.")
    if status is not None and status not in STATUS_LABELS:
        raise InvalidRequest("bad status", public_message="Unknown usage status.")
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise InvalidRequest("bad page", public_message=f"Page must be 1 or more and page size 1–{MAX_PAGE_SIZE}.")
    clauses, params = [], []
    for term in q.split():
        clauses.append("(content LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\')")
        params += [_like(term)] * 3
    for column, value in (("kind", kind), ("product_area", product_area), ("segment", segment)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(f"SELECT id, kind, title, source_date, segment, product_area, content FROM sources{where} "
                      "ORDER BY source_date DESC, id", params).fetchall()
    use = usage(db)
    matched = [r for r in rows if not status or use[r[0]]["status"] == status]
    counts: dict[str, int] = {}
    for r in rows:
        counts[use[r[0]]["status"]] = counts.get(use[r[0]]["status"], 0) + 1
    start = (page - 1) * page_size
    items = [{"id": r[0], "kind": r[1], "title": r[2], "date": (r[3] or "")[:10] or None, "segment": r[4],
              "product_area": r[5], "snippet": r[6][:280] + ("…" if len(r[6]) > 280 else ""),
              "status": use[r[0]]["status"], "status_label": STATUS_LABELS[use[r[0]]["status"]],
              "used_in": use[r[0]]["used_in"]} for r in matched[start:start + page_size]]
    return {"total": len(matched), "page": page, "page_size": page_size, "items": items,
            "status_counts": counts, "status_labels": STATUS_LABELS,
            "note": "Usage comes from Gist's grouping and similarity linking, not from confirmed causes. Synthetic Pulse data."}
