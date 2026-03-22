from __future__ import annotations

import io
import json
import logging


def _capture_json_log(level: int, message: str) -> dict:
    """Emit one log record through a JsonFormatter and return the parsed JSON."""
    from kore.logging_config import JsonFormatter

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    buf = io.StringIO()
    handler.stream = buf

    logger = logging.getLogger("kore_test_json_" + str(level))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    logger.log(level, message)
    return json.loads(buf.getvalue().strip())


def test_json_formatter_produces_valid_json():
    data = _capture_json_log(logging.INFO, "hello world")
    assert isinstance(data, dict)


def test_json_formatter_contains_required_fields():
    data = _capture_json_log(logging.WARNING, "test message")
    assert "timestamp" in data
    assert "level" in data
    assert "logger" in data
    assert "message" in data


def test_json_formatter_level_name():
    data = _capture_json_log(logging.ERROR, "oops")
    assert data["level"] == "ERROR"


def test_json_formatter_message_content():
    data = _capture_json_log(logging.INFO, "specific content")
    assert data["message"] == "specific content"


def test_configure_logging_adds_root_handler():
    from kore.logging_config import configure_logging
    import logging as _logging

    root = _logging.getLogger()
    before = len(root.handlers)
    configure_logging(level=logging.DEBUG, json_format=False)
    assert len(root.handlers) > before
    # Restore to avoid polluting other tests
    for h in root.handlers[before:]:
        root.removeHandler(h)
