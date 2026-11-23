"""Document loading: chunking and the embedding cache. No PDFs, network or database."""

from ingest.load_docs import (
    Page,
    approx_tokens,
    budget_heading,
    cache_key,
    chunk_code,
    chunk_fixed,
    clean,
    embed_texts,
    pack,
    rows_from_words,
    strip_budget_furniture,
)

CODE = """CHAPTER 14X-8
HEATING, COOLING, AND MECHANICAL SYSTEMS
14X-8-801   General.
14X-8-802   Heating systems.
14X-8-801 GENERAL.
14X-8-801.1 Scope.
This chapter provides minimum standards.
14X-8-802 HEATING SYSTEMS.
14X-8-802.2 Residential occupancies.
Dwelling units must be provided with permanent heating equipment.
14X-8-802.2.2 Heat to be provided.
Heat from September 15th to June 1st, a minimum temperature of 68ºF at 8:30 a.m.
and thereafter until 10:30 p.m., unless Section
14X-8-802.2.1, which is cited here, says otherwise."""


def code_chunks():
    return {c.id: c for c in chunk_code([Page(1, clean(CODE))], chapter="14X-8")}


def test_code_chunk_ids_are_section_numbers():
    # 801 and 802 have no text of their own: they are parents, not chunks
    assert list(code_chunks()) == ["14X-8-801.1", "14X-8-802.2", "14X-8-802.2.2"]


def test_code_chunk_carries_parents_and_title():
    c = code_chunks()["14X-8-802.2.2"]
    assert c.title == "Heat to be provided"
    assert c.parent == "14X-8-802 Heating systems > 14X-8-802.2 Residential occupancies"
    assert c.text.startswith("14X-8-802 Heating systems > 14X-8-802.2 Residential occupancies > "
                             "14X-8-802.2.2 Heat to be provided\n")


def test_wrapped_section_reference_is_not_a_heading():
    # "14X-8-802.2.1, which is cited here" starts a line but is part of a sentence
    c = code_chunks()["14X-8-802.2.2"]
    assert "which is cited here" in c.text
    assert "14X-8-802.2.1" not in code_chunks()


def test_degree_sign_survives_cleaning():
    assert clean("68ºF") == "68°F"
    assert clean("Diﬀerence") == "Difference"


def test_second_chapter_in_same_file_is_ignored():
    text = CODE + "\nCHAPTER 5-16\n5-16-010   Lease.\n5-16-010 Lease.\n   Text about leases."
    chunks = chunk_code([Page(1, clean(text))], chapter="14X-8")
    assert "Text about leases" not in chunks[-1].text


def test_long_section_is_split_into_parts():
    para = "   (a) " + "word " * 300
    text = "CHAPTER 5-12\n5-12-110   Tenant remedies.\n5-12-110 Tenant remedies.\n" + "\n".join([para] * 4)
    chunks = chunk_code([Page(1, text)], chapter="5-12", max_tokens=800)
    assert [c.id for c in chunks] == ["5-12-110#1", "5-12-110#2"]
    assert all(c.section == "5-12-110" for c in chunks)
    assert "(part 1 of 2)" in chunks[0].text


def test_pack_respects_size_and_overlap():
    paras = [f"p{i} " + "w " * 70 for i in range(10)]  # ~92 tokens each
    chunks = pack(paras, max_tokens=300, overlap_tokens=100)
    assert all(approx_tokens(c) <= 300 for c in chunks)
    # the last paragraph of a chunk is repeated at the start of the next
    first_last = chunks[0].split("\n\n")[-1]
    assert chunks[1].startswith(first_last)


def test_chunk_fixed_splits_a_huge_paragraph():
    chunks = chunk_fixed("word " * 2000, max_tokens=500, overlap_tokens=0)
    assert len(chunks) >= 5 and all(approx_tokens(c) <= 500 for c in chunks)


def test_rows_from_words_keeps_numbers_next_to_labels():
    # (x0, y0, x1, y1, text): one row, a wide gap between label and number
    words = [(10, 100, 40, 110, "Library"), (42, 100, 70, 110, "Fund"), (200, 100, 260, 110, "99,795,421"),
             (10, 120, 50, 130, "Total"), (200, 120, 260, 130, "$130,783,421")]
    assert rows_from_words(words) == ["Library Fund | 99,795,421", "Total | $130,783,421"]


def test_budget_furniture_removed():
    text = "2027 BUDGET OVERVIEW FINANCIAL SUMMARIES\n\nReal paragraph.\n\n43"
    assert strip_budget_furniture(text, 43) == "Real paragraph."


def test_budget_heading_from_table_of_contents():
    toc = [(36, 1, "Budget at a Glance"), (37, 2, "Budget Process"), (39, 2, "Where the Money Goes"),
           (40, 1, "Financial Summaries")]
    assert budget_heading(toc, 39) == "Budget at a Glance > Where the Money Goes"
    assert budget_heading(toc, 40) == "Financial Summaries"


def test_cache_key_changes_with_settings():
    base = cache_key("gemini-embedding-001", 768, "RETRIEVAL_DOCUMENT", "text")
    assert base != cache_key("gemini-embedding-001", 3072, "RETRIEVAL_DOCUMENT", "text")
    assert base != cache_key("gemini-embedding-001", 768, "RETRIEVAL_QUERY", "text")
    assert base != cache_key("other-model", 768, "RETRIEVAL_DOCUMENT", "text")


def test_embed_texts_uses_cache_on_second_run(tmp_path, monkeypatch):
    from ingest import load_docs

    calls = []

    def fake_embed(client, model, dims, task, texts, attempts=6):  # noqa: ARG001
        calls.append(len(texts))
        return [[3.0, 4.0] for _ in texts]

    monkeypatch.setattr(load_docs, "_embed_with_retry", fake_embed)
    args = dict(model="m", dims=2, task="RETRIEVAL_DOCUMENT", api_key=None, cache_dir=tmp_path, client=object())
    vectors, n = embed_texts(["a", "b"], **args)
    assert n == 1 and vectors[0] == [0.6, 0.8]  # normalized to length 1
    vectors, n = embed_texts(["a", "b"], **args)
    assert n == 0 and calls == [2]  # second run: everything from the cache


def test_token_batches_split_by_size():
    from ingest.load_docs import token_batches
    texts = ["w " * 3000, "w " * 3000, "w " * 3000, "short"]  # ~3,900 tokens each
    assert token_batches(texts, [0, 1, 2, 3], max_tokens=8000) == [[0, 1], [2, 3]]


def test_minute_budget_waits_instead_of_overspending():
    from ingest.load_docs import MinuteBudget
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

    from ingest import load_docs

    class Client:
        class models:
            @staticmethod
            def embed_content(**kwargs):
                raise errors.ClientError(429, {"error": {"code": 429, "message": "quota",
                    "details": [{"violations": [{"quotaId": "EmbedContentRequestsPerDayPerProject"}]}]}})

    monkeypatch.setattr(load_docs.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept")))
    with pytest.raises(SystemExit, match="daily embedding quota"):
        load_docs._embed_with_retry(Client, "m", 8, "RETRIEVAL_DOCUMENT", ["x"])
