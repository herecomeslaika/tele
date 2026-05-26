"""A2A_min_v1 Idempotency Manager — corr_id-based duplicate detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from app.models.state import SessionState


class IdempotencyAction(str, Enum):
    ACCEPT = "accept"          # new message, process normally
    REUSE = "reuse"            # duplicate, return cached result
    IGNORE = "ignore"          # duplicate, silently ignore
    REJECT = "reject"          # duplicate, return error


@dataclass
class CachedResult:
    corr_id: str
    msg_type: str
    state: SessionState
    result: Optional[dict] = None
    response: Optional[Any] = None


@dataclass
class IdempotencyManager:
    """Tracks corr_id-based message deduplication.

    Policies:
      - duplicate INVOKE while active -> REJECT
      - duplicate INVOKE when terminal -> REUSE (return cached result)
      - duplicate CANCEL -> IGNORE
      - duplicate STREAM_END -> IGNORE
    """

    _cache: dict[str, CachedResult] = field(default_factory=dict)

    def check_invoke(self, corr_id: str) -> tuple[IdempotencyAction, Optional[CachedResult]]:
        cached = self._cache.get(corr_id)
        if cached is None:
            return IdempotencyAction.ACCEPT, None

        if cached.state.is_terminal:
            return IdempotencyAction.REUSE, cached

        return IdempotencyAction.REJECT, cached

    def check_cancel(self, corr_id: str) -> tuple[IdempotencyAction, Optional[CachedResult]]:
        cached = self._cache.get(corr_id)
        if cached is None:
            return IdempotencyAction.ACCEPT, None

        if cached.state == SessionState.CANCELLED:
            return IdempotencyAction.IGNORE, cached

        if cached.state.is_terminal:
            return IdempotencyAction.REJECT, cached

        return IdempotencyAction.ACCEPT, cached

    def check_stream_end(self, corr_id: str) -> tuple[IdempotencyAction, Optional[CachedResult]]:
        cached = self._cache.get(corr_id)
        if cached is None:
            return IdempotencyAction.ACCEPT, None

        if cached.state.is_terminal:
            return IdempotencyAction.IGNORE, cached

        return IdempotencyAction.ACCEPT, cached

    def register(self, corr_id: str, msg_type: str, state: SessionState,
                 result: Optional[dict] = None) -> None:
        self._cache[corr_id] = CachedResult(
            corr_id=corr_id, msg_type=msg_type, state=state, result=result
        )

    def update_state(self, corr_id: str, state: SessionState) -> None:
        cached = self._cache.get(corr_id)
        if cached is not None:
            cached.state = state

    def store_response(self, corr_id: str, response: Any) -> None:
        cached = self._cache.get(corr_id)
        if cached is not None:
            cached.response = response

    def get(self, corr_id: str) -> Optional[CachedResult]:
        return self._cache.get(corr_id)
