"""Runs the whole flow and writes the cited answer. (Day 6)

    answer("How many heat violations were recorded last winter, and what must landlords provide?")
    -> QueryResponse(answer="... 339 heat violations [1] ... at least 68°F ... [2]",
                     route="both", citations=[<table + SQL>, <14X-8-802.2.2>], refused=False)

Steps:
1. Router: sql, docs or both (both = two sub-questions).
2. Sources, in parallel: the SQL agent (rows + notes) and/or hybrid search (5 chunks).
3. Each source gets an id: T1 for the table result, D1..D5 for the chunks. Gemini
   writes the answer from those sources only, citing ids inline ([T1], [D2]).
4. Code, not the model, builds the citations: ids that don't exist are dropped, the
   inline ids become [1], [2] in citation order, and an answer that cites nothing
   it was given becomes a refusal.

run(question) returns a Trace with everything (route, SQL, chunk ids) for the evals;
answer(question) returns just the API response.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.router import RouteDecision, route_question
from app.schemas import Citation, QueryResponse, Usage
from app.sql_agent import SqlResult

PREVIEW_ROWS = 50     # rows of a SQL result shown to the answer model
CELL_CHARS = 200      # long text cells (inspector comments) are cut to this
SNIPPET_CHARS = 300   # chunk text kept in a citation

DATASETS = {  # table -> (name, portal URL)
    "service_requests_311": ("311 Service Requests", "https://data.cityofchicago.org/d/v6vf-nfxy"),
    "building_violations": ("Building Violations", "https://data.cityofchicago.org/d/22u3-xenr"),
    "building_permits": ("Building Permits", "https://data.cityofchicago.org/d/ydr8-5enu"),
}
REFUSAL = "I can't answer that from the city data and documents I have."


class AnswerDraft(BaseModel):
    answer: str = Field(description="The answer, citing source ids inline like [T1] or [D2].")
    refused: bool = Field(description="True if the sources don't answer the question at all.")


SYSTEM = """You answer questions about Chicago using ONLY the sources given (table results
[T1] and document excerpts [D1], [D2], ...). Never use outside knowledge.

- Cite every claim with the id of the source it comes from, right after it: "... 339 heat
  violations [T1]." Use only ids that appear in the sources.
- Numbers: copy them exactly from the table rows. Don't compute new figures beyond simple
  ones (a sum or difference of numbers shown); never estimate.
- Table results: mention the filters and limits in its notes that change the meaning
  (duplicates excluded, date range, "the data ends on ..."). Prefer the code-checked notes.
  Zero rows means none were recorded in this data, not that none exist.
- If the table source says the tables can't answer, say why in one sentence.
- Documents: say what the section requires and name it ("Section 14X-8-802.2.2").
  Excerpts from the 2027 budget are a PROPOSED budget, not adopted: always say "proposed".
- Building violations cite the old ordinance number 13-196-410 for heat; the current rule
  is 14X-8-802.2.2. Don't name current sections for other old numbers.
- If the sources don't answer the question, set refused=true and say briefly what's missing.
  If they answer only part of it, answer that part and say what's missing.
