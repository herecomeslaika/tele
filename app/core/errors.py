# A2A_min_v1 Error Codes & Structured Error Factory

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from app.models.envelope import Envelope, MessageType


class ErrorCode(str, Enum):
    INVALID_MESSAGE_TYPE = "INVALID_MESSAGE_TYPE"
    MISSING_CORRELATION_FIELDS = "MISSING_CORRELATION_FIELDS"
    OUT_OF_ORDER_STREAM = "OUT_OF_ORDER_STREAM"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    FIRST_TOKEN_TIMEOUT = "FIRST_TOKEN_TIMEOUT"
    TOKEN_INTERVAL_TIMEOUT = "TOKEN_INTERVAL_TIMEOUT"
    MESSAGE_AFTER_TERMINAL = "MESSAGE_AFTER_TERMINAL"
    ILLEGAL_STATE_TRANSITION = "ILLEGAL_STATE_TRANSITION"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"


def make_error_envelope(
    code: ErrorCode,
    detail: str,
    *,
    version: str = "A2A_min_v1",
    session_id: str = "",
    corr_id: str | None = None,
    seq: int = 0,
    original_seq: int | None = None,
) -> Envelope:
    """Factory: produce a standard ERROR envelope for any validation failure."""
    payload: dict[str, Any] = {
        "code": code.value,
        "detail": detail,
    }
    if original_seq is not None:
        payload["original_seq"] = original_seq

    return Envelope(
        version=version,
        type=MessageType.ERROR,
        session_id=session_id,
        corr_id=corr_id or uuid.uuid4().hex,
        seq=seq,
        timestamp=time.time(),
        payload=payload,
    )
