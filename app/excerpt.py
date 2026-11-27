"""Pick the passage of a document chunk that supports a claim, for the citation excerpt.

A code section or budget page is often longer than the excerpt (400 characters), and
the sentence that matters is rarely the first one: 5-12-110's rodent rule is far down
the section. best_passage() scores every stretch of whole sentences (or table rows)
that fits, by the words it shares with the claim and the question, and keeps the best.

    best_passage(chunk_text, "landlords must exterminate rodents")
    -> Excerpt(text="…Failure to exterminate insects, rodents or other pests…",
               highlights=["exterminate", "rodents"])

Words are compared by a rough stem ("rodents" = "rodent", "heating" = "heat"), each
counted once, so a passage can't win by repeating one word. Numbers count more than
words: "914,383,396" pins the budget line exactly; years count less (every budget page
says 2027).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LIMIT = 400

STOP = set("""
about after also among another and any are been before being both but can cannot could
did does each either from had has have her his how into its may might more most must
not only other our over per same shall should some such than that the their them then
there these they this those through under until upon very was were what when where which
while who whom why will with within would year years your you section sections chapter
chicago city code municipal provided following including thereof herein against
require required requires requirement requirements
""".split())

TOKEN = re.compile(r"\d{1,2}:\d\d|\d[\d,]*(?:\.\d+)?|[A-Za-z]+")   # 8:30 is one token
SUFFIXES = ("ations", "ation", "ings", "ing", "ed", "es", "s")


def stem(token: str) -> str | None:
    """A rough stem, or None for words too common or short to mean anything."""
    if token[0].isdigit():
        number = token.replace(",", "").rstrip(".")
        return number if len(number) >= 2 else None
    word = token.lower()
    if len(word) < 4 or word in STOP:
        return None
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    return word[:6]


def weight(term: str) -> float:
    if not term[0].isdigit():
        return 1.0
    if re.fullmatch(r"(19|20)\d\d", term):
        return 0.5   # a year: on every budget page
    return 3.0 if len(term.split(".")[0]) >= 3 else 2.0   # 914383396 / 68, 8:30


def terms(text: str) -> set[str]:
    return {s for t in TOKEN.findall(text) if (s := stem(t))}


@dataclass
class Excerpt:
    text: str
    highlights: list[str] = field(default_factory=list)


def pieces(body: str) -> list[tuple[str, str]]:
    """The body as (separator before, piece): sentences of prose, rows of tables.
    PDF line wraps inside a paragraph become spaces; table rows keep their lines."""
    out: list[tuple[str, str]] = []
    for paragraph in re.split(r"\n\s*\n", body.strip()):
        lines = [ln.strip() for ln in paragraph.splitlines() if ln.strip()]
        if not lines:
            continue
        if any("|" in ln for ln in lines):
            parts, joiner = lines, "\n"
        else:
            prose = re.sub(r"\s+", " ", " ".join(lines))
            parts, joiner = re.split(r"(?<![ap]\.m\.)(?<![\s(]\d\.)(?<=[.;:])\s+(?=[(A-Z0-9])", prose), " "
        for i, part in enumerate(parts):
            for chunk in _fit(part):
                out.append(("\n" if i == 0 else joiner, chunk))
    if out:
        out[0] = ("", out[0][1])
    return out


def _fit(text: str) -> list[str]:
    """A sentence is kept whole up to twice the limit (one long rule reads better
    whole); past that it's cut at word boundaries."""
    if len(text) <= 2 * LIMIT:
        return [text]
    chunks, current = [], ""
    for word in text.split(" "):
        if current and len(current) + 1 + len(word) > LIMIT - 2:
            chunks.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    return chunks + [current]


def best_passage(body: str, focus: str = "", limit: int = LIMIT) -> Excerpt:
    """The stretch of whole pieces, at most `limit` characters, that shares the most
    with `focus` (the claim and the question). No match: the start of the body."""
    parts = pieces(body)
    if not parts:
        return Excerpt("")
    wanted = terms(focus)

    def window(i: int) -> tuple[float, int, int]:
        """Pieces i..j-1 that fit in the limit, and their score."""
        length, j, found = 0, i, set()
        while j < len(parts):
            extra = len(parts[j][1]) + (len(parts[j][0]) if j > i else 0)
            if j > i and length + extra > limit:
                break
            length += extra
            found |= terms(parts[j][1]) & wanted
            j += 1
        return sum(weight(t) for t in found), i, j

    # A window starts at a matching sentence, not at filler before it; the best score
    # wins, a tie keeps the earlier one. Nothing matches: the start of the chunk.
    starts = [i for i, (_, piece) in enumerate(parts) if terms(piece) & wanted] or [0]
    _, i, j = max((window(i) for i in starts), key=lambda w: (w[0], -w[1]))
    text = parts[i][1] + "".join(sep + p for sep, p in parts[i + 1:j])
    if j < len(parts):   # more follows: "rooms. …", "rodents;…"
        text += " …" if text.endswith(".") else "…"
    text = ("…" if i > 0 else "") + text
    highlights = list({t.lower(): t for t in TOKEN.findall(text) if stem(t) in wanted}.values())
    return Excerpt(text, highlights)
