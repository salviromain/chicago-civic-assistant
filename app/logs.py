"""One JSON line per log record (Day 12), so each request's numbers can be searched.

    log.info("query", extra={"fields": {"status": 200, "latency_ms": 2310, "cost_usd": 0.0029}})
    -> {"severity": "INFO", "message": "query", "status": 200, "latency_ms": 2310, "cost_usd": 0.0029}

Cloud Run reads JSON lines on stdout as structured logs: `severity` sets the level,
and every other key becomes a field you can filter on in Logs Explorer
(e.g. jsonPayload.latency_ms > 8000). Locally it's still one readable line per request.
"""

from __future__ import annotations

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup(name: str = "civic", level: int = logging.INFO) -> logging.Logger:
    """The app's logger, writing JSON lines to stdout. Safe to call more than once."""
    log = logging.getLogger(name)
    if not any(isinstance(h.formatter, JsonFormatter) for h in log.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False  # uvicorn's own handlers would print it a second time
    return log


def level_for(status_code: int) -> int:
    """5xx = ERROR (our side failed), 4xx = WARNING (the client's request), else INFO."""
    return logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
