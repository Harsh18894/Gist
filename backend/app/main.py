"""Gist HTTP API."""
from contextlib import asynccontextmanager
from datetime import date
import logging
import os
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import analytics, evidence, experiments, issues, observability, opportunities, priorities, public
from .investigate import audit as investigation_log, executor as investigation_executor
from .investigate.plan import rule_plan
from .config import cors_origin
from .database import connection
from .errors import GistError, InvalidRequest
from .schemas import (AnalyticsReleases, AnalyticsRepeated, AnalyticsSummary, AnalyticsTrends, Area, AskRequest,
                      AskResponse, Category, ErrorResponse, Feedback, Page, SearchHit, Segment, Sentiment,
                      SourceDetail, Stats, TicketPage, UsageSummary, IssueMap, SubThemeDetail, IssueRecord)
from .services import get_record, get_stats, list_records
from .rag.ingest import DEMO_MODEL
from .rag.provider import PaidApiDisabled, PaidRequestRejected, ProviderError, usage_summary
from .rag.provider import EMBED_MODEL, DEFAULT_LLM_MODEL
from .rag.retrieval import Filters, hits_for_ids, hybrid_search, keyword_search, semantic_search
from .rag.ingest import demo_vector
from .rag.service import answer, citation

def _configure_logging() -> None:
    """Print Gist's own INFO+ messages (uvicorn only configures its own loggers, so these were silently dropped)."""
    gist = logging.getLogger("gist")
    if not gist.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        gist.addHandler(handler)
        gist.setLevel(logging.INFO)
        gist.propagate = False


_configure_logging()
logger = logging.getLogger("gist.api")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def warm_caches() -> float | None:
    """Build the deterministic caches (issue map, opportunities) before serving, so the first visitor after a
    restart or a free-tier wake-up does not pay for them. Returns seconds taken, or None if warming failed.
    Never raises: a warming problem is logged and the request path builds the caches as before."""
    import time
    started = time.perf_counter()
    try:
        with connection() as db:
            issue_map = issues.issue_map(db)
            built = opportunities.build(db)
    except Exception:  # noqa: BLE001 - warming must never stop the API from starting
        logger.warning("Cache warming failed; caches will be built on first use.", exc_info=True)
        return None
    # The product-events database is separate and optional locally: warm it on its own, so a problem here never
    # undoes the warming above. Counting events per day also reads the whole file once, so first queries are fast.
    from .investigate import tools
    try:
        with tools.connect() as events_db:
            event_days = f"{len(tools._daily_counts(events_db))} event days"
    except Exception:  # noqa: BLE001
        event_days = "events not warmed"
        logger.warning("Events cache warming skipped; investigations will build it on first use.", exc_info=True)
    seconds = time.perf_counter() - started
    logger.info("Caches warmed in %.2f s (%d sub-themes, %d opportunities, %s, %s)", seconds,
                len(issue_map["sub_themes"]), len(built["opportunities"]), built["method"], event_days)
    return seconds


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("GIST_WARM_CACHES", "").strip().lower() == "true":
        warm_caches()
    yield


app = FastAPI(title="Gist API", description="Synthetic Pulse product intelligence data", version="0.1.0", lifespan=lifespan,
              responses={500: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})


# Registered BEFORE CORSMiddleware: the middleware added last is outermost, so
# CORS wraps this and browsers can read the error body. An
# exception_handler(Exception) would run outside CORS instead.
@app.middleware("http")
async def unexpected_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:  # noqa: BLE001 - last-resort boundary; details go to the log only
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "internal_error", "Gist hit an unexpected error. Check the API logs.")


@app.middleware("http")
async def public_limits(request: Request, call_next):
    """Public mode only: cap request bodies and rate-limit every API route per client IP."""
    if public.public_mode() and request.url.path.startswith("/api/"):
        lim = public.limits()
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            length = request.headers.get("content-length")
            if length is None and request.method != "DELETE":
                return _error(411, "length_required", "Requests to the public demo must declare their size.")
            if length is not None and (not length.isdigit() or int(length) > lim["max_body_bytes"]):
                return _error(413, "too_large", "That request is too large for the public demo.")
        if request.method != "OPTIONS" and not public.API_WINDOW.allow(public.client_ip(request), lim["api_per_minute"], 60):
            return _error(429, "rate_limited", "Too many requests to the public demo. Wait a minute and try again.")
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=[cors_origin()], allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["Content-Type", "X-Gist-Access-Code"])


@app.exception_handler(GistError)
async def gist_error(_request: Request, error: GistError) -> JSONResponse:
    logger.warning("%s: %s", error.code, error)
    return _error(error.status, error.code, error.public_message)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "Check the supplied query parameters."}})


