"""Load documents: extract text, chunk, embed, store in pgvector.

Usage:
    python -m ingest.load_docs --dry-run      # extract and chunk, print stats, touch nothing
    python -m ingest.load_docs --no-embed     # store chunks without embeddings (no API key needed)
    python -m ingest.load_docs                # full load: chunks + Gemini embeddings

Inputs (downloaded by hand, see docs/SOURCES.md):
    data/docs/code/<chapter>.pdf              # Municipal Code chapters, e.g. 14X-8.pdf
    data/docs/budget/2027-budget-overview.pdf

Output: the `doc_chunks` table. Code chunks are one per numbered section (id =
section number, e.g. 14X-8-802.2.2); budget chunks are ~500-token pieces of one
page (id = budget-2027-p<page>-<n>). Each row has an embedding (pgvector) and a
full-text column (tsv) for keyword search.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DOCS_DIR = Path("data/docs")
BUDGET_FILE = DOCS_DIR / "budget" / "2027-budget-overview.pdf"
CACHE_DIR = Path("data/cache/embeddings")

CODE_URL = "https://codelibrary.amlegal.com/codes/chicago/latest/chicago_il"
BUDGET_URL = "https://www.chicago.gov/city/en/depts/obm/provdrs/budget.html"
BUDGET_DOC = "2027 Budget Overview (proposed)"

CHUNK_TOKENS = 500        # target size of a budget chunk
OVERLAP_TOKENS = 50       # repeated between consecutive budget chunks
MAX_SECTION_TOKENS = 800  # a code section longer than this is split into parts
# Gemini free tier: 30,000 input tokens per minute for embeddings
# (quota EmbedContentTokensPerMinutePerProjectPerModel-FreeTier). Our token
# counts are estimates and numbers-heavy budget text counts higher, so stay well under.
EMBED_BATCH_TOKENS = 8_000      # estimated tokens per request
EMBED_MINUTE_TOKENS = 18_000    # estimated tokens sent per rolling minute
EMBED_BATCH_MAX = 100           # texts per request (API limit)


# ---------------------------------------------------------------------------
# Data shapes


@dataclass
class Page:
    number: int  # page number as printed in the document
    text: str


@dataclass
class Chunk:
    id: str
    doc: str
    kind: str              # 'code' or 'budget'
    section: str | None    # code section number, e.g. 14X-8-802.2.2
    title: str | None      # section title, or the budget's table-of-contents heading
    parent: str | None     # enclosing sections, e.g. "14X-8-802 Heating systems > ..."
    page: int
    url: str
    text: str              # what gets embedded and searched; starts with a context line
    n_tokens: int = field(init=False)

    def __post_init__(self) -> None:
        self.n_tokens = approx_tokens(self.text)


def approx_tokens(text: str) -> int:
    """Rough token count: about 1.3 tokens per English word. Good enough for sizing."""
    return round(len(text.split()) * 1.3)


def clean(text: str) -> str:
    """Normalize ligatures (ﬀ -> ff), odd spaces and trailing whitespace.

    The code PDFs write degrees with the masculine ordinal sign (68ºF); NFKC would
    turn it into the letter o ("68oF"), so it becomes a real degree sign first."""
    text = unicodedata.normalize("NFKC", text.replace("\u00ba", "\u00b0"))
    return "\n".join(line.rstrip() for line in text.splitlines())


# ---------------------------------------------------------------------------
# Packing text into chunks (shared by code and budget)


def _split_oversized(unit: str, max_tokens: int) -> list[str]:
    """Break one paragraph that is too big on its own: by line, then by words."""
    if approx_tokens(unit) <= max_tokens:
        return [unit]
    lines = unit.split("\n")
    if len(lines) > 1:
        return [piece for line in lines for piece in _split_oversized(line, max_tokens)]
    words = unit.split()
    step = max(1, int(max_tokens / 1.3))
    return [" ".join(words[i:i + step]) for i in range(0, len(words), step)]


def pack(paragraphs: list[str], max_tokens: int, overlap_tokens: int = 0) -> list[str]:
    """Group paragraphs into chunks of at most ~max_tokens, never cutting a paragraph
    unless it is too big on its own. With overlap, each chunk starts with the last
    paragraph(s) of the previous one (up to overlap_tokens), so a fact that sits on a
    boundary appears whole in at least one chunk."""
    units = [u for p in paragraphs if p.strip() for u in _split_oversized(p.strip(), max_tokens)]
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for unit in units:
        n = approx_tokens(unit)
        if current and size + n > max_tokens:
            chunks.append(current)
            carry: list[str] = []
            carried = 0
            for prev in reversed(current):
                if carried + approx_tokens(prev) > overlap_tokens:
                    break
                carry.insert(0, prev)
                carried += approx_tokens(prev)
            current, size = carry, carried
        current.append(unit)
        size += n
    if current:
        chunks.append(current)
    return ["\n\n".join(c) for c in chunks]


def chunk_fixed(text: str, max_tokens: int = CHUNK_TOKENS,
                overlap_tokens: int = OVERLAP_TOKENS) -> list[str]:
    """Fixed-size chunking: ~max_tokens per chunk, split at blank lines, with overlap.
    Used for the budget; also the baseline for the Day 10 chunking experiment."""
    return pack(re.split(r"\n\s*\n", text), max_tokens, overlap_tokens)


# ---------------------------------------------------------------------------
# Municipal Code: one chunk per numbered section


def extract_code_pages(path: Path) -> list[Page]:
    import pymupdf
    with pymupdf.open(path) as doc:
        return [Page(i + 1, clean(page.get_text())) for i, page in enumerate(doc)]


def chunk_code(pages: list[Page], chapter: str, max_tokens: int = MAX_SECTION_TOKENS) -> list[Chunk]:
    """Split a code chapter at its numbered headings.

    The chapter starts with a table of contents (number, 2+ spaces, title). In the
    body, a heading is the number, ONE space, then a capitalized title, e.g.
    "14X-8-802.2.2 Heat to be provided." Lines that start with a section number
    followed by "(" or "," are wrapped sentences ("5-12-110(a), the tenant..."),
    not headings. A heading is only accepted if its top-level section is in the
    table of contents. Text after a second "CHAPTER" title is ignored.
    """
    chap = re.escape(chapter)
    toc_re = re.compile(rf"^({chap}-\d+)\s{{2,}}(\S.*?)\.?$")
    head_re = re.compile(rf"^({chap}-\d+(?:\.\d+)*) ([A-Z].*?)\.?$")

    lines = [(p.number, line) for p in pages for line in p.text.split("\n")]
    # A file can contain the next chapter too (5-12.pdf ends with all of 5-16): stop
    # at the second "CHAPTER" title.
    starts = [i for i, (_, line) in enumerate(lines) if line.startswith("CHAPTER ")]
    if len(starts) > 1:
        lines = lines[:starts[1]]
    toc = {m.group(1): m.group(2) for _, line in lines if (m := toc_re.match(line))}

    sections: list[dict] = []
    for page_no, line in lines:
        m = head_re.match(line)
        if m and (not toc or m.group(1).split(".")[0] in toc):
            sections.append({"num": m.group(1), "title": m.group(2), "page": page_no, "body": []})
        elif sections and not toc_re.match(line):
            sections[-1]["body"].append(line)

    # Top-level titles from the table of contents read better ("Heating systems"
    # instead of "HEATING SYSTEMS").
    titles = {s["num"]: toc.get(s["num"], s["title"]) for s in sections}
    doc = f"Municipal Code of Chicago, Chapter {chapter}"
    chunks: list[Chunk] = []
    for s in sections:
        body = "\n".join(s["body"]).strip()
        title = titles[s["num"]]
        if not body or title.lower().startswith("reserved"):
            continue  # pure parent headings and repealed sections have no text of their own
        parts = s["num"].split(".")
        ancestors = [".".join(parts[:i]) for i in range(1, len(parts))]
        parent = " > ".join(f"{a} {titles[a]}" for a in ancestors if a in titles) or None
        header = " > ".join(filter(None, [parent, f"{s['num']} {title}"]))
        # Paragraphs start with an indented line in these PDFs ("   (a) ...").
        paragraphs = re.split(r"\n(?=\s)", body)
        pieces = pack(paragraphs, max_tokens) if approx_tokens(body) > max_tokens else [body]
        for k, piece in enumerate(pieces, start=1):
            many = len(pieces) > 1
            chunks.append(Chunk(
                id=f"{s['num']}#{k}" if many else s["num"],
                doc=doc, kind="code", section=s["num"], title=title, parent=parent,
                page=s["page"], url=CODE_URL,
                text=f"{header}{f' (part {k} of {len(pieces)})' if many else ''}\n{piece}",
            ))
    return chunks


# ---------------------------------------------------------------------------
# Budget: page-aware fixed-size chunks; tables rebuilt as rows


def rows_from_words(words: list, tol: float = 3.0, gap: float = 15.0) -> list[str]:
    """Rebuild table rows from word boxes: words at the same height form a row, and a
    wide horizontal gap becomes a ' | ' column break. Keeps each number next to its
    label, which plain text extraction loses (it lists all labels, then all numbers)."""
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[list] = []
    for w in words:
        y = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - y) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([y, [w]])
    out = []
    for _, ws in rows:
        ws.sort(key=lambda w: w[0])
        line = ws[0][4]
        for a, b in zip(ws, ws[1:]):
            line += (" | " if b[0] - a[2] > gap else " ") + b[4]
        out.append(line)
    return out


def budget_page_text(page) -> str:
    """Prose as paragraph blocks; areas detected as tables rebuilt row by row."""
    import pymupdf
    tables = [pymupdf.Rect(t.bbox) for t in page.find_tables().tables]

    def in_table(bbox) -> bool:
        return any(pymupdf.Rect(bbox).intersects(t) for t in tables)

    items = []
    for b in page.get_text("blocks", sort=True):
        if b[6] == 0 and not in_table(b[:4]):  # b[6] == 0: a text block, not an image
            items.append((b[1], b[0], " ".join(b[4].split())))
    words = page.get_text("words")
    for t in tables:
        inside = [w for w in words if pymupdf.Rect(w[:4]).intersects(t)]
        items.append((t.y0, t.x0, "\n".join(rows_from_words(inside))))
    items.sort(key=lambda i: (i[0], i[1]))
    return clean("\n\n".join(text for _, _, text in items if text))


def strip_budget_furniture(text: str, printed_page: int) -> str:
    """Drop the running header ("2027 BUDGET OVERVIEW ...") and the page number."""
    keep = [p for p in text.split("\n\n")
            if not p.startswith("2027 BUDGET OVERVIEW") and p.strip() != str(printed_page)]
    return "\n\n".join(keep)


def parse_budget_toc(page) -> list[tuple[int, int, str]]:
    """Table of contents -> [(printed start page, level, title)]. Level from indent."""
    entries = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = clean("".join(span["text"] for span in line["spans"])).strip()
            m = re.match(r"^(.+?)\s*\.{3,}\s*(\d+)\.?\s*$", text)
            if m:
                entries.append((line["bbox"][0], int(m.group(2)), m.group(1).strip()))
    if not entries:
        return []
    left = min(x for x, _, _ in entries)
    return [(start, 1 if x < left + 5 else 2, title) for x, start, title in entries]


def budget_heading(toc: list[tuple[int, int, str]], printed_page: int) -> str | None:
    """'Level 1 > Level 2' heading that a printed page falls under."""
    top = sub = None
    for start, level, title in sorted(toc, key=lambda e: (e[0], e[1])):
        if start > printed_page:
            break
        if level == 1:
            top, sub = title, None
        else:
            sub = title
    return " > ".join(filter(None, [top, sub])) or None


def chunk_budget(path: Path = BUDGET_FILE, toc_pdf_page: int = 3, page_offset: int = 1) -> list[Chunk]:
    """PDF page n is printed page n - page_offset (the cover pages are unnumbered)."""
    import pymupdf
    chunks: list[Chunk] = []
    with pymupdf.open(path) as doc:
        toc = parse_budget_toc(doc[toc_pdf_page - 1])
        first = min((start for start, _, _ in toc), default=1)
        for i, page in enumerate(doc):
            printed = i + 1 - page_offset
            if printed < first:
                continue  # covers and the table of contents
            text = strip_budget_furniture(budget_page_text(page), printed)
            if approx_tokens(text) < 20:
                continue  # photo or divider pages
            heading = budget_heading(toc, printed)
            context = f"{BUDGET_DOC}, page {printed}" + (f", {heading}" if heading else "")
            for k, piece in enumerate(chunk_fixed(text), start=1):
                chunks.append(Chunk(
                    id=f"budget-2027-p{printed:03d}-{k}", doc=BUDGET_DOC, kind="budget",
                    section=None, title=heading, parent=None, page=printed, url=BUDGET_URL,
                    text=f"{context}\n{piece}",
                ))
    return chunks


# ---------------------------------------------------------------------------
# Embeddings (Gemini), cached on disk


def cache_key(model: str, dims: int, task: str, text: str) -> str:
    return hashlib.sha256(f"{model}|{dims}|{task}|{text}".encode()).hexdigest()


def _normalize(vec: list[float]) -> list[float]:
    """Scale to length 1. Google recommends this for embeddings shortened below 3072."""
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def token_batches(texts: list[str], idx: list[int], max_tokens: int = EMBED_BATCH_TOKENS,
                  max_items: int = EMBED_BATCH_MAX) -> list[list[int]]:
    """Group text indexes into requests by estimated size, not just by count."""
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for i in idx:
        n = approx_tokens(texts[i])
        if current and (size + n > max_tokens or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        current.append(i)
        size += n
    if current:
        batches.append(current)
    return batches


class MinuteBudget:
    """Wait before a request if it would push the last 60 s over the token budget.
    Pacing up front avoids hitting the limit and burning retries."""

    def __init__(self, per_minute: int = EMBED_MINUTE_TOKENS, clock=time.monotonic, sleep=time.sleep):
        self.per_minute, self.clock, self.sleep = per_minute, clock, sleep
        self.sent: list[tuple[float, int]] = []

    def wait_for(self, tokens: int) -> None:
        while True:
            now = self.clock()
            self.sent = [(t, n) for t, n in self.sent if now - t < 60]
            used = sum(n for _, n in self.sent)
            if not self.sent or used + tokens <= self.per_minute:
                self.sent.append((now, tokens))
                return
            self.sleep(60 - (now - self.sent[0][0]) + 0.5)


def embed_texts(texts: list[str], model: str, dims: int, task: str,
                api_key: str | None, cache_dir: Path = CACHE_DIR,
                client=None, budget: MinuteBudget | None = None) -> tuple[list[list[float]], int]:
    """Embed texts, reading and writing a per-text cache. Returns (vectors, API calls)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    vectors: list[list[float] | None] = [None] * len(texts)
    missing = []
    for i, text in enumerate(texts):
        f = cache_dir / f"{cache_key(model, dims, task, text)}.json"
        if f.exists():
            vectors[i] = json.loads(f.read_text())
        else:
            missing.append(i)
    calls = 0
    if missing:
        if client is None:
            if not api_key:
                raise SystemExit("GEMINI_API_KEY is not set (add it to .env), or use --no-embed")
            from google import genai
            client = genai.Client(api_key=api_key)
        budget = budget or MinuteBudget()
        done = 0
        for idx in token_batches(texts, missing):
            budget.wait_for(sum(approx_tokens(texts[i]) for i in idx))
            result = _embed_with_retry(client, model, dims, task, [texts[i] for i in idx])
            calls += 1
            for i, emb in zip(idx, result):
                vec = _normalize(list(emb))
                vectors[i] = vec
                f = cache_dir / f"{cache_key(model, dims, task, texts[i])}.json"
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps(vec))
                tmp.replace(f)  # never leave a half-written cache file
            done += len(idx)
            print(f"  embedded {done}/{len(missing)}", flush=True)
    return vectors, calls  # type: ignore[return-value]


