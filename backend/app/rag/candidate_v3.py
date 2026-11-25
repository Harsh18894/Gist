"""Experimental source-level retriever for the benchmark-3 development trials.

Not the Ask Gist default and not the locked v2 retriever (`retrieval.py`).
Every adjustment is general (weights, document presence, diversity, generic
clause splitting); none uses product vocabulary or benchmark wording.
Subqueries use local FTS5 only, so they add no API cost.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

import numpy as np

from .ingest import STOPWORDS
from .retrieval import Filters, keyword_search, semantic_search

DOCUMENT_KINDS = {"prd", "release_note"}
MULTI_PART_CUE = re.compile(r"\b(?:distinct|separate|separates|distinguish|differ|differs|compare|versus|vs|"
                            r"rather than|and what|and how|and which)\b")
SPLIT = re.compile(r",\s*and\s+|\s+and\s+(?=(?:what|how|which|who|when|where|later)\b)|"
                   r"\s+(?:versus|vs\.?|rather than)\s+|\s+from\s+")


@dataclass(frozen=True)
class CandidateConfig:
    keyword_weight: float = 1.0
    vector_weight: float = 1.0
    rrf_k: int = 60
    depth: int = 50
    vector_only_min_similarity: float = 0.30   # same eligibility rule as the locked hybrid
    document_slot: bool = False                # keep one matching product document in the top five
    document_depth: int = 15
    decompose: bool = False                    # generic clause split for multi-part questions
    subquery_weight: float = 0.5
    max_subqueries: int = 3
    mmr_lambda: float | None = None            # diversity-aware rerank when set (0..1)
    results: int = 20

    def __post_init__(self) -> None:
        if not (0 <= self.max_subqueries <= 4 and 1 <= self.depth <= 100 and 1 <= self.results <= 20):
            raise ValueError("Subqueries, depth and results must be bounded.")
        if self.mmr_lambda is not None and not 0 <= self.mmr_lambda <= 1:
            raise ValueError("mmr_lambda must be between 0 and 1.")


def _content_terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2 and t not in STOPWORDS]


def split_question(question: str, limit: int = 3) -> list[str]:
    """Split a multi-part question into clauses; return [] for single-part questions."""
    text = question.strip().rstrip("?.!")
    if not MULTI_PART_CUE.search(text.lower()):
        return []
    parts = [part.strip(" ,") for part in SPLIT.split(text)]
    parts = [part for part in parts if len(_content_terms(part)) >= 2]
    return parts[:limit] if len(parts) > 1 else []


def _source_ranks(db: sqlite3.Connection, chunk_ids: list[str]) -> list[str]:
    if not chunk_ids:
        return []
    rows = dict(db.execute(f"SELECT id,source_id FROM chunks WHERE id IN ({','.join('?' * len(chunk_ids))})", chunk_ids))
    return list(dict.fromkeys(rows[cid] for cid in chunk_ids if cid in rows))


def _source_vectors(db: sqlite3.Connection, source_ids: list[str], model: str) -> dict[str, np.ndarray]:
    if not source_ids:
        return {}
    rows = db.execute(f"""SELECT c.source_id, e.vector FROM embeddings e JOIN chunks c ON c.id = e.chunk_id
        WHERE e.model = ? AND c.source_id IN ({','.join('?' * len(source_ids))})""", [model, *source_ids]).fetchall()
    grouped: dict[str, list[np.ndarray]] = {}
    for source_id, blob in rows:
        grouped.setdefault(source_id, []).append(np.frombuffer(blob, dtype=np.float32))
    vectors = {}
    for source_id, items in grouped.items():
        mean = np.mean(items, axis=0)
        norm = np.linalg.norm(mean)
        if norm:
            vectors[source_id] = mean / norm
    return vectors


def retrieve(db: sqlite3.Connection, question: str, filters: Filters, vector: np.ndarray,
             model: str, config: CandidateConfig) -> tuple[list[str], dict]:
    keyword = _source_ranks(db, keyword_search(db, question, filters, limit=config.depth))
    semantic_chunks = semantic_search(db, vector, model, filters, limit=config.depth)
    similarity: dict[str, float] = {}
    for chunk_id, value in semantic_chunks:
        source = _source_ranks(db, [chunk_id])
        if source and source[0] not in similarity:
            similarity[source[0]] = value
    semantic = list(similarity)
    score: dict[str, float] = {}
    for rank, source_id in enumerate(keyword, 1):
        score[source_id] = score.get(source_id, 0.0) + config.keyword_weight / (config.rrf_k + rank)
    keyword_set = set(keyword)
    for rank, source_id in enumerate(semantic, 1):
        if source_id in keyword_set or similarity[source_id] >= config.vector_only_min_similarity:
            score[source_id] = score.get(source_id, 0.0) + config.vector_weight / (config.rrf_k + rank)
    parts = split_question(question, config.max_subqueries) if config.decompose else []
    part_lists = []
    for part in parts:
        ids = _source_ranks(db, keyword_search(db, part, filters, limit=config.depth))
        part_lists.append(ids)
        for rank, source_id in enumerate(ids, 1):
            score[source_id] = score.get(source_id, 0.0) + config.subquery_weight / (config.rrf_k + rank)
    ranked = sorted(score, key=lambda sid: (-score[sid], sid))
    trace = {"subqueries": parts, "mmr": config.mmr_lambda is not None, "document_slot_used": None}

    if config.mmr_lambda is not None and ranked:
        pool = ranked[:config.depth]
        vectors = _source_vectors(db, pool, model)
        top = score[pool[0]]
        chosen: list[str] = []
        remaining = list(pool)
        while remaining and len(chosen) < config.results:
            def mmr(sid: str) -> float:
                penalty = max((float(vectors[sid] @ vectors[other]) for other in chosen
                               if sid in vectors and other in vectors), default=0.0)
                return config.mmr_lambda * score[sid] / top - (1 - config.mmr_lambda) * penalty
            best = max(remaining, key=lambda sid: (mmr(sid), sid))
            chosen.append(best)
            remaining.remove(best)
        ranked = chosen + [sid for sid in ranked if sid not in chosen]

    if part_lists:
        # Evidence quota: each clause's best source appears within the top five.
        for ids in part_lists:
            best = next((sid for sid in ids if sid in score), None)
            if best and best not in ranked[:5]:
                ranked.remove(best)
                ranked.insert(min(4, len(ranked)), best)

    if config.document_slot:
        kinds = dict(db.execute(f"SELECT id,kind FROM sources WHERE id IN ({','.join('?' * len(ranked))})", ranked)) if ranked else {}
        if not any(kinds.get(sid) in DOCUMENT_KINDS for sid in ranked[:5]):
            document = next((sid for sid in ranked[5:config.document_depth] if kinds.get(sid) in DOCUMENT_KINDS), None)
            if document:
                ranked.remove(document)
                ranked.insert(min(2, len(ranked)), document)
                trace["document_slot_used"] = document
    return ranked[:config.results], trace


# Locked 2026-11-23 from development trials on gist-phase2.1-benchmark-3-reviewed.
# Changing this value or this file invalidates evals/phase21/retrieval-lock-benchmark3.json.
LOCKED_CONFIG = CandidateConfig(mmr_lambda=0.7)
