"""Ask Gist orchestration and citation validation."""
import re
import sqlite3
import time
from collections.abc import Callable

from app.schemas import AskRequest, AskResponse, SearchHit

from .ingest import DEMO_MODEL
from .evidence import assess, unsupported_numbers
from .provider import EMBED_MODEL, PaidApiDisabled, complete, embed_query_cached
from .retrieval import Filters, Hit, hybrid_search

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
    """Accept one or more comma-separated IDs per bracket; reject malformed groups."""
    groups = re.findall(r"\[([^\]]+)\]", answer_text)
    if not groups:
        return None
    ids: set[str] = set()
    for group in groups:
        for item in group.split(","):
            source_id = item.strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", source_id):
                return None
            ids.add(source_id)
    return ids


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
        hits = hybrid_search(db, request.question, filters, model=EMBED_MODEL, query_vector=query_vector)
    else:
        hits = hybrid_search(db, request.question, filters, model=DEMO_MODEL)
    assessment = assess(request.question, hits)
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
        generated, completion_usage = complete(db, request.question,
                                                [(hit.source_id, hit.content) for hit in hits])
        if audit_generated is not None:
            audit_generated(generated)
        usage = {key: usage[key] + completion_usage[key] for key in usage}
        source_ids = cited_source_ids(generated)
        allowed = {hit.source_id for hit in hits}
        cited_texts = [hit.content for hit in hits if source_ids and hit.source_id in source_ids]
        if (not source_ids or not source_ids <= allowed or
                "insufficient evidence" in generated.lower() or
                unsupported_numbers(generated, cited_texts)):
            return AskResponse(answer=INSUFFICIENT, status="insufficient_evidence", mode=request.mode,
                               citations=[], retrieved_sources=[citation(hit) for hit in hits],
                               latency_ms=round((time.perf_counter() - started) * 1000), **usage)
        response = generated
        cited = [citation(hit) for hit in hits if hit.source_id in source_ids]
    return AskResponse(answer=response, status="answered", mode=request.mode,
                       citations=cited, retrieved_sources=[citation(hit) for hit in hits],
                       latency_ms=round((time.perf_counter() - started) * 1000), **usage)
