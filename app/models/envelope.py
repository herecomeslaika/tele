# A2A_min_v1 Envelope & Message Types

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MessageType(str, Enum):
    INVOKE = "INVOKE"
    STREAM_CHUNK = "STREAM_CHUNK"
    STREAM_END = "STREAM_END"
    ERROR = "ERROR"
    CANCEL = "CANCEL"
    HEARTBEAT = "HEARTBEAT"


VALID_MESSAGE_TYPES = {mt.value for mt in MessageType}


class Envelope(BaseModel):
    version: str = Field(..., min_length=1, description="Protocol version, e.g. A2A_min_v1")
    type: str = Field(..., description="Message type, one of the six core types")
    session_id: str = Field(..., min_length=1, description="Session identifier")
    corr_id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="Correlation ID")
    seq: int = Field(default=0, ge=0, description="Sequence number within the session")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp in seconds")
    payload: Any = Field(default=None, description="Message payload")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_MESSAGE_TYPES:
            raise ValueError(f"Invalid message type '{v}'. Must be one of: {sorted(VALID_MESSAGE_TYPES)}")
        return v

    def model_post_init(self, __context: Any) -> None:
        # Ensure required fields are not empty strings
        if not self.version.strip():
            raise ValueError("version must not be empty")
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
