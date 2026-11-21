"""Gist Phase 1 read-only HTTP API."""
from datetime import date
import os
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import cors_origin
from .database import connection
from .schemas import (Area, AskRequest, AskResponse, Category, ErrorResponse, Feedback,
                      Page, SearchHit, Segment, SourceDetail, Stats, UsageSummary)
from .services import get_record, get_stats, list_records
from .rag.ingest import DEMO_MODEL
from .rag.provider import PaidApiDisabled, ProviderError, usage_summary
from .rag.provider import EMBED_MODEL, DEFAULT_LLM_MODEL
from .rag.retrieval import Filters, hits_for_ids, hybrid_search, keyword_search, semantic_search
from .rag.ingest import demo_vector
from .rag.service import answer, citation

app = FastAPI(title="Gist API", description="Synthetic Pulse product intelligence data", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[cors_origin()], allow_methods=["GET", "POST"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "Check the supplied query parameters."}})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "Gist"}


@app.get("/api/records", response_model=Page, responses={422: {"model": ErrorResponse}})
def records(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
            category: Category | None = None, segment: Segment | None = None,
            query: str | None = Query(None, max_length=200)) -> Page:
    with connection() as db:
        return list_records(db, page, page_size, category, segment, query.strip() if query else None)


@app.get("/api/records/{record_id}", response_model=Feedback,
         responses={404: {"model": ErrorResponse}})
def record(record_id: str) -> Feedback | JSONResponse:
    with connection() as db:
        found = get_record(db, record_id)
    if not found:
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Feedback record not found."}})
    return Feedback(**found)


@app.get("/api/stats", response_model=Stats)
def stats() -> Stats:
    with connection() as db:
        return get_stats(db)


@app.get("/api/search", response_model=list[SearchHit], responses={422: {"model": ErrorResponse}})
def search(query: str = Query(min_length=3, max_length=500),
           strategy: Literal["keyword", "semantic", "hybrid"] = "hybrid",
           segment: Segment | None = None, product_area: Area | None = None,
           from_date: date | None = None, to_date: date | None = None,
           limit: int = Query(5, ge=1, le=20)) -> list[SearchHit] | JSONResponse:
    if from_date and to_date and from_date > to_date:
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "from_date must be on or before to_date."}})
    filters = Filters(segment, product_area, from_date.isoformat() if from_date else None,
                      to_date.isoformat() if to_date else None)
    with connection() as db:
        if strategy == "hybrid":
            hits = hybrid_search(db, query, filters, limit=limit)
        elif strategy == "keyword":
            ids = keyword_search(db, query, filters, limit=limit)
            hits = hits_for_ids(db, ids, strategy)
        else:
            ids = [item[0] for item in semantic_search(db, demo_vector(query), DEMO_MODEL, filters, limit=limit)]
            hits = hits_for_ids(db, ids, strategy)
        return [citation(hit) for hit in hits]


@app.post("/api/ask", response_model=AskResponse,
          responses={403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
def ask(request: AskRequest) -> AskResponse | JSONResponse:
    try:
        with connection() as db:
            return answer(db, request)
    except PaidApiDisabled as exc:
        return JSONResponse(status_code=403, content={"error": {"code": "paid_api_disabled", "message": str(exc)}})
    except ProviderError:
        return JSONResponse(status_code=502, content={"error": {"code": "provider_error", "message": "The answer service is temporarily unavailable."}})


@app.get("/api/sources/{source_id}", response_model=SourceDetail,
         responses={404: {"model": ErrorResponse}})
def source(source_id: str) -> SourceDetail | JSONResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Source not found."}})
    return SourceDetail(**dict(row))


@app.get("/api/usage", response_model=UsageSummary)
def usage() -> UsageSummary:
    with connection() as db:
        return UsageSummary(**usage_summary(db))


@app.get("/api/rag/status")
def rag_status() -> dict:
    with connection() as db:
        has_meta = db.execute("SELECT name FROM sqlite_master WHERE name = 'dataset_meta'").fetchone()
        version = db.execute("SELECT value FROM dataset_meta WHERE key = 'version'").fetchone() if has_meta else None
        fingerprint = db.execute("SELECT value FROM dataset_meta WHERE key = 'source_sha256'").fetchone() if has_meta else None
        sources = db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        openai_vectors = db.execute("SELECT COUNT(*) FROM embeddings WHERE model = ?", (EMBED_MODEL,)).fetchone()[0]
    legacy_v1 = not has_meta and sources > 0
    return {"dataset_version": version[0] if version else "v1" if legacy_v1 else "unseeded", "source_sha256": fingerprint[0] if fingerprint else None,
            "sources": sources, "chunks": chunks, "openai_vectors": openai_vectors,
            "paid_api_enabled": os.getenv("GIST_ENABLE_PAID_API") == "true" and
            os.getenv("GIST_PAID_EVAL_APPROVED") == "true" and chunks > 0 and openai_vectors == chunks,
            "llm_model": os.getenv("GIST_LLM_MODEL", DEFAULT_LLM_MODEL)}
