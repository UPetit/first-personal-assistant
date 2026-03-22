from __future__ import annotations

import logging

from pythonjsonlogger.jsonlogger import JsonFormatter as _BaseJsonFormatter


class JsonFormatter(_BaseJsonFormatter):
    """JSON log formatter with a consistent field contract.

    Every record produces: ``timestamp``, ``level``, ``logger``, ``message``.
    Additional fields (``exc_info``, ``stack_info``) are included when present.
    """

    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        # Normalise to the project field contract
        if "asctime" not in log_record:
            log_record["timestamp"] = self.formatTime(record, self.datefmt)
        else:
            log_record["timestamp"] = log_record.pop("asctime")
        log_record["level"] = log_record.pop("levelname", record.levelname)
        log_record["logger"] = log_record.pop("name", record.name)
        log_record["message"] = log_record.pop("message", record.getMessage())


def configure_logging(
    level: int = logging.INFO,
    *,
    json_format: bool = True,
) -> None:
    """Configure the root logger with a stream handler.

    Args:
        level: Logging level (e.g. ``logging.INFO``).
        json_format: When True use ``JsonFormatter``; otherwise use a
            human-readable format suitable for development/testing.
    """
    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(JsonFormatter("%(timestamp)s %(level)s %(logger)s %(message)s"))
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")
        )
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
