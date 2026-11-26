"""Ask Gist orchestration and citation validation."""
import os
import re
import sqlite3
import time
from dataclasses import replace
from collections.abc import Callable

from app.schemas import AskRequest, AskResponse, SearchHit

from .ingest import DEMO_MODEL
from .evidence import assess, unsupported_numbers
from .provider import EMBED_MODEL, PaidApiDisabled, complete, embed_query_cached
from .candidate_v3 import LOCKED_CONFIG, retrieve
from .retrieval import Filters, Hit, hits_for_ids, hybrid_search

INSUFFICIENT = "I don't have enough evidence in the indexed Pulse sources to answer that question. Try a more specific question or broaden the filters."


def filters_from_request(request: AskRequest) -> Filters:
    return Filters(segment=request.segment, product_area=request.product_area,
                   from_date=request.from_date.isoformat() if request.from_date else None,
                   to_date=request.to_date.isoformat() if request.to_date else None)


def citation(hit: Hit) -> SearchHit:
    return SearchHit(source_id=hit.source_id, chunk_id=hit.chunk_id, title=hit.title,
                     kind=hit.kind, path=hit.path, source_date=hit.source_date,
                     segment=hit.segment, product_area=hit.product_area,
                     snippet=hit.content, score=hit.score,
                     keyword_rank=hit.keyword_rank, semantic_rank=hit.semantic_rank)


def cited_source_ids(answer_text: str) -> set[str] | None:
    """Accept one or more comma- or semicolon-separated IDs per bracket; reject malformed groups."""
    groups = re.findall(r"\[([^\]]+)\]", answer_text)
    if not groups:
        return None
    ids: set[str] = set()
    for group in groups:
        for item in re.split(r"[,;]", group):
            source_id = item.strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", source_id):
                return None
            ids.add(source_id)
    return ids


STATUS_LINE = re.compile(r"\A\s*\**status:\s*(answered|partial|insufficient)\**\s*(?:\n|\Z)", re.IGNORECASE)
ABSTENTION = re.compile(r"\binsufficient evidence\b", re.IGNORECASE)
PAID_CONTEXT_SOURCES = 8


def parse_status(generated: str) -> tuple[str, str]:
    """Read the model's declared status line; fall back to the legacy phrase rule.

    An "answered" reply that still says "insufficient evidence" is downgraded to
    "partial" so a stated limitation is never presented as a complete answer.
    """
    match = STATUS_LINE.match(generated)
    if not match:
        return ("insufficient" if ABSTENTION.search(generated) else "answered"), generated.strip()
    status, body = match.group(1).lower(), generated[match.end():].strip()
    if status == "answered" and ABSTENTION.search(body):
        status = "partial"
    return status, body


def paid_retriever() -> str:
    """Which retriever builds paid answer context: the locked hybrid (default) or MMR diversity."""
    value = os.getenv("GIST_PAID_RETRIEVER", "hybrid")
    if value not in {"hybrid", "mmr"}:
        raise ValueError("GIST_PAID_RETRIEVER must be hybrid or mmr.")
    return value


def _paid_context(db: sqlite3.Connection, question: str, filters: Filters, query_vector) -> list[Hit]:
    if paid_retriever() == "hybrid":
        return hybrid_search(db, question, filters, model=EMBED_MODEL, query_vector=query_vector,
                             limit=PAID_CONTEXT_SOURCES)
    config = replace(LOCKED_CONFIG, results=PAID_CONTEXT_SOURCES)
    source_ids, _trace = retrieve(db, question, filters, query_vector, EMBED_MODEL, config)
    # Source-level results; use each source's first chunk (only 2 of 534 v2 sources have more than one).
    chunk_ids = [f"{source_id}:000" for source_id in source_ids]
    return hits_for_ids(db, chunk_ids, "hybrid")


def answer(db: sqlite3.Connection, request: AskRequest,
           audit_generated: Callable[[str], None] | None = None) -> AskResponse:
    started = time.perf_counter()
    usage = {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
    filters = filters_from_request(request)
    if request.mode == "openai":
        # Check indexed vectors before any paid query-embedding call.
        indexed = db.execute("SELECT COUNT(*) FROM embeddings WHERE model = ?", (EMBED_MODEL,)).fetchone()[0]
        total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if not total or indexed != total:
            raise PaidApiDisabled("OpenAI embeddings are incomplete. Run the guarded embedding command after approval.")
        query_vector, embed_usage = embed_query_cached(db, request.question)
        usage = {key: embed_usage.get(key, 0) for key in usage}
        hits = _paid_context(db, request.question, filters, query_vector)
    else:
        hits = hybrid_search(db, request.question, filters, model=DEMO_MODEL)
    # Demo mode has no model to judge topical fit, so it keeps the lexical coverage rules.
    # Paid mode keeps only fact-type rules; the model's status line and citation checks follow.
    assessment = assess(request.question, hits, fact_rules_only=request.mode == "openai")
    if not assessment.sufficient:
        return AskResponse(answer=INSUFFICIENT, status="insufficient_evidence", mode=request.mode,
                           citations=[], retrieved_sources=[citation(hit) for hit in hits],
                           latency_ms=round((time.perf_counter() - started) * 1000), **usage)
    if request.mode == "demo":
        return AskResponse(answer="Retrieved sources for review. No answer was generated.",
                           status="sources_only", mode=request.mode,
                           citations=[], retrieved_sources=[citation(hit) for hit in hits],
                           latency_ms=round((time.perf_counter() - started) * 1000), **usage)
    else:
        generated, completion_usage = complete(db, request.question, [
            (hit.source_id, hit.content, {"kind": hit.kind, "date": hit.source_date,
                                          "segment": hit.segment, "product_area": hit.product_area})
            for hit in hits])
        if audit_generated is not None:
            audit_generated(generated)
        usage = {key: usage[key] + completion_usage[key] for key in usage}
        declared, body = parse_status(generated)
        source_ids = cited_source_ids(body)
        # Only sources actually sent to the model may be cited.
        allowed = set(completion_usage.get("sent_source_ids") or [hit.source_id for hit in hits])
        # The model also sees each source's date, so a stated date is checked against it too.
        cited_texts = [f"{hit.source_date or ''} {hit.content}" for hit in hits
                       if source_ids and hit.source_id in source_ids]
        if (declared == "insufficient" or not source_ids or not source_ids <= allowed or
                unsupported_numbers(body, cited_texts)):
            return AskResponse(answer=INSUFFICIENT, status="insufficient_evidence", mode=request.mode,
                               citations=[], retrieved_sources=[citation(hit) for hit in hits],
                               latency_ms=round((time.perf_counter() - started) * 1000), **usage)
        response = body
        result_status = "partial" if declared == "partial" else "answered"
        cited = [citation(hit) for hit in hits if hit.source_id in source_ids]
    return AskResponse(answer=response, status=result_status, mode=request.mode,
                       citations=cited, retrieved_sources=[citation(hit) for hit in hits],
                       latency_ms=round((time.perf_counter() - started) * 1000), **usage)
