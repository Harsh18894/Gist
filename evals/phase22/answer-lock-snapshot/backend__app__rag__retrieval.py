"""Filtered FTS5, cosine, and reciprocal-rank-fusion retrieval."""
import re
import sqlite3
from dataclasses import dataclass

import numpy as np

from .ingest import DEMO_MODEL, STOPWORDS, demo_vector


@dataclass(frozen=True)
class Filters:
    segment: str | None = None
    product_area: str | None = None
    from_date: str | None = None
    to_date: str | None = None


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    source_id: str
    title: str
    kind: str
    path: str
    source_date: str | None
    segment: str | None
    product_area: str | None
    content: str
    score: float
    keyword_rank: int | None
    semantic_rank: int | None


def _where(filters: Filters) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    for field, value in (("segment", filters.segment), ("product_area", filters.product_area)):
        if value:
            clauses.append(f"s.{field} = ?")
            params.append(value)
    if filters.from_date:
        clauses.append("s.source_date >= ?")
        params.append(filters.from_date)
    if filters.to_date:
        clauses.append("s.source_date <= ?")
        params.append(filters.to_date)
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


def _tokens(question: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", question.lower()) if token not in STOPWORDS and len(token) > 1]


def keyword_search(db: sqlite3.Connection, question: str, filters: Filters, limit: int = 50) -> list[str]:
    terms = _tokens(question)
    if not terms:
        return []
    expression = " OR ".join(f'"{term}"' for term in dict.fromkeys(terms))
    extra, params = _where(filters)
    rows = db.execute(f"""SELECT c.id FROM chunk_fts
        JOIN chunks c ON c.id = chunk_fts.chunk_id
        JOIN sources s ON s.id = c.source_id
        WHERE chunk_fts MATCH ?{extra}
        ORDER BY bm25(chunk_fts), c.id LIMIT ?""", [expression, *params, limit]).fetchall()
    return [row[0] for row in rows]


def semantic_search(db: sqlite3.Connection, vector: np.ndarray, model: str,
                    filters: Filters, limit: int = 50) -> list[tuple[str, float]]:
    extra, params = _where(filters)
    rows = db.execute(f"""SELECT e.chunk_id, e.dimensions, e.vector FROM embeddings e
        JOIN chunks c ON c.id = e.chunk_id JOIN sources s ON s.id = c.source_id
        WHERE e.model = ?{extra}""", [model, *params]).fetchall()
    if not rows or not np.any(vector):
        return []
    query = vector.astype(np.float32)
    query_norm = np.linalg.norm(query)
    if not query_norm:
        return []
    scored: list[tuple[str, float]] = []
    for row in rows:
        if row["dimensions"] != len(query):
            continue
        candidate = np.frombuffer(row["vector"], dtype=np.float32)
        denominator = np.linalg.norm(candidate) * query_norm
        if denominator:
            scored.append((row["chunk_id"], float(np.dot(candidate, query) / denominator)))
    return sorted(scored, key=lambda item: (-item[1], item[0]))[:limit]


def hits_for_ids(db: sqlite3.Connection, ids: list[str], strategy: str) -> list[Hit]:
    hits: list[Hit] = []
    for rank, chunk_id in enumerate(ids, 1):
        row = db.execute("""SELECT c.id AS chunk_id, c.content, s.id AS source_id, s.title,
            s.kind, s.path, s.source_date, s.segment, s.product_area FROM chunks c
            JOIN sources s ON s.id = c.source_id WHERE c.id = ?""", (chunk_id,)).fetchone()
        if row:
            hits.append(Hit(**dict(row), score=1 / rank,
                            keyword_rank=rank if strategy == "keyword" else None,
                            semantic_rank=rank if strategy == "semantic" else None))
    return hits


def hybrid_search(db: sqlite3.Connection, question: str, filters: Filters, *,
                  model: str = DEMO_MODEL, query_vector: np.ndarray | None = None,
                  limit: int = 5) -> list[Hit]:
    keywords = keyword_search(db, question, filters)
    vector = query_vector if query_vector is not None else demo_vector(question)
    semantics = semantic_search(db, vector, model, filters)
    ranks: dict[str, dict[str, int | float]] = {}
    for rank, chunk_id in enumerate(keywords, 1):
        ranks.setdefault(chunk_id, {})["keyword_rank"] = rank
    for rank, (chunk_id, similarity) in enumerate(semantics, 1):
        ranks.setdefault(chunk_id, {})["semantic_rank"] = rank
        ranks[chunk_id]["similarity"] = similarity
    # Hash vectors are lexical projections, so the local demo needs an actual
    # keyword match. Learned OpenAI embeddings may retrieve paraphrases alone.
    eligible = {chunk_id: values for chunk_id, values in ranks.items()
                if "keyword_rank" in values or (model != DEMO_MODEL and values.get("similarity", 0) >= 0.30)}
    scored = sorted(eligible, key=lambda chunk_id: (
        -(1 / (60 + int(eligible[chunk_id]["keyword_rank"])) if "keyword_rank" in eligible[chunk_id] else 0)
        - (1 / (60 + int(eligible[chunk_id]["semantic_rank"])) if "semantic_rank" in eligible[chunk_id] else 0), chunk_id))
    results: list[Hit] = []
    seen_sources: set[str] = set()
    asked_date = next(iter(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question)), None)
    for chunk_id in scored:
        row = db.execute("""SELECT c.id AS chunk_id, c.content, s.id AS source_id, s.title,
            s.kind, s.path, s.source_date, s.segment, s.product_area FROM chunks c
            JOIN sources s ON s.id = c.source_id WHERE c.id = ?""", (chunk_id,)).fetchone()
        if row is None or row["source_id"] in seen_sources:
            continue
        seen_sources.add(row["source_id"])
        rank = eligible[chunk_id]
        score = (1 / (60 + int(rank["keyword_rank"])) if "keyword_rank" in rank else 0) + \
                (1 / (60 + int(rank["semantic_rank"])) if "semantic_rank" in rank else 0)
        if asked_date and row["source_date"] == asked_date:
            score += 0.1
        results.append(Hit(**dict(row), score=score,
                           keyword_rank=int(rank["keyword_rank"]) if "keyword_rank" in rank else None,
                           semantic_rank=int(rank["semantic_rank"]) if "semantic_rank" in rank else None))
        if len(results) >= 50:
            break
    return sorted(results, key=lambda hit: (-hit.score, hit.source_id))[:limit]
