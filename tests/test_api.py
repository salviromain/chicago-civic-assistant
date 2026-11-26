"""The HTTP layer: auth, input checks, responses and error mapping. The pipeline is faked."""

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
    yield use
    main.app.dependency_overrides.clear()


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
    monkeypatch.setattr(app.config, "get_settings", lambda: Settings())
    assert answer.estimate_cost(10_000, 500) == 0.0
