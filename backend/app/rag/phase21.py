"""Experimental, offline-safe retrieval for the Phase 2.1 development set.

The original locked v2 retriever remains in retrieval.py. Subqueries use FTS only;
one optional caller-supplied query vector is reused for the original question.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from .ingest import STOPWORDS
from .retrieval import Filters, _where, keyword_search, semantic_search

QuestionType = Literal["direct", "semantic", "multi_source", "temporal", "quantitative", "insufficient_context"]


@dataclass(frozen=True)
class InvestigationConfig:
    max_subqueries: int = 3
    retrieval_depth: int = 40
    keyword_weight: float = 1.0
    vector_weight: float = 0.35
    subquery_weight: float = 0.55
    document_boost: float = 0.0
    diversity_penalty: float = 0.0
    focused_subqueries: bool = False
    evidence_quota: bool = False
    max_results: int = 20

    def __post_init__(self) -> None:
        if not 0 <= self.max_subqueries <= 4 or not 1 <= self.retrieval_depth <= 100 or not 1 <= self.max_results <= 20:
            raise ValueError("Subqueries, retrieval depth, and results must be bounded.")
        if any(value < 0 for value in (self.keyword_weight, self.vector_weight,
                                       self.subquery_weight, self.document_boost,
                                       self.diversity_penalty)):
            raise ValueError("Retrieval weights must be non-negative.")


@dataclass(frozen=True)
class InvestigationHit:
    source_id: str
    kind: str
    source_date: str | None
    segment: str | None
    product_area: str | None
    score: float
    evidence_needs: tuple[str, ...]


def classify_question(question: str) -> QuestionType:
    text = question.lower()
    if re.search(r"\b(which engineer|who introduced|how much revenue|exact global count)\b", text):
        return "insufficient_context"
    if re.search(r"\b(how many|how much|count|total|percentage)\b", text):
        return "quantitative"
    if re.search(r"\b(distinguish|compare|separates?|discrepancy|overlap|differ|three reasons|two reasons)\b", text):
        return "multi_source"
    if re.search(r"\b(before|after|earlier|later|change over time|since)\b", text):
        return "temporal"
    if re.search(r"\b(which release|what changed|where is|what did|which two|what controls)\b", text):
        return "direct"
    return "semantic"


def subqueries(question: str, *, max_subqueries: int = 3) -> list[str]:
    """Use a bounded product vocabulary drawn from PRDs, never benchmark labels."""
    if not 0 <= max_subqueries <= 4:
        raise ValueError("max_subqueries must be between 0 and 4")
    text = question.lower()
    needs: list[str] = []
    if any(word in text for word in ("sign in", "login", "access")) and any(word in text for word in ("reasons", "distinguish", "compare")):
        needs += ["owner verification invitation checklist", "password reset expired link", "SAML SSO identity provider configuration"]
    elif any(word in text for word in ("sales", "crm", "connector", "spreadsheet", "import")) and any(word in text for word in ("separat", "distinguish", "versus", "from")):
        needs += ["CRM connector connected missing sales records", "CSV spreadsheet import incorrect field mapping"]
    elif "onboarding" in text and ("collaboration" in text or "starter" in text):
        needs += ["invited teammate owner verification handoff", "shared starter template permissions"]
    elif "invoice" in text and "roster" in text:
        needs += ["archived seats counted until billing cycle closes", "admin roster invoice seat discrepancy"]
    elif any(word in text for word in ("digest", "summaries", "inbox")) and any(word in text for word in ("differ", "everyone", "workspace size")):
        needs += ["project digest positive one board workspace", "project digest too many emails shared boards"]
    elif "notification" in text and ("urgent" in text or "delayed" in text):
        needs += ["urgent alert delivery delay", "project summary digest preference"]
    elif "performance" in text and ("earlier" in text or "release" in text):
        needs += ["large workspace dashboard loading slowly", "portfolio performance release improvement"]
    elif "starter" in text and ("visible" in text or "locate" in text):
        needs += ["shared starter template gallery workspace menu", "team starter role permission copying"]
    # Generic conjunctions cover questions outside the Pulse-specific vocabulary.
    if not needs and classify_question(question) == "multi_source":
        parts = [part.strip(" ?.!,") for part in re.split(r"\s+(?:and|versus|rather than)\s+", question, maxsplit=2)
                 if len(part.split()) >= 3]
        if len(parts) > 1:
            needs += parts
    return list(dict.fromkeys(needs))[:max_subqueries]


def _source_ids(db: sqlite3.Connection, chunk_ids: list[str]) -> list[str]:
    if not chunk_ids:
        return []
    rows = db.execute(f"SELECT id,source_id FROM chunks WHERE id IN ({','.join('?' for _ in chunk_ids)})", chunk_ids).fetchall()
    source_by_chunk = {row[0]: row[1] for row in rows}
    return list(dict.fromkeys(source_by_chunk[chunk_id] for chunk_id in chunk_ids if chunk_id in source_by_chunk))


def _focused_source_ids(db: sqlite3.Connection, query: str, filters: Filters, depth: int) -> list[str]:
    """Prefer an AND of two corpus-rare query terms, then fill with ordinary OR matches."""
    terms = list(dict.fromkeys(term for term in re.findall(r"[a-z0-9]+", query.lower())
                               if len(term) > 2 and term not in STOPWORDS))
    frequency = []
    for term in terms:
        count = db.execute("SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH ?", (f'"{term}"',)).fetchone()[0]
        if count:
            frequency.append((count, term))
    rarest = [term for _, term in sorted(frequency)[:2]]
    focused: list[str] = []
    if rarest:
        expression = " AND ".join(f'"{term}"' for term in rarest)
        extra, params = _where(filters)
        rows = db.execute(f"""SELECT c.id FROM chunk_fts JOIN chunks c ON c.id=chunk_fts.chunk_id
            JOIN sources s ON s.id=c.source_id WHERE chunk_fts MATCH ?{extra}
            ORDER BY bm25(chunk_fts), c.id LIMIT ?""", [expression, *params, depth]).fetchall()
        focused = _source_ids(db, [row[0] for row in rows])
    broad = _source_ids(db, keyword_search(db, query, filters, limit=depth))
    return list(dict.fromkeys([*focused, *broad]))[:depth]


def investigate(db: sqlite3.Connection, question: str, filters: Filters,
                config: InvestigationConfig, *, vector=None, model: str | None = None,
                keyword_candidates: list[str] | None = None,
                vector_candidates: list[str] | None = None) -> tuple[list[InvestigationHit], dict]:
    """Return source-level results and an explainable per-need trace.

    Candidate lists are optional for replaying previously paid development queries
    without sending a new embedding request.
    """
    kind = classify_question(question)
    needs = subqueries(question, max_subqueries=config.max_subqueries) if kind in {"multi_source", "temporal"} else []
    keyword = keyword_candidates if keyword_candidates is not None else _source_ids(
        db, keyword_search(db, question, filters, limit=config.retrieval_depth))
    if vector_candidates is not None:
        semantic = vector_candidates
    elif vector is not None and model is not None:
        semantic = _source_ids(db, [chunk_id for chunk_id, _ in semantic_search(
            db, vector, model, filters, limit=config.retrieval_depth)])
    else:
        semantic = []
    lists: list[tuple[str, list[str], float]] = [("original_keyword", keyword, config.keyword_weight),
                                                ("original_vector", semantic, config.vector_weight)]
    for ordinal, need in enumerate(needs, 1):
        ids = (_focused_source_ids(db, need, filters, config.retrieval_depth) if config.focused_subqueries else
               _source_ids(db, keyword_search(db, need, filters, limit=config.retrieval_depth)))
        lists.append((f"need_{ordinal}", ids, config.subquery_weight))
    score: dict[str, float] = {}
    support: dict[str, set[str]] = {}
    for label, ids, weight in lists:
        for rank, source_id in enumerate(ids[:config.retrieval_depth], 1):
            score[source_id] = score.get(source_id, 0.0) + weight / (30 + rank)
            if label.startswith("need_"):
                support.setdefault(source_id, set()).add(label)
    if not score:
        return [], {"question_type": kind, "subqueries": needs, "candidate_counts": {label: len(ids) for label, ids, _ in lists}}
    ids = sorted(score)
    extra, params = _where(filters)
    rows = db.execute(f"""SELECT s.id,s.kind,s.source_date,s.segment,s.product_area,s.content
        FROM sources s WHERE s.id IN ({','.join('?' for _ in ids)}){extra}""", [*ids, *params]).fetchall()
    by_id = {row[0]: row for row in rows}
    counts: Counter[str] = Counter()
    chosen: list[InvestigationHit] = []
    pool = set(score) & set(by_id)
    seeds: list[str] = []
    if config.evidence_quota and kind == "multi_source":
        for label, ids, _ in lists:
            if label.startswith("need_"):
                source_id = next((item for item in ids if item in pool and item not in seeds), None)
                if source_id:
                    seeds.append(source_id)
    while pool and len(chosen) < config.max_results:
        def adjusted(source_id: str) -> float:
            row = by_id[source_id]
            document = row[1] in {"prd", "release_note"}
            doc_bonus = config.document_boost / 100 if document and kind in {"direct", "temporal", "multi_source"} else 0.0
            kind_penalty = config.diversity_penalty * counts[row[1]] / 100
            return score[source_id] + doc_bonus - kind_penalty
        source_id = seeds.pop(0) if seeds else max(pool, key=lambda item: (adjusted(item), item))
        pool.remove(source_id)
        row = by_id[source_id]
        counts[row[1]] += 1
        chosen.append(InvestigationHit(source_id, row[1], row[2], row[3], row[4],
                                       round(adjusted(source_id), 6), tuple(sorted(support.get(source_id, set())))))
    return chosen, {"question_type": kind, "subqueries": needs,
                    "candidate_counts": {label: len(ids) for label, ids, _ in lists},
                    "evidence_need_hits": {f"need_{i}": [hit.source_id for hit in chosen if f"need_{i}" in hit.evidence_needs]
                                           for i in range(1, len(needs) + 1)}}
