# A2A_min_v1 Structured Logger — JSON format, mandatory fields

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class StructuredLogger:
    """
    JSON-format structured logger for the A2A_min_v1 Gateway.

    Every log entry contains these fields (null if not provided):
      timestamp, level, event, session_id, corr_id, state, error_code, latency_ms

    Plus any extra kwargs passed to log().
    """

    def __init__(self, name: str, output: Any = None) -> None:
        self._name = name
        self._output = output or sys.stdout

    def log(
        self,
        event: str,
        *,
        level: str = "INFO",
        session_id: str | None = None,
        corr_id: str | None = None,
        state: str | None = None,
        error_code: str | None = None,
        latency_ms: float | None = None,
        **extra: Any,
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": time.time(),
            "level": level,
            "logger": self._name,
            "event": event,
            "session_id": session_id,
            "corr_id": corr_id,
            "state": state,
            "error_code": error_code,
            "latency_ms": latency_ms,
        }
        entry.update(extra)

        # Remove None values for cleaner output, but keep mandatory fields as null
        line = json.dumps(entry, default=str, ensure_ascii=False)
        self._output.write(line + "\n")
        self._output.flush()


class _LoggerRegistry:
    """Simple registry so get_logger returns the same instance per name."""

    _loggers: dict[str, StructuredLogger] = {}

    @classmethod
    def get(cls, name: str, output: Any = None) -> StructuredLogger:
        if name not in cls._loggers:
            cls._loggers[name] = StructuredLogger(name, output)
        return cls._loggers[name]


def get_logger(name: str, output: Any = None) -> StructuredLogger:
    return _LoggerRegistry.get(name, output)
