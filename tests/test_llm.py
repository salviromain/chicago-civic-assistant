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
