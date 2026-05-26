"""A2A_min_v1 Timeout Classifier — four timeout dimensions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TimeoutKind(str, Enum):
    FIRST_TOKEN = "FIRST_TOKEN"
    TOKEN_INTERVAL = "TOKEN_INTERVAL"
    TOTAL_TASK = "TOTAL_TASK"
    PROVIDER_RESPONSE = "PROVIDER_RESPONSE"


@dataclass
class SessionTimer:
    """Tracks timing milestones for a single session."""

    session_id: str
    corr_id: str
    invoke_time: float = 0.0
    first_token_time: Optional[float] = None
    last_seen: float = 0.0

    def touch(self) -> None:
        self.last_seen = time.time()

    def mark_invoke(self) -> None:
        self.invoke_time = time.time()
        self.last_seen = self.invoke_time

    def mark_first_token(self) -> None:
        if self.first_token_time is None:
            self.first_token_time = time.time()
        self.touch()


@dataclass
class TimeoutChecker:
    """Evaluates timeout conditions for tracked sessions.

    Four timeout dimensions:
      - first_token_timeout: time from INVOKE to first STREAM_CHUNK
      - token_interval_timeout: time between consecutive STREAM_CHUNKs
      - total_task_timeout: total time from INVOKE to STREAM_END
      - provider_response_timeout: time waiting for initial provider response
    """

    first_token_timeout: float = 30.0
    token_interval_timeout: float = 15.0
    total_task_timeout: float = 120.0
    provider_response_timeout: float = 60.0

    _sessions: dict[str, SessionTimer] = field(default_factory=dict)

    def register(self, session_id: str, corr_id: str) -> SessionTimer:
        timer = SessionTimer(session_id=session_id, corr_id=corr_id)
        timer.mark_invoke()
        self._sessions[session_id] = timer
        return timer

    def get(self, session_id: str) -> Optional[SessionTimer]:
        return self._sessions.get(session_id)

    def on_heartbeat(self, session_id: str) -> bool:
        timer = self._sessions.get(session_id)
        if timer is None:
            return False
        timer.touch()
        return True

    def on_chunk(self, session_id: str) -> None:
        timer = self._sessions.get(session_id)
        if timer is not None:
            timer.mark_first_token()
            timer.touch()

    def check_timeouts(self, now: Optional[float] = None) -> list[tuple[str, TimeoutKind, dict]]:
        """Scan all tracked sessions and return (session_id, timeout_kind, details)."""
        now = now or time.time()
        results: list[tuple[str, TimeoutKind, dict]] = []

        for sid, timer in self._sessions.items():
            elapsed = now - timer.invoke_time

            # Total task timeout
            if elapsed > self.total_task_timeout:
                results.append((sid, TimeoutKind.TOTAL_TASK, {
                    "elapsed": round(elapsed, 2),
                    "limit": self.total_task_timeout,
                    "corr_id": timer.corr_id,
                }))
                continue

            # Provider response timeout (before first token)
            if timer.first_token_time is None and elapsed > self.provider_response_timeout:
                results.append((sid, TimeoutKind.PROVIDER_RESPONSE, {
                    "elapsed": round(elapsed, 2),
                    "limit": self.provider_response_timeout,
                    "corr_id": timer.corr_id,
                }))
                continue

            # First token timeout (before first token, shorter window)
            if timer.first_token_time is None and elapsed > self.first_token_timeout:
                results.append((sid, TimeoutKind.FIRST_TOKEN, {
                    "elapsed": round(elapsed, 2),
                    "limit": self.first_token_timeout,
                    "corr_id": timer.corr_id,
                }))
                continue

            # Token interval timeout (after first token)
            if timer.first_token_time is not None:
                gap = now - timer.last_seen
                if gap > self.token_interval_timeout:
                    results.append((sid, TimeoutKind.TOKEN_INTERVAL, {
                        "gap": round(gap, 2),
                        "limit": self.token_interval_timeout,
                        "corr_id": timer.corr_id,
                    }))

        return results

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
