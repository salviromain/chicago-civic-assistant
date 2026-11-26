"""Search building blocks: tsvector parsing, BM25, section numbers, and search() wiring.
No database, network or model: those parts are replaced with fakes."""

from collections import Counter

import pytest

from app import retrieval
from app.retrieval import BM25Index, parse_tsvector, section_numbers


def test_parse_tsvector_counts_positions():
    tsv = "'-8':2,9 'heat':4,12,30 'provid':7 'owner''s':5"
    assert parse_tsvector(tsv) == Counter({"heat": 3, "-8": 2, "provid": 1, "owner's": 1})


def test_bm25_prefers_rare_words():
    # "landlord" is in every chunk, "minimum" in one: matching the rare word should win
    docs = {
        "rule": Counter({"minimum": 1, "heat": 1, "owner": 1, "landlord": 1}),
        "rlto1": Counter({"landlord": 3, "tenant": 2}),
        "rlto2": Counter({"landlord": 2, "deposit": 2}),
        "rlto3": Counter({"landlord": 3, "rent": 3}),
    }
    assert BM25Index(docs).search({"minimum", "landlord"})[0] == "rule"


def test_bm25_long_chunk_does_not_win_by_repetition():
    short = Counter({"heat": 2, "rule": 2})
    long = Counter({"heat": 3, **{f"filler{i}": 5 for i in range(60)}})
    other = Counter({"tenant": 4})
    ranking = BM25Index({"short": short, "long": long, "other": other}).search({"heat"})
    assert ranking == ["short", "long"]


def test_section_numbers_in_questions():
    assert section_numbers("What does 14x-8-803.6 require?") == ["14X-8-803.6"]
    assert section_numbers("See 5-12-110(a) and 5-16-010.") == ["5-12-110", "5-16-010"]
    assert section_numbers("Call 311 about 25 potholes in 2026") == []


def test_old_section_numbers_map_to_current_ones():
    assert section_numbers("What does 13-196-410 require?") == ["14X-8-802.2.2"]
    assert section_numbers("Is 13-196-430 in the code?") == ["13-196-430"]  # no mapping: kept, finds nothing


def test_rrf_rewards_agreement_between_lists():
    merged = retrieval.reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"], ["d"]])
    assert merged[:2] == ["a", "b"] or merged[:2] == ["b", "a"]
    assert merged.index("d") < merged.index("c")  # d is in two lists, c in one


@pytest.fixture
def fake_backends(monkeypatch):
    rows = {i: {"id": i, "doc": "d", "kind": "code", "section": i, "title": "t", "parent": None,
                "page": 1, "url": "u", "text": f"text of {i}"} for i in "abcdefg"}
    monkeypatch.setattr(retrieval, "vector_search", lambda q, k=50: ["a", "b", "c"])
    monkeypatch.setattr(retrieval, "bm25_search", lambda q, k=50: ["b", "d", "e"])
    monkeypatch.setattr(retrieval, "section_search", lambda q: [])
    monkeypatch.setattr(retrieval, "fetch_chunks", lambda ids: {i: rows[i] for i in ids})
    # the fake reranker likes "e" best, then "c"
    order = {"e": 3.0, "c": 2.0}
    monkeypatch.setattr(retrieval, "rerank_scores",
                        lambda q, texts: [order.get(t[-1], 0.0) for t in texts])


def test_hybrid_without_rerank_follows_rrf(fake_backends):
    ids = [r["id"] for r in retrieval.search("q", rerank=False, top_k=5)]
    assert ids[0] == "b"  # first or second in both lists
    assert set(ids) == {"a", "b", "c", "d", "e"}


def test_rerank_reorders_candidates(fake_backends):
    results = retrieval.search("q", rerank=True, top_k=2)
    assert [r["id"] for r in results] == ["e", "c"]
    assert results[0]["bm25_rank"] == 3 and results[0]["vector_rank"] is None


def test_keyword_mode_skips_vector_search(fake_backends, monkeypatch):
    monkeypatch.setattr(retrieval, "vector_search", lambda q, k=50: pytest.fail("vector search called"))
    ids = [r["id"] for r in retrieval.search("q", mode="keyword", rerank=False)]
    assert ids == ["b", "d", "e"]


def test_named_section_always_reaches_candidates(fake_backends, monkeypatch):
    monkeypatch.setattr(retrieval, "section_search", lambda q: ["g"])
    ids = [r["id"] for r in retrieval.search("what does g say", rerank=False, candidates=2, top_k=5)]
    assert ids[0] == "g"


def test_unknown_mode_is_an_error():
    with pytest.raises(ValueError):
        retrieval.search("q", mode="magic")


def test_reranker_off_by_default(fake_backends, monkeypatch):
    monkeypatch.setattr(retrieval, "rerank_scores", lambda q, t: pytest.fail("reranker called"))
    assert retrieval.search("q", top_k=1)[0]["rerank_score"] is None


def test_rerank_text_drops_shared_budget_label():
    chunk = {"kind": "budget", "title": "Community Services",
             "text": "2027 Budget Overview (proposed), page 150, Community Services\nLibrary Fund | 99,795,421"}
    assert retrieval.rerank_text(chunk) == "Community Services\nLibrary Fund | 99,795,421"
    code = {"kind": "code", "title": "Heat", "text": "14X-8-802.2.2 Heat to be provided\nbody"}
    assert retrieval.rerank_text(code) == code["text"]
