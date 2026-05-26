"""A2A_min_v1 Structured Logger — JSON-formatted logs with required fields."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Optional


class StructuredFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    REQUIRED_FIELDS = (
        "timestamp", "session_id", "corr_id", "seq",
        "state", "event", "latency_ms", "error_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge structured extra fields
        if hasattr(record, "structured_extra"):
            entry.update(record.structured_extra)

        # Ensure all required fields exist (null if missing)
        for f in self.REQUIRED_FIELDS:
            if f not in entry:
                entry[f] = None

        # Override timestamp with ISO format
        entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
        if record.msecs:
            entry["timestamp"] += f".{int(record.msecs):03d}"

        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str, ensure_ascii=False)


def setup_logger(name: str = "a2a", level: int = logging.INFO) -> logging.Logger:
    """Create and configure a structured JSON logger."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    return logger


def log_event(
    logger: logging.Logger,
    event: str,
    session_id: str = "",
    corr_id: str = "",
    seq: Optional[int] = None,
    state: Optional[str] = None,
    latency_ms: Optional[float] = None,
    error_code: Optional[str] = None,
    **extra: Any,
) -> None:
    """Emit a structured log event with all required fields."""
    structured = {
        "event": event,
        "session_id": session_id,
        "corr_id": corr_id,
        "seq": seq,
        "state": state,
        "latency_ms": latency_ms,
        "error_code": error_code,
    }
    structured.update(extra)
    logger.info(event, extra={"structured_extra": structured})