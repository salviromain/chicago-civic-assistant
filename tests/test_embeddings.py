"""Embeddings: cache, batching, pacing and quota handling. No network."""

from app.embeddings import cache_key, embed_texts


def test_cache_key_changes_with_settings():
    base = cache_key("gemini-embedding-001", 768, "RETRIEVAL_DOCUMENT", "text")
    assert base != cache_key("gemini-embedding-001", 3072, "RETRIEVAL_DOCUMENT", "text")
    assert base != cache_key("gemini-embedding-001", 768, "RETRIEVAL_QUERY", "text")
    assert base != cache_key("other-model", 768, "RETRIEVAL_DOCUMENT", "text")


def test_embed_texts_uses_cache_on_second_run(tmp_path, monkeypatch):
    from app import embeddings

    calls = []

    def fake_embed(client, model, dims, task, texts, attempts=6):  # noqa: ARG001
        calls.append(len(texts))
        return [[3.0, 4.0] for _ in texts]

    monkeypatch.setattr(embeddings, "_embed_with_retry", fake_embed)
    args = dict(model="m", dims=2, task="RETRIEVAL_DOCUMENT", api_key=None, cache_dir=tmp_path, client=object())
    vectors, n = embed_texts(["a", "b"], **args)
    assert n == 1 and vectors[0] == [0.6, 0.8]  # normalized to length 1
    vectors, n = embed_texts(["a", "b"], **args)
    assert n == 0 and calls == [2]  # second run: everything from the cache


def test_token_batches_split_by_size():
    from app.embeddings import token_batches
    texts = ["w " * 3000, "w " * 3000, "w " * 3000, "short"]  # ~3,900 tokens each
    assert token_batches(texts, [0, 1, 2, 3], max_tokens=8000) == [[0, 1], [2, 3]]


def test_minute_budget_waits_instead_of_overspending():
    from app.embeddings import MinuteBudget
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    budget = MinuteBudget(per_minute=10_000, clock=lambda: now[0], sleep=sleep)
    budget.wait_for(6_000)
    budget.wait_for(6_000)  # would make 12,000 in one minute: must wait for the first to age out
    assert slept and now[0] >= 60


def test_daily_quota_stops_immediately(monkeypatch):
    import pytest
    from google.genai import errors

    from app import embeddings

    class Client:
        class models:
            @staticmethod
            def embed_content(**kwargs):
                raise errors.ClientError(429, {"error": {"code": 429, "message": "quota",
                    "details": [{"violations": [{"quotaId": "EmbedContentRequestsPerDayPerProject"}]}]}})

    monkeypatch.setattr(embeddings.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept")))
    with pytest.raises(SystemExit, match="daily embedding quota"):
        embeddings._embed_with_retry(Client, "m", 8, "RETRIEVAL_DOCUMENT", ["x"])