def _quota_id(error) -> str:
    """Which quota a 429 hit, e.g. ...TokensPerMinute... or ...PerDay..."""
    m = re.search(r"'quotaId': '([^']+)'", str(error))
    return m.group(1) if m else "unknown quota"


def _embed_with_retry(client, model: str, dims: int, task: str, texts: list[str],
                      attempts: int = 6) -> list[list[float]]:
    """One embedding request; retries rate limits (429) and server errors (5xx).
    A daily quota won't reset by waiting minutes, so that stops at once."""
    from google.genai import errors, types
    config = types.EmbedContentConfig(task_type=task, output_dimensionality=dims)
    for attempt in range(attempts):
        try:
            result = client.models.embed_content(model=model, contents=texts, config=config)
            return [e.values for e in result.embeddings]
        except errors.APIError as e:
            if e.code != 429 and (e.code or 0) < 500:
                raise  # a bad request won't fix itself
            quota = _quota_id(e) if e.code == 429 else f"server error {e.code}"
            if "PerDay" in quota:
                raise SystemExit(f"daily embedding quota reached ({quota}); run again tomorrow, "
                                 "cached embeddings are kept")
            if attempt == attempts - 1:
                raise
            wait = min(2 ** attempt * 15, 120)
            print(f"  embedding API {e.code} ({quota}), retrying in {wait}s", flush=True)
            time.sleep(wait)
    return []