@app.get("/api/public/status")
def public_status() -> dict:
    """Whether this server is the public demo, and whether visitor AI is available (never reveals the code)."""
    return public.status()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "Gist"}


@app.get("/api/records", response_model=Page, responses={422: {"model": ErrorResponse}})
def records(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
            category: Category | None = None, segment: Segment | None = None,
            query: str | None = Query(None, max_length=200), product_area: Area | None = None,
            sentiment: Sentiment | None = None, feature: str | None = Query(None, max_length=100),
            channel: str | None = Query(None, max_length=50),
            from_date: date | None = None, to_date: date | None = None) -> Page | JSONResponse:
    if from_date and to_date and from_date > to_date:
        return _error(422, "invalid_request", "from_date must be on or before to_date.")
    with connection() as db:
        return list_records(db, page, page_size, category, segment, query.strip() if query else None,
                            product_area=product_area, sentiment=sentiment, feature=feature, channel=channel,
                            from_date=from_date.isoformat() if from_date else None,
                            to_date=to_date.isoformat() if to_date else None)


def _scope(from_date: date | None, to_date: date | None, segment: str | None, product_area: str | None) -> analytics.Scope:
    if from_date and to_date and from_date > to_date:
        raise InvalidRequest("from_date must be on or before to_date.",
                             public_message="from_date must be on or before to_date.")
    return analytics.Scope(from_date.isoformat() if from_date else None, to_date.isoformat() if to_date else None,
                           segment, product_area)


@app.get("/api/analytics/summary", response_model=AnalyticsSummary, responses={422: {"model": ErrorResponse}})
def analytics_summary(from_date: date | None = None, to_date: date | None = None,
                      segment: Segment | None = None, product_area: Area | None = None) -> dict:
    scope = _scope(from_date, to_date, segment, product_area)
    with connection() as db:
        return analytics.summary(db, scope)


@app.get("/api/analytics/trends", response_model=AnalyticsTrends, responses={422: {"model": ErrorResponse}})
def analytics_trends(metric: Literal["feedback", "negative_feedback", "tickets"] = "feedback",
                     group_by: Literal["category", "area", "segment"] | None = None,
                     from_date: date | None = None, to_date: date | None = None,
                     segment: Segment | None = None, product_area: Area | None = None) -> dict:
    scope = _scope(from_date, to_date, segment, product_area)
    with connection() as db:
        return analytics.trends(db, scope, metric, group_by)


@app.get("/api/analytics/releases", response_model=AnalyticsReleases, responses={422: {"model": ErrorResponse}})
def analytics_releases(window_days: int = Query(30, ge=1, le=180), from_date: date | None = None,
                       to_date: date | None = None, segment: Segment | None = None,
                       product_area: Area | None = None) -> dict:
    scope = _scope(from_date, to_date, segment, product_area)
    with connection() as db:
        return analytics.releases(db, scope, window_days)


@app.get("/api/analytics/repeated", response_model=AnalyticsRepeated, responses={422: {"model": ErrorResponse}})
def analytics_repeated(min_count: int = Query(2, ge=2, le=50), limit: int = Query(10, ge=1, le=50),
                       from_date: date | None = None, to_date: date | None = None,
                       segment: Segment | None = None, product_area: Area | None = None) -> dict:
    scope = _scope(from_date, to_date, segment, product_area)
    with connection() as db:
        return analytics.repeated(db, scope, min_count, limit)


@app.get("/api/tickets", response_model=TicketPage, responses={422: {"model": ErrorResponse}})
def tickets(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
            severity: str | None = Query(None, max_length=20), status: str | None = Query(None, max_length=30),
            category: str | None = Query(None, max_length=60), from_date: date | None = None,
            to_date: date | None = None, segment: Segment | None = None, product_area: Area | None = None) -> dict:
    scope = _scope(from_date, to_date, segment, product_area)
    with connection() as db:
        return analytics.list_tickets(db, scope, page, page_size, severity=severity, status=status, category=category)


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
def ask(request: AskRequest, http: Request) -> AskResponse | JSONResponse:
    try:
        if request.mode == "openai" and public.public_mode():
            from .rag.provider import MAX_OUTPUT_TOKENS
            with public.GATE.admit(public.client_ip(http), http.headers.get("x-gist-access-code"),
                                   public.worst_case_usd(1, MAX_OUTPUT_TOKENS)) as spend:
                try:
                    with connection() as db:
                        result = answer(db, request)
                except PaidApiDisabled:
                    spend["usd"] = 0.0          # refused before any call (PaidRequestRejected included)
                    raise
                spend["usd"] = getattr(result, "estimated_cost_usd", 0.0) or 0.0
                return result
        with connection() as db:
            return answer(db, request)
    except PaidRequestRejected as exc:  # subclass of PaidApiDisabled: must come first
        return _error(422, "paid_request_rejected", str(exc))
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


