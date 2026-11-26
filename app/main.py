"""FastAPI entry point: run with `uvicorn app.main:app --reload`.

    GET  /health   is the service up, and does the database answer?
    POST /query    {"question": "..."} -> cited answer (X-API-Key header required)

Failures become clear errors, not a bare 500:
    503  the database is down, or the daily Gemini quota is used up
    502  Gemini's reply was unusable (empty, or not the expected JSON), or it kept timing out
    504  the request took longer than request_timeout_s
"""

from __future__ import annotations

import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import ValidationError

from app import __version__
from app.config import Settings, get_settings
from app.llm import QuotaExhausted
from app.schemas import ErrorResponse, HealthResponse, QueryRequest, QueryResponse

log = logging.getLogger("civic")

app = FastAPI(
    title="Chicago Civic Data Assistant",
    version=__version__,
    description="Answers questions about Chicago from city data tables and city documents, with citations.",
)

# Requests run here, so one can be abandoned when it passes its time limit. The
# abandoned work finishes in the background (Python can't stop a thread), but the
# client gets its 504 on time. 4 workers: the free tier allows ~8 Gemini calls a minute.
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="query")


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    # compare_digest takes the same time whether the first or last character differs,
    # so the key can't be guessed one character at a time by timing responses
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.service_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid X-API-Key")


def database_ok() -> bool:
    try:
        from app.db import connect_readonly
        with connect_readonly() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version=__version__, database="ok" if database_ok() else "unavailable")


def error_for(exc: Exception) -> HTTPException | None:
    """Known failures -> the HTTP error the client should see. None = a real bug."""
    import psycopg
    if isinstance(exc, QuotaExhausted):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                             "The daily language-model quota is used up. Try again tomorrow.")
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


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)],
          responses={401: {"model": ErrorResponse}, 502: {"model": ErrorResponse},
                     503: {"model": ErrorResponse}, 504: {"model": ErrorResponse}})
def query(req: QueryRequest, settings: Settings = Depends(get_settings)) -> QueryResponse:
    from app import answer
    job = _pool.submit(answer.answer, req.question)
    try:
        return job.result(timeout=settings.request_timeout_s)
    except FutureTimeout:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT,
                            f"No answer within {settings.request_timeout_s} s. Please try again.") from None
    except Exception as exc:  # noqa: BLE001
        known = error_for(exc)
        if known is None:
            log.exception("query failed: %r", req.question)
            raise
        log.warning("query failed (%s): %s", type(exc).__name__, exc)
        raise known from None
