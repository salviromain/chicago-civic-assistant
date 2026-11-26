"""The eval set's shape, and the answer matcher the harness uses (Day 9)."""

from collections import Counter

from evals.build_questions import dec, money, num
from evals.run_evals import citation_ok, contains, load_questions, must_contain_ok, sql_matches, summarize


def test_numbers_match_as_whole_numbers():
    assert contains("It takes 3 days.", "3")
    assert not contains("2,032 permits in 13 wards", "3")
    assert contains("There were 5,443 requests", "5443") and contains("5443 requests", "5,443")
    assert contains("About 36.7% were duplicates.", "36.7") and not contains("136.7", "36.7")
    assert contains("$2,243,691,824 (proposed)", "2,243,691,824")
    assert contains("Ward 32.", "32")  # a full stop after a number is not a decimal
    assert contains("no more than $10.00 a month", "10") and contains("$500.00", "500")
    assert not contains("10.5 days", "10")


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



def test_sql_match_allows_extra_columns_and_rounding():
    assert sql_matches([[721]], [[721]])
    assert sql_matches([["Streets and Sanitation", 409928]], [["Streets and Sanitation", 483252]])  # key = first value
    assert sql_matches([[2989283995]], [[2989283995, 1460, 1460]])  # later reference columns are context
    assert sql_matches([[6.9857]], [[6.99]])          # both round to 7.0
    assert sql_matches([[0.36705]], [[36.7]])         # a share as a fraction
    assert not sql_matches([[718]], [[721]])
    assert not sql_matches([[0.7957]], [[75.8]])
    assert not sql_matches([], [[721]])


def test_sql_match_accepts_either_side_of_a_tie():
    ref = [["501 E 32ND ST", 4], ["5110 S DR MARTIN L KING JR DR", 4], ["1407 E 71ST PL", 3]]
    assert sql_matches([["5110 S DR MARTIN L KING JR DR", 4]], ref, tie=True)
    assert not sql_matches([["1407 E 71ST PL", 3]], ref, tie=True)
    assert not sql_matches([["5110 S DR MARTIN L KING JR DR", 4]], ref, tie=False)


def test_citation_needs_the_right_kind_of_source():
    both = {"route": "both", "source_chunks": ["14X-8-802.2.2"]}
    assert citation_ok(both, ["T1", "14X-8-802.2.2"])
    assert not citation_ok(both, ["T1", "5-12-110#1"])
    assert citation_ok({"route": "sql", "source_chunks": []}, ["T1"])


def test_summary_rates():
    recs = [
        {"answerable": True, "refused": False, "route_ok": True, "checks_ok": True, "citation_ok": True,
         "llm_calls": 2, "latency_ms": 2000, "tokens": 100, "cost_usd": 0.0, "recall@5": 1.0, "rr": 0.5,
         "judge": {"faithful": True, "correctness": "correct"}},
        {"answerable": True, "refused": True, "route_ok": False, "checks_ok": False, "citation_ok": False,
         "llm_calls": 0, "latency_ms": 10, "tokens": 50, "cost_usd": 0.0,
         "judge": {"faithful": True, "correctness": "incorrect"}},
        {"answerable": False, "refused": True, "route_ok": True, "refusal_ok": True,
         "llm_calls": 3, "latency_ms": 4000, "tokens": 90, "cost_usd": 0.0},
    ]
    s = summarize(recs)
    assert s["router_accuracy"] == (2 / 3, 3) and s["answer_checks"] == (0.5, 2)
    assert s["false_refusals"] == (0.5, 2) and s["correct_refusals"] == (1.0, 1)
    assert s["faithfulness"] == (1.0, 1)          # refusals aren't judged for faithfulness
    assert s["correctness_judge"] == (0.5, 2)
    assert s["latency_measured_on"] == 2          # the cached question isn't timed
    assert s["mrr"] == (0.5, 1)
