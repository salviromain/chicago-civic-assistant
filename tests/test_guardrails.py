import pytest

from app.retrieval import reciprocal_rank_fusion
from app.sql_guard import is_safe_select
from evals.run_evals import load_questions, recall_at_k, reciprocal_rank


@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM service_requests_311",
    "with w as (select 1) select * from w;",
])
def test_allows_selects(sql):
    assert is_safe_select(sql)


@pytest.mark.parametrize("sql", [
    "DROP TABLE service_requests_311",
    "SELECT 1; DELETE FROM service_requests_311",
    "UPDATE service_requests_311 SET status = 'x'",
    "select * from t where 1=1; drop table t",
])
def test_blocks_writes(sql):
    assert not is_safe_select(sql)


def test_rrf_rewards_agreement():
    merged = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
    assert set(merged[:2]) == {"a", "b"}


def test_retrieval_metrics():
    assert recall_at_k(["x", "y", "z"], ["z"], k=5) == 1.0
    assert recall_at_k(["x", "y", "z"], ["z"], k=2) == 0.0
    assert reciprocal_rank(["x", "y", "z"], ["y"]) == 0.5


def test_eval_set_is_valid():
    qs = load_questions()
    assert qs
    for q in qs:
        assert {"id", "question", "route", "answerable"} <= q.keys()
        assert q["route"] in {"sql", "docs", "both"}