# ---------------------------------------------------------------------------
# Storage


def store(chunks: list[Chunk], vectors: list[list[float]] | None, database_url: str, dims: int) -> None:
    """Recreate doc_chunks and insert every chunk; indexes are built after loading."""
    import numpy as np
    import psycopg
    from pgvector.psycopg import register_vector

    url = database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        conn.execute("DROP TABLE IF EXISTS doc_chunks")
        conn.execute(f"""
            CREATE TABLE doc_chunks (
                id        text PRIMARY KEY,
                doc       text NOT NULL,
                kind      text NOT NULL,
                section   text,
                title     text,
                parent    text,
                page      int,
                url       text,
                text      text NOT NULL,
                n_tokens  int,
                embedding vector({dims}),
                tsv       tsvector GENERATED ALWAYS AS (
                    to_tsvector('english',
                        coalesce(section, '') || ' ' || coalesce(title, '') || ' ' || text)) STORED
            )""")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO doc_chunks (id, doc, kind, section, title, parent, page, url, text,"
                " n_tokens, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(c.id, c.doc, c.kind, c.section, c.title, c.parent, c.page, c.url, c.text,
                  c.n_tokens, np.array(vectors[i], dtype=np.float32) if vectors else None)
                 for i, c in enumerate(chunks)])
        conn.execute("CREATE INDEX doc_chunks_tsv_idx ON doc_chunks USING gin (tsv)")
        conn.execute("CREATE INDEX doc_chunks_embedding_idx ON doc_chunks "
                     "USING hnsw (embedding vector_cosine_ops)")