- Be brief: 1 to 4 sentences, plain language. Not legal advice; don't add disclaimers.
"""


@dataclass
class Trace:
    question: str
    response: QueryResponse
    decision: RouteDecision | None = None
    sql: SqlResult | None = None
    chunks: list[dict] = field(default_factory=list)
    sources_text: str = ""
    draft: AnswerDraft | None = None
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    timings_ms: dict[str, int] = field(default_factory=dict)  # route, sources, answer, waited
    cited: list[str] = field(default_factory=list)  # what the answer cited: "T1" or chunk ids

    @property
    def chunk_ids(self) -> list[str]:
        return [c["id"] for c in self.chunks]


# ---------------------------------------------------------------------------
# Sources -> prompt text


def _cell(value) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= CELL_CHARS else text[:CELL_CHARS] + "…"


def sql_source_text(r: SqlResult) -> str:
    lines = [f"[T1] City data tables. Question asked: {r.question}"]
    if not r.answerable:
        lines.append(f"The tables can't answer this: {r.refusal_reason}")
        return "\n".join(lines)
    if r.error:
        lines.append(f"The query failed: {r.error}. No data.")
        return "\n".join(lines)
    lines.append(f"SQL: {r.sql}")
    lines.append("Columns: " + " | ".join(r.columns))
    for row in r.rows[:PREVIEW_ROWS]:
        lines.append(" | ".join(_cell(v) for v in row))
    shown = min(len(r.rows), PREVIEW_ROWS)
    lines.append(f"({len(r.rows)} rows{'; first ' + str(shown) + ' shown' if shown < len(r.rows) else ''}"
                 f"{'; more rows exist beyond the row limit' if r.truncated else ''})")
    if not r.rows:
        lines.append("(No rows: nothing matched.)")
    for n in r.data_notes:
        lines.append(f"Code-checked note: {n}")
    for n in r.notes:
        lines.append(f"Note from the query writer: {n}")
    return "\n".join(lines)


def doc_label(c: dict) -> str:
    if c.get("kind") == "budget":
        return f"2027 Budget Overview (proposed), page {c['page']}"
    return f"Municipal Code of Chicago, Section {c['section']}" + (f" ({c['title']})" if c.get("title") else "")


def docs_source_text(chunks: list[dict], question: str = "") -> str:
    from app.retrieval import OLD_SECTIONS, SECTION_RE
    lines = [f"Note: section {old} is the old number of today's Section {OLD_SECTIONS[old]}."
             for old in dict.fromkeys(m.upper() for m in SECTION_RE.findall(question))
             if old in OLD_SECTIONS]
    lines += [f"[D{i}] {doc_label(c)}\n{c['text']}" for i, c in enumerate(chunks, 1)]
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Citations


def sql_citation(r: SqlResult) -> Citation:
    tables = [t for t in DATASETS if r.sql and re.search(rf"\b{t}\b", r.sql)]
    names = ", ".join(DATASETS[t][0] for t in tables) or "City data tables"
    url = DATASETS[tables[0]][1] if len(tables) == 1 else None
    return Citation(source=f"Chicago Data Portal: {names}", snippet=r.sql, url=url)


def doc_citation(c: dict) -> Citation:
    body = c["text"].split("\n", 1)[-1].strip()
    snippet = body if len(body) <= SNIPPET_CHARS else body[:SNIPPET_CHARS] + "…"
    return Citation(source=doc_label(c), snippet=snippet, url=c.get("url"))


# A citation: [T1], [D3], or several ids in one bracket: [D1, D4], [T1; D2]
_ID = re.compile(r"\[\s*((?:T|D)\d+(?:\s*[,;]\s*(?:T|D)\d+)*)\s*\]")


def cited_ids(text: str) -> list[str]:
    """Source ids cited in the text, in order of first use."""
    ids: list[str] = []
    for group in _ID.findall(text):
        for sid in re.split(r"\s*[,;]\s*", group):
            if sid not in ids:
                ids.append(sid)
    return ids


def link_citations(text: str, available: dict[str, Citation]) -> tuple[str, list[Citation]]:
    """[T1]/[D3] (or [D1, D4]) in the answer -> [1]/[2] in order of first use, plus the
    citation list. Ids that weren't given to the model are removed."""
    order = [sid for sid in cited_ids(text) if sid in available]
    number = {sid: i for i, sid in enumerate(order, 1)}

    def swap(m: re.Match) -> str:
        ids = [s for s in re.split(r"\s*[,;]\s*", m.group(1)) if s in number]
        return "".join(f"[{number[s]}]" for s in ids)
    text = _ID.sub(swap, text)
    text = re.sub(r"\]\s+\[", "][", text)        # "[1] [2]" -> "[1][2]"
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)  # space left before punctuation by a removed id
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text, [available[sid] for sid in order]


# ---------------------------------------------------------------------------


