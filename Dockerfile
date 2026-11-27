# The API image (Day 12). Build and run locally:
#   docker build -t civic-api .
#   docker compose up -d db && docker compose up api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dependencies first: this layer is reused on rebuilds until requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
# The SQL agent's prompt includes the table reference
COPY docs/TABLES.md ./docs/TABLES.md

# Run as a normal user, not root; it may write only its reply caches
RUN useradd --create-home --uid 10001 civic && mkdir -p data/cache && chown -R civic data
USER civic

# Cloud Run sets $PORT. No access log: the app writes its own JSON line per query.
# exec: uvicorn replaces the shell, so it gets the stop signal and shuts down cleanly.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