@app.get("/api/issues", response_model=IssueMap)
def issue_map() -> dict:
    with connection() as db:
        data = issues.issue_map(db)
    return {**{k: v for k, v in data.items() if k not in ("sub_themes", "unclustered")},
            "sub_themes": [{k: v for k, v in s.items() if k != "members"} for s in data["sub_themes"]],
            "unclustered_count": len(data["unclustered"])}


@app.get("/api/issues/unclustered", response_model=list[IssueRecord])
def unclustered_issues() -> list[dict]:
    with connection() as db:
        return issues.issue_map(db)["unclustered"]


@app.get("/api/issues/{sub_theme_id}", response_model=SubThemeDetail, responses={404: {"model": ErrorResponse}})
def sub_theme(sub_theme_id: str) -> dict | JSONResponse:
    with connection() as db:
        found = next((s for s in issues.issue_map(db)["sub_themes"] if s["id"] == sub_theme_id), None)
    if not found:
        return _error(404, "not_found", "Sub-theme not found.")
    return found


@app.get("/api/opportunities")
def opportunity_list() -> dict:
    """Evidence-backed opportunity cards (lightweight list; per-record evidence IDs omitted)."""
    with connection() as db:
        data = opportunities.build(db)
    slim = []
    for card in data["opportunities"]:
        evidence = {k: v for k, v in card["evidence"].items() if k not in ("feedback_ids", "linked_tickets")}
        evidence["linked_tickets"] = len(card["evidence"]["linked_tickets"])
        slim.append({**{k: v for k, v in card.items() if k not in ("evidence", "quotes", "assumptions", "unknowns")},
                     "evidence": evidence})
    return {**{k: v for k, v in data.items() if k != "opportunities"}, "opportunities": slim}


@app.get("/api/opportunities/{opportunity_id}", response_model=None, responses={404: {"model": ErrorResponse}})
def opportunity_detail(opportunity_id: str) -> dict | JSONResponse:
    with connection() as db:
        data = opportunities.build(db)
        found = next((c for c in data["opportunities"] if c["id"] == opportunity_id), None)
        if not found:
            return _error(404, "not_found", "Opportunity not found.")
        records = {row[0]: row[1] for row in db.execute(
            f"SELECT id, feedback_text FROM feedback WHERE id IN ({','.join('?' * len(found['evidence']['feedback_ids']))})",
            found["evidence"]["feedback_ids"])}
        tickets = {row[0]: {"subject": row[1], "description": row[2]} for row in db.execute(
            f"SELECT id, subject, description FROM support_tickets WHERE id IN ({','.join('?' * max(1, len(found['evidence']['linked_tickets'])))})",
            [t["id"] for t in found["evidence"]["linked_tickets"]] or [""])}
    return {**found, "confidence_rubric": data["confidence_rubric"], "interpretation": data["interpretation"],
            "evidence": {**found["evidence"],
                         "feedback": [{"id": i, "text": records[i]} for i in found["evidence"]["feedback_ids"]],
                         "linked_tickets": [{**t, **tickets[t["id"]]} for t in found["evidence"]["linked_tickets"]]}}


class WeightsUpdate(BaseModel):
    weights: dict[str, int]


class PriorityInput(BaseModel):
    strategic: Literal["low", "medium", "high"] | None = None
    effort: Literal["S", "M", "L", "XL"] | None = None
    note: str | None = Field(default=None, max_length=priorities.NOTE_LIMIT)


@app.get("/api/priorities")
def priority_table() -> dict:
    """Transparent prioritization: measured parts, weights and PM estimates, labelled separately."""
    with connection() as db:
        cards = opportunities.build(db)["opportunities"]
        return priorities.table(db, cards)


@app.put("/api/priorities/weights")
def priority_weights(body: WeightsUpdate) -> dict:
    public.require_owner_write("Editing priority weights")
    with connection() as db:
        key = priorities.dataset_key(db)
    return {"weights": priorities.set_weights(key, body.weights)}


@app.delete("/api/priorities/weights")
def priority_weights_reset() -> dict:
    public.require_owner_write("Resetting priority weights")
    with connection() as db:
        key = priorities.dataset_key(db)
    return {"weights": priorities.reset_weights(key)}


@app.put("/api/priorities/{opportunity_id}", response_model=None, responses={404: {"model": ErrorResponse}})
def priority_input(opportunity_id: str, body: PriorityInput) -> dict | JSONResponse:
    public.require_owner_write("Editing priority estimates")
    with connection() as db:
        key = priorities.dataset_key(db)
        known = {c["id"] for c in opportunities.build(db)["opportunities"]}
    if opportunity_id not in known:
        return _error(404, "not_found", "Opportunity not found.")
    return priorities.set_input(key, opportunity_id, body.strategic, body.effort, body.note)


