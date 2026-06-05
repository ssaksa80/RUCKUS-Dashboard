"""Tests for ruckus_dashboard.logging_setup (Task 5)."""
import json
import logging

from ruckus_dashboard.logging_setup import _JsonLogFormatter, configure_logging


def test_json_formatter_emits_valid_json():
    fmt = _JsonLogFormatter()
    record = logging.LogRecord(
        "ruckus_dashboard", logging.INFO, "f.py", 1, "hello", None, None
    )
    record.request_id = "abcd1234"
    out = fmt.format(record)
    payload = json.loads(out)
    # Verbatim port from monolith uses "msg" (not "message") and includes "ts"/"logger".
    assert payload["msg"] == "hello"
    assert payload["request_id"] == "abcd1234"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "ruckus_dashboard"
    assert "ts" in payload


def test_configure_logging_idempotent(tmp_instance):
    configure_logging(tmp_instance, debug=False)
    handlers_after_first = list(logging.getLogger("ruckus_dashboard").handlers)
    configure_logging(tmp_instance, debug=True)  # second call must not duplicate handlers
    logger = logging.getLogger("ruckus_dashboard")
    # Same handler count after a re-configure (no duplication).
    assert len(logger.handlers) == len(handlers_after_first)
    handler_classes = {type(h).__name__ for h in logger.handlers}
    # Either RotatingFileHandler + StreamHandler, or just StreamHandler if disk write failed.
    assert "RotatingFileHandler" in handler_classes or "StreamHandler" in handler_classes
    assert logger.level == logging.DEBUG  # debug=True took effect


def test_configure_logging_writes_log_file(tmp_instance):
    from pathlib import Path

    configure_logging(tmp_instance, debug=False)
    logger = logging.getLogger("ruckus_dashboard")
    logger.info("test message", extra={"request_id": "req-1"})
    for h in logger.handlers:
        h.flush()
    log_file = Path(tmp_instance) / "logs" / "ruckus_dashboard.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "test message" in content
    assert "req-1" in content
