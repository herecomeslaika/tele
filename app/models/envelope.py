"""A2A_min_v1 protocol envelope and payload models with full schema validation."""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Message type enum – canonical set for A2A_min_v1
# ---------------------------------------------------------------------------
class MessageType(str, enum.Enum):
    INVOKE = "INVOKE"
    STREAM_CHUNK = "STREAM_CHUNK"
    STREAM_END = "STREAM_END"
    CANCEL = "CANCEL"
    HEARTBEAT = "HEARTBEAT"
    ERROR = "ERROR"
    AGENT_DELEGATE = "AGENT_DELEGATE"
    AGENT_RESPONSE = "AGENT_RESPONSE"


# ---------------------------------------------------------------------------
# Version enum
# ---------------------------------------------------------------------------
class ProtocolVersion(str, enum.Enum):
    V1 = "v1"


# ---------------------------------------------------------------------------
# CSD_Stream_v0 legacy message name mapping (for #32 compatibility)
# ---------------------------------------------------------------------------
LEGACY_MESSAGE_MAP: dict[str, MessageType] = {
    "TASK_START": MessageType.INVOKE,
    "CHUNK": MessageType.STREAM_CHUNK,
    "TASK_END": MessageType.STREAM_END,
    "STOP": MessageType.CANCEL,
    "PING": MessageType.HEARTBEAT,
    "FAIL": MessageType.ERROR,
}


# ---------------------------------------------------------------------------
# Base envelope
# ---------------------------------------------------------------------------
class Envelope(BaseModel):
    """Unified A2A_min_v1 envelope with strict validation."""

    version: ProtocolVersion = ProtocolVersion.V1
    type: MessageType
    session_id: str = Field(..., min_length=1, max_length=128)
    corr_id: str = Field(..., min_length=1, max_length=128)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seq: Optional[int] = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("version", mode="before")
    @classmethod
    def normalize_version(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ("v1", "1"):
                return ProtocolVersion.V1
            raise ValueError(f"Unknown protocol version: {v!r}. Supported: v1")
        return v

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v: Any) -> Any:
        """Support legacy CSD_Stream_v0 message names (#32)."""
        if isinstance(v, str):
            if v in LEGACY_MESSAGE_MAP:
                return LEGACY_MESSAGE_MAP[v]
            try:
                return MessageType(v)
            except ValueError:
                valid = [m.value for m in MessageType]
                legacy = list(LEGACY_MESSAGE_MAP.keys())
                raise ValueError(
                    f"Unknown message type: {v!r}. Valid: {valid}, Legacy: {legacy}"
                )
        return v

    @model_validator(mode="after")
    def check_payload_for_type(self) -> "Envelope":
        """Validate payload contents based on message type."""
        p = self.payload
        t = self.type

        if t == MessageType.INVOKE:
            if "prompt" not in p and "messages" not in p:
                raise ValueError("INVOKE payload must contain 'prompt' or 'messages'")
            if "model" not in p:
                raise ValueError("INVOKE payload must contain 'model'")

        elif t == MessageType.STREAM_CHUNK:
            if "content" not in p:
                raise ValueError("STREAM_CHUNK payload must contain 'content'")
            if self.seq is None:
                raise ValueError("STREAM_CHUNK must have a seq field")

        elif t == MessageType.STREAM_END:
            if self.seq is None:
                raise ValueError("STREAM_END must have a seq field")

        elif t == MessageType.CANCEL:
            pass  # no special payload requirements

        elif t == MessageType.HEARTBEAT:
            pass  # no special payload requirements

        elif t == MessageType.ERROR:
            if "error_code" not in p:
                raise ValueError("ERROR payload must contain 'error_code'")

        elif t == MessageType.AGENT_DELEGATE:
            if "target_agent" not in p and "target_agents" not in p:
                raise ValueError("AGENT_DELEGATE payload must contain 'target_agent' or 'target_agents'")
            if "task" not in p:
                raise ValueError("AGENT_DELEGATE payload must contain 'task'")

        elif t == MessageType.AGENT_RESPONSE:
            if "delegation_id" not in p:
                raise ValueError("AGENT_RESPONSE payload must contain 'delegation_id'")
            if "result" not in p:
                raise ValueError("AGENT_RESPONSE payload must contain 'result'")

        return self

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Payload helper models for typed construction
# ---------------------------------------------------------------------------
class InvokePayload(BaseModel):
    model: str
    prompt: Optional[str] = None
    messages: Optional[list[dict[str, Any]]] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = True
    task_type: Optional[str] = None  # for #26 capability routing


class StreamChunkPayload(BaseModel):
    content: str
    token_index: Optional[int] = None


class StreamEndPayload(BaseModel):
    reason: str = "completed"
    total_tokens: int = 0


class ErrorPayload(BaseModel):
    error_code: str
    message: str
    recoverable: bool = False
    retry_recommended: bool = False
    source: str = "gateway"


class CancelPayload(BaseModel):
    reason: Optional[str] = None


class HeartbeatPayload(BaseModel):
    agent_status: Optional[str] = None


class AgentDelegatePayload(BaseModel):
    target_agent: str
    task: str
    pattern: str = "single"
    context: dict[str, Any] = {}
    delegation_id: Optional[str] = None
    source_agent: Optional[str] = None


class AgentResponsePayload(BaseModel):
    delegation_id: str
    result: str
    status: str = "completed"
    source_agent: Optional[str] = None


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------
def make_envelope(
    msg_type: MessageType,
    session_id: str,
    corr_id: str,
    payload: dict[str, Any],
    seq: Optional[int] = None,
) -> Envelope:
    return Envelope(
        type=msg_type,
        session_id=session_id,
        corr_id=corr_id,
        payload=payload,
        seq=seq,
    )


def make_error_envelope(
    session_id: str,
    corr_id: str,
    error_code: str,
    message: str,
    recoverable: bool = False,
    retry_recommended: bool = False,
    source: str = "gateway",
    seq: Optional[int] = None,
) -> Envelope:
    return make_envelope(
        MessageType.ERROR,
        session_id,
        corr_id,
        ErrorPayload(
            error_code=error_code,
            message=message,
            recoverable=recoverable,
            retry_recommended=retry_recommended,
            source=source,
        ).model_dump(),
        seq=seq,
    )
