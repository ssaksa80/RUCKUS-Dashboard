"""Structured JSON logging (rotating file + stderr), ported from the monolith.

Provides a `_JsonLogFormatter` that serialises each `LogRecord` as a single-line
JSON object (with optional well-known extras like `request_id`), and a
`configure_logging(instance_path, debug)` entry point that wires a rotating
file handler under `<instance>/logs/ruckus_dashboard.log` plus a stderr stream
handler onto the package logger.

`configure_logging` is idempotent: existing handlers on the package logger are
removed before new ones are attached, so it is safe to call multiple times
(e.g. when toggling debug at runtime or re-bootstrapping in tests).
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("ruckus_dashboard")

_LOG_EXTRA_KEYS = ("request_id", "client", "status", "path", "event")


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _LOG_EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                obj[key] = value
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=True, default=str)


def configure_logging(instance_path: str, debug: bool) -> None:
    LOG.setLevel(logging.DEBUG if debug else logging.INFO)
    for handler in list(LOG.handlers):
        LOG.removeHandler(handler)
    formatter = _JsonLogFormatter()
    try:
        log_dir = Path(instance_path) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "ruckus_dashboard.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        LOG.addHandler(file_handler)
    except OSError:
        pass
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    LOG.addHandler(stream)
    LOG.propagate = False
