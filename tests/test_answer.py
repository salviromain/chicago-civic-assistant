"""Router and answer flow with a fake LLM, fake SQL agent and fake search."""

import datetime as dt
from types import SimpleNamespace

from app import answer as ans
from app.answer import AnswerDraft, link_citations, run
from app.router import RouteDecision
from app.schemas import Citation, Route
from app.sql_agent import SqlResult

TODAY = dt.date(2026, 11, 25)
HEAT = {"id": "14X-8-802.2.2", "doc": "Municipal Code of Chicago, Chapter 14X-8", "kind": "code",
        "section": "14X-8-802.2.2", "title": "Heat to be provided", "page": 1,
        "url": "https://codelibrary.amlegal.com/x", "text": "14X-8-802.2.2 Heat to be provided\nAt least 68°F."}
BUDGET = {"id": "budget-2027-p150-1", "doc": "2027 Budget Overview (proposed)", "kind": "budget",
          "section": None, "title": "Community Services", "page": 150, "url": "https://chicago.gov/b",
          "text": "label\nLibrary Fund | 99,795,421"}
COUNT = SqlResult(question="How many heat violations last winter?", answerable=True,
                  sql="SELECT COUNT(*) FROM building_violations WHERE ...", columns=["count"], rows=[[339]],
                  notes=["Old ordinance 13-196-410"], data_notes=[])


def fake_llm(decision, draft):
    """First call: the router; second call: the answer. Records prompts."""
    replies, prompts = [decision, draft], []

    def generate(prompt, **kw):
        prompts.append(prompt)
        return SimpleNamespace(parsed=replies.pop(0), cached=False, input_tokens=10,
                               output_tokens=5, thinking_tokens=0)
    generate.prompts = prompts
    return generate


def go(decision, draft, sql=COUNT, chunks=(HEAT,)):
    calls = {"sql": [], "search": []}

    def query_tables(q, today, model=None):
        calls["sql"].append(q)
        return sql

    def search(q):
        calls["search"].append(q)
        return list(chunks)
    llm = fake_llm(decision, draft)
    trace = run("q?", TODAY, generate=llm, query_tables=query_tables, search=search)
    return trace, calls, llm


def test_both_route_sends_each_part_to_its_source():
    d = RouteDecision(reasoning="r", route=Route.both, sql_question="How many?", docs_question="What rule?")
    trace, calls, llm = go(d, AnswerDraft(answer="339 violations [T1]. At least 68°F [D1].", refused=False))
    assert calls == {"sql": ["How many?"], "search": ["What rule?"]}
    r = trace.response
    assert r.answer == "339 violations [1]. At least 68°F [2]." and not r.refused
    assert r.citations[0].snippet.startswith("SELECT") and "Building Violations" in r.citations[0].source
    assert r.citations[1].source == "Municipal Code of Chicago, Section 14X-8-802.2.2 (Heat to be provided)"
    assert "[T1]" in llm.prompts[1] and "[D1]" in llm.prompts[1] and "339" in llm.prompts[1]
    assert trace.chunk_ids == ["14X-8-802.2.2"] and trace.llm_calls == 2


def test_docs_route_skips_the_sql_agent():
    d = RouteDecision(reasoning="r", route=Route.docs, docs_question="Library budget?")
    trace, calls, _ = go(d, AnswerDraft(answer="$99,795,421, proposed [D1].", refused=False), chunks=[BUDGET])
    assert calls["sql"] == [] and trace.response.citations[0].source == "2027 Budget Overview (proposed), page 150"


def test_answer_without_valid_citation_becomes_a_refusal():
    d = RouteDecision(reasoning="r", route=Route.docs, docs_question="q")
    trace, _, _ = go(d, AnswerDraft(answer="The mayor is someone [D7].", refused=False))
    assert trace.response.refused and trace.response.answer == ans.REFUSAL and trace.response.citations == []


def test_uncited_refusal_gets_the_sql_agents_reason():
    refused_sql = SqlResult(question="q", answerable=False, refusal_reason="Violations have no ward column.")
    d = RouteDecision(reasoning="r", route=Route.sql)
    trace, _, _ = go(d, AnswerDraft(answer="That isn't recorded.", refused=False), sql=refused_sql)
    assert trace.response.refused and trace.response.answer == ans.REFUSAL + " Violations have no ward column."


def test_model_refusal_keeps_its_reason():
    refused_sql = SqlResult(question="q", answerable=False, refusal_reason="No ward column.")
    d = RouteDecision(reasoning="r", route=Route.sql, sql_question="Violations in ward 25?")
    trace, _, llm = go(d, AnswerDraft(answer="Violations have no ward column.", refused=True), sql=refused_sql)
    assert trace.response.refused and "ward column" in trace.response.answer
    assert "can't answer this: No ward column." in llm.prompts[1]


def test_single_route_uses_the_question_as_asked():
    d = RouteDecision(reasoning="r", route=Route.sql, sql_question="A reworded question?")
    _, calls, _ = go(d, AnswerDraft(answer="339 [T1]", refused=False))
    assert calls["sql"] == ["q?"] and calls["search"] == []


def test_both_route_falls_back_to_the_whole_question():
    d = RouteDecision(reasoning="r", route=Route.both, sql_question="How many?")
    _, calls, _ = go(d, AnswerDraft(answer="339 [T1]", refused=False))
    assert calls == {"sql": ["How many?"], "search": ["q?"]}


def test_old_section_number_is_explained_to_the_model():
    text = ans.docs_source_text([HEAT], "What does 13-196-410 require?")
    assert text.startswith("Note: section 13-196-410 is the old number of today's Section 14X-8-802.2.2.")


def test_link_citations_renumbers_and_drops_unknown_ids():
    avail = {"T1": Citation(source="t"), "D2": Citation(source="d2")}
    text, cites = link_citations("A [D2]. B [T1] [D2]. C [D9].", avail)
    assert text == "A [1]. B [2][1]. C." and [c.source for c in cites] == ["d2", "t"]


def test_several_ids_in_one_bracket():
    avail = {"T1": Citation(source="t"), "D1": Citation(source="d1"), "D4": Citation(source="d4")}
    text, cites = link_citations("Police: $2,243,691,824 [D1, D4]. Count [T1; D9].", avail)
    assert text == "Police: $2,243,691,824 [1][2]. Count [3]." and [c.source for c in cites] == ["d1", "d4", "t"]
    assert ans.cited_ids("x [D1, D4] y [D1] z [T1]") == ["D1", "D4", "T1"]


def test_sql_preview_is_capped_and_cells_cut():
    big = SqlResult(question="list", answerable=True, sql="SELECT x FROM building_violations",
                    columns=["comment"], rows=[["x" * 500]] * 80)
    text = ans.sql_source_text(big)
    assert text.count("\n" + "x" * ans.CELL_CHARS + "…") == ans.PREVIEW_ROWS
    assert "80 rows; first 50 shown" in text


def test_numbers_in_the_table_source_are_tidy():
    r = SqlResult(question="fees", answerable=True, sql="SELECT sum(total_fee) FROM building_permits",
                  columns=["sum", "share", "n", "days"], rows=[[42462228.9200002, 0.36705, 5443, 6.985706]])
    text = ans.sql_source_text(r)
    assert "42,462,228.92 | 0.367 | 5,443 | 6.986" in text
    assert ans._number(8.448800409540189) == "8.449"  # not 8.45, which the answer would round to 8.5
    assert ans._number(3.0) == "3" and ans._number(2989283995) == "2,989,283,995"
