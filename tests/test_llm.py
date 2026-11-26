"""The Gemini wrapper: cache, structured output, retries. A fake client stands in for the API."""

from types import SimpleNamespace

import pytest
from google.genai import errors
from pydantic import BaseModel

from app import llm


class Answer(BaseModel):
    count: int


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)  # strings, or exceptions to raise
        self.calls = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        usage = SimpleNamespace(prompt_token_count=100, candidates_token_count=5,
                                thoughts_token_count=20)
        return SimpleNamespace(text=reply, usage_metadata=usage)


class NoWait:
    def wait_for(self, n):
        pass


def ask(tmp_path, client, prompt="How many?", **kw):
    return llm.generate(prompt, model="m", cache_dir=tmp_path, client=client, budget=NoWait(), **kw)


def test_second_identical_call_comes_from_cache(tmp_path):
    client = FakeClient(['{"count": 721}'])
    first = ask(tmp_path, client, schema=Answer)
    second = ask(tmp_path, client, schema=Answer)
    assert len(client.calls) == 1
    assert first.parsed == second.parsed == Answer(count=721)
    assert not first.cached and second.cached
    assert second.input_tokens == 100 and second.thinking_tokens == 20


def test_different_prompt_or_system_is_a_new_call(tmp_path):
    client = FakeClient(["a", "b", "c"])
    ask(tmp_path, client)
    ask(tmp_path, client, prompt="Other?")
    ask(tmp_path, client, system="Be brief.")
    assert len(client.calls) == 3


def test_schema_sets_json_output(tmp_path):
    client = FakeClient(['{"count": 1}'])
    ask(tmp_path, client, schema=Answer)
    config = client.calls[0][2]
    assert config.response_mime_type == "application/json" and config.response_schema is Answer
    assert config.temperature == 0.0


def test_rate_limit_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    minute = errors.ClientError(429, {"error": {"code": 429, "message": "slow down", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}]}})
    client = FakeClient([minute, "ok"])
    assert ask(tmp_path, client).text == "ok"
    assert len(client.calls) == 2


def test_daily_quota_stops_at_once(tmp_path):
    day = errors.ClientError(429, {"error": {"code": 429, "message": "quota", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
    client = FakeClient([day, "never reached"])
    with pytest.raises(llm.QuotaExhausted):
        ask(tmp_path, client)
    assert len(client.calls) == 1


def test_bad_request_is_not_retried(tmp_path):
    client = FakeClient([errors.ClientError(400, {"error": {"code": 400, "message": "bad"}}), "x"])
    with pytest.raises(errors.ClientError):
        ask(tmp_path, client)
    assert len(client.calls) == 1


def test_bad_reply_is_not_cached(tmp_path):
    from pydantic import ValidationError
    client = FakeClient(['{"count": "lots"', '{"count": 3}'])  # cut-off JSON, then a good reply
    with pytest.raises(ValidationError):
        ask(tmp_path, client, schema=Answer)
    assert list(tmp_path.iterdir()) == []
    assert ask(tmp_path, client, schema=Answer).parsed == Answer(count=3)


def test_empty_reply_is_an_error_not_a_cache_entry(tmp_path):
    with pytest.raises(RuntimeError, match="empty reply"):
        ask(tmp_path, FakeClient([""]))
    assert list(tmp_path.iterdir()) == []


def test_cache_is_in_the_project_folder():
    from app.config import PROJECT_ROOT
    assert llm.CACHE_DIR == PROJECT_ROOT / "data" / "cache" / "llm" and llm.CACHE_DIR.is_absolute()


class ReadTimeout(Exception):
    """Same name as httpx's timeout error."""


def test_stalled_call_is_retried_at_once(tmp_path, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: pytest.fail("no waiting after a timeout"))
    client = FakeClient([ReadTimeout("read timed out"), "ok"])
    assert ask(tmp_path, client).text == "ok" and len(client.calls) == 2


def test_timeouts_give_up_after_three_tries(tmp_path):
    client = FakeClient([ReadTimeout("t")] * 3 + ["never"])
    with pytest.raises(ReadTimeout):
        ask(tmp_path, client)
    assert len(client.calls) == 3


def test_rate_limit_still_retried_after_reordering(tmp_path, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    client = FakeClient([errors.ServerError(503, {"error": {"code": 503, "message": "busy"}}), "ok"])
    assert ask(tmp_path, client).text == "ok"