def run(question: str, today: dt.date | None = None, *, model: str | None = None,
        generate=None, query_tables=None, search=None) -> Trace:
    """The whole pipeline. generate, query_tables and search can be replaced in tests."""
    from app.llm import generate as default_generate
    if query_tables is None:
        from app.sql_agent import query_tables
    if search is None:
        from app.retrieval import search
    generate = generate or default_generate
    today = today or dt.date.today()
    start = time.perf_counter()
    trace = Trace(question=question, response=None)  # type: ignore[arg-type]

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        trace.timings_ms[name] = round((now - since) * 1000)
        return now

    def count(reply):
        trace.timings_ms["waited"] = trace.timings_ms.get("waited", 0) + getattr(reply, "waited_ms", 0)
        trace.llm_calls += 0 if reply.cached else 1
        trace.input_tokens += reply.input_tokens
        trace.output_tokens += reply.output_tokens + reply.thinking_tokens

    decision, reply = route_question(question, model=model, generate=generate)
    count(reply)
    trace.decision = decision
    t = lap("route", start)

    # The two sources don't depend on each other: fetch them at the same time
    with ThreadPoolExecutor(max_workers=2) as pool:
        sql_job = (pool.submit(query_tables, decision.sql_question, today, model=model)
                   if decision.sql_question else None)
        docs_job = pool.submit(search, decision.docs_question) if decision.docs_question else None
        if sql_job:
            trace.sql = sql_job.result()
            trace.llm_calls += trace.sql.llm_calls
            trace.input_tokens += trace.sql.input_tokens
            trace.output_tokens += trace.sql.output_tokens
        if docs_job:
            trace.chunks = docs_job.result()
    t = lap("sources", t)

    available: dict[str, Citation] = {}
    parts = []
    if trace.sql:
        parts.append(sql_source_text(trace.sql))
        if trace.sql.ok:  # a refusal or a failed query isn't something to cite
            available["T1"] = sql_citation(trace.sql)
    if trace.chunks:
        parts.append(docs_source_text(trace.chunks, question))
        available.update({f"D{i}": doc_citation(c) for i, c in enumerate(trace.chunks, 1)})
    trace.sources_text = "\n\n".join(parts)

    prompt = f"Today is {today.isoformat()}.\nQuestion: {question}\n\nSources:\n\n{trace.sources_text}"
    reply = generate(prompt, system=SYSTEM, schema=AnswerDraft, model=model)
    count(reply)
    trace.draft = draft = reply.parsed
    lap("answer", t)

    text, citations = link_citations(draft.answer, available)
    ids = {"T1": "T1", **{f"D{i}": c["id"] for i, c in enumerate(trace.chunks, 1)}}
    trace.cited = [ids[sid] for sid in cited_ids(draft.answer) if sid in available]
    refused = draft.refused
    if not refused and not citations:
        # An answer that cites nothing it was given can't be checked: refuse instead,
        # with the SQL agent's reason when it gave one (e.g. "no ward column")
        reason = trace.sql.refusal_reason if trace.sql and not trace.sql.answerable else None
        text, refused = (f"{REFUSAL} {reason}" if reason else REFUSAL), True
    trace.response = QueryResponse(
        answer=text or REFUSAL, route=decision.route, citations=citations, refused=refused,
        latency_ms=round((time.perf_counter() - start) * 1000),
        usage=Usage(llm_calls=trace.llm_calls, input_tokens=trace.input_tokens,
                    output_tokens=trace.output_tokens),
        cost_usd=estimate_cost(trace.input_tokens, trace.output_tokens))
    return trace


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """US$ from token counts and the configured prices (0 on the free tier).
    Counts every token sent, cached replies included: what the request would cost
    without the cache. Embeddings (one short question) are left out: a few tokens."""
    from app.config import get_settings
    s = get_settings()
    return round((input_tokens * s.llm_usd_per_m_input + output_tokens * s.llm_usd_per_m_output) / 1e6, 6)


def answer(question: str) -> QueryResponse:
    return run(question).response
