"""Phase 3.3 opportunity discovery: one evidence-backed card per reliable sub-theme.

Everything is deterministic and derived from stored data or documented rules. There is no
generated prose and no model call. Evidence volume is not business value; revenue, churn,
conversion and effort are never estimated, only listed as unknowns. Scoring lives in priorities.py (Phase 3.4).
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

import numpy as np

from . import issues
from .clustering import Vectorizer, _embeddings, _normalize

# Revised 2026-11-26 after development-half calibration (evals/phase33/results/): the first rubric rated
# nearly everything high and medium groups were purer than high ones.
CONFIDENCE_RUBRIC = [
    ("focus", "At least 80% of records come from one product area (mixed areas often mean mixed problems)"),
    ("cohesion", "Members are close to the group's centre (mean word similarity at least 0.75)"),
    ("corroboration", "At least one support ticket links to the group"),
    ("evidence", "At least 5 feedback records (very small groups are fragile)"),
]


@dataclass(frozen=True)
class LinkConfig:
    """Similarity thresholds for linking tickets and documents to an opportunity.

    Defaults were chosen on the development half (evals/phase33/results/linking-v1.json).
    """
    ticket_threshold: float = 0.6
    second_ticket_margin: float = 0.03   # a ticket may join a second opportunity this close to its best match
    document_threshold: float = 0.5
    max_documents: int = 2

    def __post_init__(self) -> None:
        if not (0 < self.ticket_threshold < 1 and 0 < self.document_threshold < 1 and 0 <= self.second_ticket_margin < 1
                and 1 <= self.max_documents <= 5):
            raise ValueError("Link thresholds must be in (0, 1); max_documents 1–5")


def _vectors(db: sqlite3.Connection, feedback: list[str], tickets: list[tuple], documents: list[tuple]) -> tuple:
    try:
        return (_embeddings(db, feedback), _embeddings(db, [t[0] for t in tickets]),
                _embeddings(db, [d[0] for d in documents]), "learned vectors (stored)")
    except RuntimeError:
        texts = {row[0]: row[1] for row in db.execute("SELECT id, feedback_text FROM feedback")}
        vectorizer = Vectorizer().fit([texts[i] for i in feedback] + [t[1] for t in tickets] + [d[1] for d in documents])
        return (vectorizer.transform([texts[i] for i in feedback]), vectorizer.transform([t[1] for t in tickets]),
                vectorizer.transform([d[1] for d in documents]), "word similarity")


DEFAULT_LINK = LinkConfig()
_cache: dict[tuple, dict] = {}
_CACHE_LIMIT = 8


def _data_key(db: sqlite3.Connection) -> tuple:
    """Everything build() depends on: the issue-map key plus tickets, documents and stored embeddings."""
    counts = db.execute("""SELECT (SELECT COUNT(*) || ':' || IFNULL(MAX(id), '') FROM support_tickets),
                                  (SELECT COUNT(*) || ':' || IFNULL(MAX(id), '') FROM documents),
                                  (SELECT COUNT(*) FROM sqlite_master WHERE name = 'embeddings')""").fetchone()
    vectors = db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] if counts[2] else 0
    return issues._key(db) + (counts[0], counts[1], vectors)


def build(db: sqlite3.Connection, link: LinkConfig = LinkConfig()) -> dict:
    """Opportunity cards for the current data. Deterministic, so the server's default configuration is cached per
    data version (callers must not modify the returned structure; tests guard this). Other configurations, used by
    the evaluation sweeps, are computed fresh."""
    if link != DEFAULT_LINK:
        return _build(db, link)
    key = _data_key(db)
    if key not in _cache:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.clear()
        _cache[key] = _build(db, link)
    return _cache[key]


def _build(db: sqlite3.Connection, link: LinkConfig) -> dict:
    data = issues.issue_map(db)
    subs = [s for s in data["sub_themes"] if not s["needs_triage"]]
    feedback_ids = [row[0] for row in db.execute("SELECT id FROM feedback ORDER BY id")]
    position = {fid: i for i, fid in enumerate(feedback_ids)}
    tickets = db.execute("""SELECT id, subject || '. ' || description, severity, status, substr(timestamp,1,10),
        customer_segment, product_area FROM support_tickets ORDER BY id""").fetchall()
    documents = db.execute("SELECT id, title || '. ' || content, kind, title, substr(published_at,1,10) FROM documents ORDER BY id").fetchall()
    feedback_vectors, ticket_vectors, doc_vectors, method = _vectors(db, feedback_ids, tickets, documents)
    primary = [[m["id"] for m in s["members"] if m["membership"] == "primary"] for s in subs]
    centroids = _normalize(np.vstack([feedback_vectors[[position[i] for i in ids]].mean(axis=0) for ids in primary])) \
        if subs else np.zeros((0, feedback_vectors.shape[1]))

    # Tickets: best-matching opportunity above the threshold, plus a near-tie second one (multi-issue tickets).
    ticket_links: dict[int, list[tuple[str, float]]] = {}
    if subs and len(tickets):
        sims = ticket_vectors @ centroids.T
        for t, row in enumerate(sims):
            order = np.argsort(-row)
            best = float(row[order[0]])
            if best < link.ticket_threshold:
                continue
            chosen = [order[0]] + [j for j in order[1:2] if row[j] >= link.ticket_threshold and best - row[j] <= link.second_ticket_margin]
            for j in chosen:
                ticket_links.setdefault(int(j), []).append((tickets[t][0], round(float(row[j]), 4)))
    doc_sims = doc_vectors @ centroids.T if subs and len(documents) else np.zeros((len(documents), len(subs)))
    by_ticket = {t[0]: t for t in tickets}

    all_dates = sorted({m["date"] for s in data["sub_themes"] for m in s["members"]} | {u["date"] for u in data["unclustered"]})
    months = sorted({d[:7] for d in all_dates})
    total_feedback = data["records"]
    cards = []
    for j, sub in enumerate(subs):
        members = sub["members"]
        primary_members = [m for m in members if m["membership"] == "primary"]
        linked = sorted(ticket_links.get(j, []), key=lambda x: (-x[1], x[0]))
        severity = Counter(by_ticket[tid][2] for tid, _ in linked)
        docs = sorted(((documents[d][0], float(doc_sims[d, j])) for d in range(len(documents)) if doc_sims[d, j] >= link.document_threshold),
                      key=lambda x: -x[1])[:link.max_documents]
        doc_rows = {d[0]: d for d in documents}
        negative = sum(m["sentiment"] == "Negative" for m in members)
        cohesion = float(np.mean([m["similarity"] for m in primary_members])) if primary_members else 0.0
        area_counts = Counter(m["area"] for m in primary_members)
        focus = area_counts.most_common(1)[0][1] / len(primary_members) if primary_members else 0.0
        checks = {"focus": focus >= 0.8, "cohesion": cohesion >= 0.75,
                  "corroboration": len(linked) > 0, "evidence": sub["size"] >= 5}
        points = sum(checks.values())
        monthly = Counter(m["date"][:7] for m in members)
        context = []
        for doc_id, sim in docs:
            row = doc_rows[doc_id]
            item = {"id": doc_id, "title": row[3], "kind": row[2], "published": row[4], "similarity": round(sim, 4)}
            if row[2] == "release_note":
                item["records_before"] = sum(m["date"] < row[4] for m in members)
                item["records_after"] = sum(m["date"] >= row[4] for m in members)
            context.append(item)
        unknowns = ["Business impact (revenue, churn, conversion) is not in the data.",
                    "Engineering effort is not provided; it must be estimated by the team.",
                    "Root cause is not established: records are grouped by similarity, not by confirmed cause."]
        if not context:
            unknowns.append("No product document closely matches this problem; current product intent is unknown.")
        for item in context:
            if item["kind"] == "release_note":
                unknowns.append(f"Whether the {item['published']} release ({item['id']}) changed this is not established; "
                                f"{item['records_before']} records came before it and {item['records_after']} after.")
        assumptions = ["The grouped records describe one shared problem (similarity grouping; check the quotes).",
                       "Volume of feedback reflects how often customers hit the problem, not how much it matters."]
        if sub["secondary_members"]:
            assumptions.append(f"{sub['secondary_members']} records mention this alongside another problem; they are counted as supporting evidence.")
        if sub["distinct_texts"] < sub["size"]:
            assumptions.append(f"Repeated wording is counted once per record ({sub['size']} records, {sub['distinct_texts']} distinct wordings).")
        cards.append({
            "id": f"OPP-{sub['id']}", "sub_theme_id": sub["id"], "theme_id": sub["theme_id"], "title": sub["label"],
            "problem": sub["representatives"][0]["text"] if sub["representatives"] else sub["label"],
            "quotes": sub["representatives"],
            "evidence": {"feedback_records": sub["size"], "also_mentioned_in": sub["secondary_members"],
                         "distinct_wordings": sub["distinct_texts"], "feedback_ids": [m["id"] for m in members],
                         "linked_tickets": [{"id": tid, "similarity": sim, "severity": by_ticket[tid][2], "status": by_ticket[tid][3]}
                                            for tid, sim in linked]},
            # Primary records only: secondary members mainly describe another problem and are reported separately.
            "frequency": {"records": sub["size"], "also_mentioned_in": sub["secondary_members"],
                          "share_of_feedback": round(sub["size"] / total_feedback, 4) if total_feedback else 0.0},
            "severity_proxy": {"negative_share": round(negative / len(members), 4) if members else 0.0,
                               "linked_tickets": len(linked), "tickets_by_severity": dict(severity.most_common()),
                               "note": "Proxy only: negative sentiment and ticket severity, not customer or business impact."},
            "segments": sub["segments"], "areas": sub["areas"],
            "trend": {"label": sub["trend"], "recent_90_days": sub["recent_90_days"], "prior_90_days": sub["prior_90_days"],
                      "first_date": sub["first_date"], "last_date": sub["last_date"],
                      "months": months, "monthly_counts": [monthly.get(m, 0) for m in months]},
            "confidence": {"level": "high" if points == 4 else "medium" if points == 3 else "low", "points": points,
                           "checks": checks, "cohesion": round(cohesion, 4), "area_focus": round(focus, 4)},
            "product_context": context, "assumptions": assumptions, "unknowns": unknowns})
    linked_ticket_ids = {tid for links in ticket_links.values() for tid, _ in links}
    return {"method": method, "link_config": link.__dict__, "opportunities": cards,
            "excluded_needs_triage": [s["id"] for s in data["sub_themes"] if s["needs_triage"]],
            "unlinked_tickets": len(tickets) - len(linked_ticket_ids), "total_tickets": len(tickets),
            "confidence_rubric": [{"check": k, "rule": v} for k, v in CONFIDENCE_RUBRIC] +
                                 [{"check": "levels", "rule": "High: all 4 checks; medium: 3; low: 2 or fewer. A coarse rubric, not a probability."}],
            "interpretation": ("Opportunities are evidence summaries for discussion, not recommendations. Frequency is not "
                               "business value; revenue, churn and effort are unknown. The Priorities page scores them transparently.")}