@app.get("/api/experiments")
def experiment_list() -> dict:
    """Experiment cards: data facts plus saved, checked AI suggestions (never a live paid call)."""
    with connection() as db:
        return experiments.experiments(db)


@app.get("/api/experiments/{opportunity_id}", response_model=None, responses={404: {"model": ErrorResponse}})
def experiment_detail(opportunity_id: str) -> dict | JSONResponse:
    with connection() as db:
        data = experiments.experiments(db)
    found = next((e for e in data["experiments"] if e["opportunity_id"] == opportunity_id), None)
    if not found:
        return _error(404, "not_found", "Experiment not found.")
    return {**found, "interpretation": data["interpretation"]}


@app.get("/api/evidence")
def evidence_search(q: str = "", kind: str | None = None, product_area: str | None = None, segment: str | None = None,
                    status: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    """Search every indexed source and show where Gist uses it (opportunity evidence, links, triage)."""
    with connection() as db:
        return evidence.search(db, q, kind, product_area, segment, status, page, page_size)


class InvestigationRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    planner: Literal["rules", "model"] = "rules"


@app.post("/api/investigations", response_model=None, responses={503: {"model": ErrorResponse}})
def investigate(body: InvestigationRequest, request: Request) -> dict | JSONResponse:
    """Plan, validate and run a bounded investigation. 'rules' is $0; 'model' needs the server's paid flags
    and adds a model plan and report (two guarded calls). Every run is appended to the audit log.
    In the public demo, 'model' also passes the access-code, rate-limit and daily-cap gate."""
    try:
        if body.planner == "model" and public.public_mode():
            from .rag.provider import INVESTIGATION_MAX_OUTPUT_TOKENS
            worst = public.worst_case_usd(2, INVESTIGATION_MAX_OUTPUT_TOKENS)
            with public.GATE.admit(public.client_ip(request), request.headers.get("x-gist-access-code"), worst) as spend:
                try:
                    entry = investigation_executor.investigate(body.question.strip(), body.planner)
                except PaidApiDisabled:
                    spend["usd"] = 0.0          # refused before any call: release the reservation
                    raise                       # (an uncertain ProviderError keeps the worst case: it may have been billed)
                spend["usd"] = entry.get("cost_usd") or 0.0
                return entry
        return investigation_executor.investigate(body.question.strip(), body.planner)
    except PaidApiDisabled:
        return _error(503, "paid_disabled", "AI investigation is off on this server (no paid-API approval is configured). "
                      "The rule-based mode still works at no cost.")


@app.get("/api/investigations")
def investigation_list() -> dict:
    """Recent investigations and the audit-chain check. The log has no update or delete route."""
    return {"investigations": investigation_log.recent(), "audit": investigation_log.verify()}


@app.get("/api/investigations/{investigation_id}", response_model=None, responses={404: {"model": ErrorResponse}})
def investigation_detail(investigation_id: str) -> dict | JSONResponse:
    found = investigation_log.get(investigation_id)
    return found if found else _error(404, "not_found", "Investigation not found.")


@app.get("/api/eval/benchmarks")
def eval_benchmarks() -> dict:
    """Versioned benchmark results: registry metadata with values read from the result files."""
    return observability.benchmarks()


@app.get("/api/eval/regressions")
def eval_regressions() -> dict:
    return observability.regressions()


@app.get("/api/observability/runtime")
def observability_runtime() -> dict:
    """Spend ledger and investigation audit log, read-only."""
    return {"ledger": observability.ledger_summary(), "investigations": observability.investigation_summary(),
            "billing": observability.billing_vs_ledger()}


class BillingEntry(BaseModel):
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount_usd: float
    source: str = Field(default="owner entry", max_length=120)


@app.put("/api/observability/billing")
def observability_billing(body: BillingEntry) -> dict:
    """Record the provider-billed amount for one UTC day (from the provider's cost export)."""
    public.require_owner_write("Entering billing figures")
    return observability.set_billing(body.day, body.amount_usd, body.source)


class FeedbackEntry(BaseModel):
    target_type: Literal["investigation", "ask"]
    target_id: str = Field(min_length=1, max_length=80)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=observability.COMMENT_LIMIT)


@app.post("/api/feedback")
def feedback(body: FeedbackEntry) -> dict:
    if public.public_mode() and body.comment and body.comment.strip():
        public.require_owner_write("Free-text feedback")       # ratings only in the public demo
    return observability.add_feedback(body.target_type, body.target_id, body.rating, body.comment)


@app.get("/api/feedback")
def feedback_summary() -> dict:
    return observability.feedback_summary()
