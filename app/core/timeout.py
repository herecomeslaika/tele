# A2A_min_v1 Heartbeat Tracker & Timeout Classifier

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from app.core.errors import ErrorCode, make_error_envelope
from app.models.envelope import Envelope


class TimeoutKind(str, Enum):
    FIRST_TOKEN = "FIRST_TOKEN"
    TOKEN_INTERVAL = "TOKEN_INTERVAL"
    PROVIDER_OVERALL = "PROVIDER_OVERALL"


_TIMEOUT_TO_ERROR: dict[TimeoutKind, ErrorCode] = {
    TimeoutKind.FIRST_TOKEN: ErrorCode.FIRST_TOKEN_TIMEOUT,
    TimeoutKind.TOKEN_INTERVAL: ErrorCode.TOKEN_INTERVAL_TIMEOUT,
    TimeoutKind.PROVIDER_OVERALL: ErrorCode.PROVIDER_TIMEOUT,
}


@dataclass
class SessionTimer:
    """Tracks timing milestones for a single session."""

    session_id: str
    corr_id: str
    invoke_time: float = 0.0
    first_token_time: float | None = None
    last_seen: float = 0.0
    version: str = "A2A_min_v1"

    def touch(self) -> None:
        """Update last_seen to now (used by HEARTBEAT and any inbound message)."""
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
    """
    Evaluates timeout conditions for tracked sessions.

    Three timeout dimensions:
      - first_token_timeout: time from INVOKE to first STREAM_CHUNK
      - token_interval_timeout: time between consecutive STREAM_CHUNKs
      - provider_overall_timeout: total time from INVOKE to STREAM_END
    """

    first_token_timeout: float = 30.0
    token_interval_timeout: float = 15.0
    provider_overall_timeout: float = 120.0

    _sessions: dict[str, SessionTimer] = field(default_factory=dict)

    def register(self, session_id: str, corr_id: str, version: str = "A2A_min_v1") -> SessionTimer:
        timer = SessionTimer(session_id=session_id, corr_id=corr_id, version=version)
        timer.mark_invoke()
        self._sessions[session_id] = timer
        return timer

    def get(self, session_id: str) -> SessionTimer | None:
        return self._sessions.get(session_id)

    def on_heartbeat(self, session_id: str) -> bool:
        """Process a heartbeat. Returns True if session exists."""
        timer = self._sessions.get(session_id)
        if timer is None:
            return False
        timer.touch()
        return True

    def on_chunk(self, session_id: str) -> None:
        """Record that a STREAM_CHUNK arrived for this session."""
        timer = self._sessions.get(session_id)
        if timer is not None:
            timer.mark_first_token()
            timer.touch()

    def check_timeouts(self, now: float | None = None) -> list[tuple[str, TimeoutKind, Envelope]]:
        """
        Scan all tracked sessions and return (session_id, timeout_kind, error_envelope)
        for any session that has exceeded a timeout threshold.
        """
        now = now or time.time()
        results: list[tuple[str, TimeoutKind, Envelope]] = []

        for sid, timer in self._sessions.items():
            elapsed = now - timer.invoke_time

            # Provider overall timeout
            if elapsed > self.provider_overall_timeout:
                results.append((
                    sid,
                    TimeoutKind.PROVIDER_OVERALL,
                    make_error_envelope(
                        code=ErrorCode.PROVIDER_TIMEOUT,
                        detail=f"Provider overall timeout: {elapsed:.1f}s > {self.provider_overall_timeout}s",
                        version=timer.version,
                        session_id=sid,
                        corr_id=timer.corr_id,
                    ),
                ))
                continue

            # First token timeout (only if we haven't seen a token yet)
            if timer.first_token_time is None and elapsed > self.first_token_timeout:
                results.append((
                    sid,
                    TimeoutKind.FIRST_TOKEN,
                    make_error_envelope(
                        code=ErrorCode.FIRST_TOKEN_TIMEOUT,
                        detail=f"First token timeout: {elapsed:.1f}s > {self.first_token_timeout}s",
                        version=timer.version,
                        session_id=sid,
                        corr_id=timer.corr_id,
                    ),
                ))
                continue

            # Token interval timeout (only after first token received)
            if timer.first_token_time is not None:
                gap = now - timer.last_seen
                if gap > self.token_interval_timeout:
                    results.append((
                        sid,
                        TimeoutKind.TOKEN_INTERVAL,
                        make_error_envelope(
                            code=ErrorCode.TOKEN_INTERVAL_TIMEOUT,
                            detail=f"Token interval timeout: {gap:.1f}s > {self.token_interval_timeout}s",
                            version=timer.version,
                            session_id=sid,
                            corr_id=timer.corr_id,
                        ),
                    ))

        return results

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
