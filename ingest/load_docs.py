"""Load documents: extract text, chunk, embed, store in pgvector. (Day 3)

Plan:
- Municipal Code chapters (downloaded by hand into data/docs/code/)
- One budget PDF (data/docs/budget/)
- Chunk by code section; keep section number, title and source URL on each chunk
- Embed with `embedding_model`; store in a `chunks` table with a full-text index
"""


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