# ---------------------------------------------------------------------------


def build_chunks(only: str | None = None) -> list[Chunk]:
    chunks: list[Chunk] = []
    if only in (None, "code"):
        for path in sorted((DOCS_DIR / "code").glob("*.pdf")):
            chunks += chunk_code(extract_code_pages(path), chapter=path.stem)
    if only in (None, "budget") and BUDGET_FILE.exists():
        chunks += chunk_budget(BUDGET_FILE)
    ids = [c.id for c in chunks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SystemExit(f"duplicate chunk ids: {sorted(dupes)[:10]}")
    return chunks


def print_stats(chunks: list[Chunk]) -> None:
    by_doc: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_doc.setdefault(c.doc, []).append(c)
    for doc, cs in by_doc.items():
        sizes = [c.n_tokens for c in cs]
        print(f"  {doc}: {len(cs)} chunks, tokens median {statistics.median(sizes):.0f}, max {max(sizes)}")
    print(f"  total: {len(chunks)} chunks, ~{sum(c.n_tokens for c in chunks):,} tokens")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="extract and chunk only; print stats")
    p.add_argument("--no-embed", action="store_true", help="store chunks without embeddings")
    p.add_argument("--only", choices=["code", "budget"], help="load one document set")
    args = p.parse_args()

    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    from app.config import get_settings
    settings = get_settings()

    chunks = build_chunks(args.only)
    print_stats(chunks)
    if args.dry_run:
        return

    vectors = None
    if not args.no_embed:
        vectors, calls = embed_texts(
            [c.text for c in chunks], settings.embedding_model, settings.embedding_dims,
            "RETRIEVAL_DOCUMENT", os.getenv("GEMINI_API_KEY") or settings.gemini_api_key)
        print(f"  embeddings: {len(vectors)} ({calls} API calls, the rest from cache)")
    store(chunks, vectors, os.getenv("DATABASE_URL") or settings.database_url, settings.embedding_dims)
    print(f"  stored {len(chunks)} chunks in doc_chunks")


if __name__ == "__main__":
    main()
