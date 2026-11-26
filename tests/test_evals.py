"""The eval set's shape, and the answer matcher the harness uses (Day 9)."""

from collections import Counter

from evals.build_questions import dec, money, num
from evals.run_evals import contains, load_questions, must_contain_ok


def test_numbers_match_as_whole_numbers():
    assert contains("It takes 3 days.", "3")
    assert not contains("2,032 permits in 13 wards", "3")
    assert contains("There were 5,443 requests", "5443") and contains("5443 requests", "5,443")
    assert contains("About 36.7% were duplicates.", "36.7") and not contains("136.7", "36.7")
    assert contains("$2,243,691,824 (proposed)", "2,243,691,824")
    assert contains("Ward 32.", "32")  # a full stop after a number is not a decimal


def test_text_matches_ignore_case():
    assert contains("The busiest month was march.", "March")
    assert contains("about $2.24 billion", "2.24 billion")


def test_must_contain_needs_every_group():
    groups = [["164"], ["September 15", "Sept. 15"]]
    assert must_contain_ok("164 violations; heat from September 15 to June 1.", groups)
    assert not must_contain_ok("164 violations.", groups)


def test_number_variants():
    assert num(5443) == ["5,443", "5443"]
    assert dec(6.9857) == ["7", "7.0"] and dec(0.4934) == ["0.49", "0.5"]
    assert "9.5 million" in money(9530803) and "10 million" not in money(9530803)
    assert {"2.24 billion", "2,243,691,824"} <= set(money(2243691824))


def test_eval_set_shape():
    qs = load_questions()
    assert len(qs) >= 80 and len({q["id"] for q in qs}) == len(qs)
    kinds = Counter(q["route"] if q["answerable"] else "unanswerable" for q in qs)
    assert kinds["sql"] >= 25 and kinds["docs"] >= 25 and kinds["both"] >= 8 and kinds["unanswerable"] >= 8
    for q in qs:
        assert q["route"] in {"sql", "docs", "both"} and q["as_of"] == "2026-11-25"
        if q["answerable"]:
            assert q["answer_must_contain"], q["id"]
            assert bool(q["reference_sql"]) == (q["route"] in {"sql", "both"}), q["id"]
            assert bool(q["source_chunks"]) == (q["route"] in {"docs", "both"}), q["id"]
        else:
            assert not q["reference_sql"] and q["reference_answer"], q["id"]


def test_reference_answers_pass_their_own_checks():
    for q in load_questions():
        if q["answerable"]:
            assert must_contain_ok(q["reference_answer"], q["answer_must_contain"]), q["id"]
