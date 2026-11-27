"""FastAPI entry point: run with `uvicorn app.main:app --reload`.

    GET  /         a web page to ask questions (app/static/index.html)
    GET  /health   is the service up, and does the database answer?
    POST /query    {"question": "..."} -> cited answer (X-API-Key header required)

Failures become clear errors, not a bare 500:
    429  too many questions from this client, or for the service today (Retry-After says when)
    503  the database is down, or the daily Gemini quota is used up
    502  Gemini's reply was unusable (empty, or not the expected JSON), or it kept timing out
    504  the request took longer than request_timeout_s
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app import __version__, logs
from app.config import Settings, get_settings
from app.llm import QuotaExhausted
from app.ratelimit import RateLimiter, client_address, seconds_until_pacific_midnight
from app.schemas import ErrorResponse, HealthResponse, QueryRequest, QueryResponse

log = logs.setup()
limiter = RateLimiter()
# Logs show a client as a short hash, not its IP address. The salt is new at every
# start, so the hash links one client's requests without being reversible to an IP.
_SALT = os.urandom(16)

app = FastAPI(
    title="Chicago Civic Data Assistant",
    version=__version__,
    description="Answers questions about Chicago from city data tables and city documents, with citations.",
)

# Requests run here, so one can be abandoned when it passes its time limit. The
# abandoned work finishes in the background (Python can't stop a thread), but the
# client gets its 504 on time. 4 workers: the free tier allows ~8 Gemini calls a minute.
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="query")


def client_tag(client: str) -> str:
    return hashlib.sha256(_SALT + client.encode()).hexdigest()[:12]


@app.middleware("http")
async def log_queries(request: Request, call_next):
    """One JSON log line per /query: status, latency, tokens, cost (app/logs.py).
    Every response carries an X-Request-ID that matches its log line."""
    request_id = uuid.uuid4().hex[:16]
    request.state.log = {}
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        if request.url.path == "/query":
            client = getattr(request.state, "client", None)
            fields = {"request_id": request_id, "status": status_code,
                      "latency_ms": round((time.perf_counter() - start) * 1000),
                      "client": client_tag(client) if client else None, **request.state.log}
            log.log(logs.level_for(status_code), "query", extra={"fields": fields})


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    # compare_digest takes the same time whether the first or last character differs,
    # so the key can't be guessed one character at a time by timing responses
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.service_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid X-API-Key")


def rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """429 past the per-client or per-service limits (app/ratelimit.py), after the key check."""
    client = client_address(request.client.host if request.client else None,
                            request.headers.get("x-forwarded-for"), settings.trusted_proxies)
    request.state.client = client
    limited = limiter.check(client, per_minute=settings.rate_limit_per_minute,
                            per_day=settings.rate_limit_per_day,
                            total_per_day=settings.rate_limit_total_per_day)
    if limited:
        request.state.log["error"] = "rate_limited"
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, limited.reason,
                            headers={"Retry-After": str(limited.retry_after_s)})


def database_ok() -> bool:
    try:
        from app.db import connect_readonly
        with connect_readonly() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False


PAGE = Path(__file__).parent / "static" / "index.html"
# The page uses only its own inline style and script and calls only this service:
# the browser refuses anything else (scripts or frames from other sites)
PAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                               "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def page() -> HTMLResponse:
    return HTMLResponse(PAGE.read_text(), headers=PAGE_HEADERS)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version=__version__, database="ok" if database_ok() else "unavailable")


def error_for(exc: Exception) -> HTTPException | None:
    """Known failures -> the HTTP error the client should see. None = a real bug."""
    import psycopg
    if isinstance(exc, QuotaExhausted):
        # Gemini's daily quota resets at midnight Pacific time
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                             "The daily language-model quota is used up. "
                             "It resets at midnight Pacific time; please try again then.",
                             headers={"Retry-After": str(seconds_until_pacific_midnight(time.time()))})
    if isinstance(exc, psycopg.OperationalError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The database is unavailable.")
    if isinstance(exc, ValidationError) or "timeout" in type(exc).__name__.lower() or \
            (isinstance(exc, RuntimeError) and "empty reply" in str(exc)):
        return HTTPException(status.HTTP_502_BAD_GATEWAY,
                             "The language model gave no usable answer. Please try again.")
    try:
        from google.genai import errors
        if isinstance(exc, errors.APIError):
            return HTTPException(status.HTTP_502_BAD_GATEWAY,
                                 f"The language model service failed ({exc.code}). Please try again.")
    except ImportError:
        pass
    return None


@app.post("/query", response_model=QueryResponse,
          dependencies=[Depends(require_api_key), Depends(rate_limit)],
          responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse},
                     502: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
                     504: {"model": ErrorResponse}})
def query(req: QueryRequest, request: Request, settings: Settings = Depends(get_settings)) -> QueryResponse:
    from app import answer
    fields = request.state.log
    fields["question_chars"] = len(req.question)
    if settings.log_questions:
        fields["question"] = req.question
    job = _pool.submit(answer.answer, req.question)
    try:
        resp = job.result(timeout=settings.request_timeout_s)
    except FutureTimeout:
        fields["error"] = "timeout"
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT,
                            f"No answer within {settings.request_timeout_s} s. Please try again.") from None
    except Exception as exc:  # noqa: BLE001
        fields["error"] = type(exc).__name__
        known = error_for(exc)
        if known is None:
            log.exception("query failed", extra={"fields": {"error": type(exc).__name__}})
            raise
        raise known from None
    fields.update(route=resp.route.value, refused=resp.refused, pipeline_ms=resp.latency_ms,
                  llm_calls=resp.usage.llm_calls, input_tokens=resp.usage.input_tokens,
                  output_tokens=resp.usage.output_tokens, cost_usd=resp.cost_usd)
    return resp
