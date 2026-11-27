"""The HTTP layer: auth, input checks, rate limits, logs, responses and error mapping.
The pipeline is faked."""

import json
import logging
import time

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import answer, main
from app.config import Settings, get_settings
from app.llm import QuotaExhausted
from app.schemas import Citation, QueryResponse, Route

client = TestClient(main.app, raise_server_exceptions=False)
KEY = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def settings():
    """The tests' own settings, whatever .env contains."""
    def use(**overrides):
        main.app.dependency_overrides[get_settings] = lambda: Settings(service_api_key="test-key", **overrides)
    use()
    main.limiter.reset()  # every test client has the same address: start each test with no history
    yield use
    main.app.dependency_overrides.clear()


@pytest.fixture
def log_lines():
    """The JSON lines the app logs during the test."""
    lines = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(json.loads(main.logs.JsonFormatter().format(record)))
    handler = Keep()
    main.log.addHandler(handler)
    yield lines
    main.log.removeHandler(handler)


GOOD = QueryResponse(answer="721 pothole complaints [1].", route=Route.sql, latency_ms=12,
                     citations=[Citation(source="Chicago Data Portal: 311 Service Requests",
                                         snippet="SELECT COUNT(*) ...")])


@pytest.fixture
def pipeline(monkeypatch):
    """Replace answer.answer; set `pipeline.result` to a response or an exception."""
    class P:
        result = GOOD

    def fake(question):
        if isinstance(P.result, Exception):
            raise P.result
        if callable(P.result):
            return P.result()
        return P.result
    monkeypatch.setattr(answer, "answer", fake)
    return P


def ask(question="How many potholes in ward 25 in 2026?", headers=KEY):
    return client.post("/query", json={"question": question}, headers=headers)


def test_health_reports_the_database(monkeypatch):
    monkeypatch.setattr(main, "database_ok", lambda: False)
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["database"] == "unavailable"


def test_query_requires_api_key(pipeline):
    assert ask(headers={}).status_code == 401
    assert ask(headers={"X-API-Key": "wrong"}).status_code == 401


def test_query_validates_input(pipeline):
    assert ask("x").status_code == 422
    assert ask("q" * 1001).status_code == 422


def test_query_returns_the_answer(pipeline):
    r = ask()
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].startswith("721") and body["route"] == "sql"
    assert body["citations"][0]["snippet"].startswith("SELECT")
    assert set(body["usage"]) == {"llm_calls", "input_tokens", "output_tokens"}


class Shape(BaseModel):
    x: int


@pytest.mark.parametrize("error, code, words", [
    (QuotaExhausted("PerDay"), 503, "quota"),
    (psycopg.OperationalError("connection refused"), 503, "database"),
    (RuntimeError("gemini-3.1-flash-lite returned an empty reply"), 502, "no usable answer"),
    (type("ReadTimeout", (Exception,), {})("timed out"), 502, "no usable answer"),
])
def test_known_failures_become_clear_errors(pipeline, error, code, words):
    pipeline.result = error
    r = ask()
    assert r.status_code == code and words in r.json()["detail"]


def test_bad_llm_json_is_a_502(pipeline):
    try:
        Shape.model_validate_json('{"x": "lots"}')
    except Exception as e:  # a real pydantic ValidationError
        pipeline.result = e
    r = ask()
    assert r.status_code == 502


def test_unknown_bug_is_a_500(pipeline):
    pipeline.result = KeyError("bug")
    assert ask().status_code == 500


def test_slow_request_gets_a_504(pipeline, settings):
    settings(request_timeout_s=1)
    pipeline.result = lambda: (time.sleep(2), GOOD)[1]
    r = ask()
    assert r.status_code == 504 and "1 s" in r.json()["detail"]


def test_cost_estimate_uses_configured_prices(monkeypatch):
    import app.config
    monkeypatch.setattr(app.config, "get_settings",
                        lambda: Settings(llm_usd_per_m_input=0.10, llm_usd_per_m_output=0.40))
    assert answer.estimate_cost(10_000, 500) == pytest.approx(0.0012)
    monkeypatch.setattr(app.config, "get_settings", lambda: Settings(llm_usd_per_m_input=0, llm_usd_per_m_output=0))
    assert answer.estimate_cost(10_000, 500) == 0.0


def test_too_many_questions_get_a_429_with_retry_after(pipeline, settings):
    settings(rate_limit_per_minute=2)
    assert [ask().status_code for _ in range(3)] == [200, 200, 429]
    r = ask()
    assert r.status_code == 429 and "2 a minute" in r.json()["detail"]
    assert 1 <= int(r.headers["Retry-After"]) <= 61


def test_requests_with_a_wrong_key_dont_use_the_limit(pipeline, settings):
    settings(rate_limit_per_minute=1)
    for _ in range(3):
        assert ask(headers={"X-API-Key": "wrong"}).status_code == 401
    assert ask().status_code == 200


def test_service_wide_daily_limit(pipeline, settings):
    settings(rate_limit_total_per_day=1)
    assert ask().status_code == 200
    r = ask()
    assert r.status_code == 429 and "service's daily limit" in r.json()["detail"]


def test_quota_503_says_when_to_retry(pipeline):
    pipeline.result = QuotaExhausted("PerDay")
    r = ask()
    assert r.status_code == 503 and "midnight Pacific" in r.json()["detail"]
    assert 0 < int(r.headers["Retry-After"]) <= 25 * 3600


def test_each_query_logs_one_json_line(pipeline, log_lines):
    r = ask()
    [line] = [l for l in log_lines if l["message"] == "query"]
    assert line["request_id"] == r.headers["X-Request-ID"]
    assert line["status"] == 200 and line["severity"] == "INFO" and line["route"] == "sql"
    assert {"latency_ms", "llm_calls", "input_tokens", "output_tokens", "cost_usd", "client"} <= set(line)
    assert "question" not in line and line["question_chars"] == len("How many potholes in ward 25 in 2026?")
    assert line["client"] != "testclient"  # a salted hash, not the address


def test_failed_queries_are_logged_with_the_error(pipeline, log_lines):
    pipeline.result = QuotaExhausted("PerDay")
    ask()
    [line] = [l for l in log_lines if l["message"] == "query"]
    assert line["status"] == 503 and line["severity"] == "ERROR" and line["error"] == "QuotaExhausted"


def test_questions_are_logged_only_when_switched_on(pipeline, settings, log_lines):
    settings(log_questions=True)
    ask("Is the question kept?")
    assert [l for l in log_lines if l["message"] == "query"][0]["question"] == "Is the question kept?"


def test_the_page_is_served_with_a_strict_content_policy():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "<title>Chicago Civic Data Assistant</title>" in r.text
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert "connect-src 'self'" in r.headers["Content-Security-Policy"]
    # Nothing from the server is inserted as HTML: answers and sources go in as text
    assert "innerHTML" not in r.text
