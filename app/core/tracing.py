"""A2A_min_v1 OpenTelemetry-style Trace Context with span definitions."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SpanOperation(str, Enum):
    """Key span operations for A2A_min_v1 gateway.

    These correspond to OTel span names:
      - agent.invoke: Agent initiates a request
      - gateway.receive: Gateway receives and validates the message
      - gateway.validate: Schema validation step
      - gateway.route: Provider routing decision
      - provider.call: Call to the LLM provider
      - provider.stream.chunk: Each streaming token chunk
      - gateway.stream: Gateway forwards chunk to agent
      - gateway.cancel: Cancel propagation
      - gateway.heartbeat: Heartbeat processing
      - gateway.error: Error response generation
    """

    AGENT_INVOKE = "agent.invoke"
    GATEWAY_RECEIVE = "gateway.receive"
    GATEWAY_VALIDATE = "gateway.validate"
    GATEWAY_ROUTE = "gateway.route"
    PROVIDER_CALL = "provider.call"
    PROVIDER_STREAM_CHUNK = "provider.stream.chunk"
    GATEWAY_STREAM = "gateway.stream"
    GATEWAY_CANCEL = "gateway.cancel"
    GATEWAY_HEARTBEAT = "gateway.heartbeat"
    GATEWAY_ERROR = "gateway.error"


# Span attributes for each operation
SPAN_ATTRIBUTES: dict[SpanOperation, list[str]] = {
    SpanOperation.AGENT_INVOKE: ["session_id", "corr_id", "model", "prompt_length", "stream"],
    SpanOperation.GATEWAY_RECEIVE: ["session_id", "corr_id", "msg_type", "version", "seq"],
    SpanOperation.GATEWAY_VALIDATE: ["session_id", "corr_id", "validation_result", "error_code"],
    SpanOperation.GATEWAY_ROUTE: ["session_id", "corr_id", "provider_name", "strategy", "route_result"],
    SpanOperation.PROVIDER_CALL: ["session_id", "corr_id", "provider_name", "model", "latency_ms"],
    SpanOperation.PROVIDER_STREAM_CHUNK: ["session_id", "corr_id", "seq", "token_length", "latency_ms"],
    SpanOperation.GATEWAY_STREAM: ["session_id", "corr_id", "seq", "forwarded_to"],
    SpanOperation.GATEWAY_CANCEL: ["session_id", "corr_id", "cancel_reason"],
    SpanOperation.GATEWAY_HEARTBEAT: ["session_id", "corr_id", "last_seen_delta_ms"],
    SpanOperation.GATEWAY_ERROR: ["session_id", "corr_id", "error_code", "error_source", "recoverable"],
}


@dataclass
class TraceContext:
    """Lightweight trace context modelled after OpenTelemetry Span conventions."""

    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    operation: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    attributes: dict = field(default_factory=dict)

    @staticmethod
    def new(parent: Optional[TraceContext] = None, operation: Optional[str] = None) -> TraceContext:
        trace_id = parent.trace_id if parent else uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]
        ctx = TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent.span_id if parent else None,
            operation=operation,
            start_time=time.time(),
        )
        return ctx

    def child(self, operation: Optional[str] = None) -> TraceContext:
        return TraceContext.new(parent=self, operation=operation)

    def finish(self) -> None:
        self.end_time = time.time()

    def duration_ms(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return None

    def inject_into_payload(self, envelope_payload: dict) -> dict:
        payload = dict(envelope_payload)
        payload["_trace_id"] = self.trace_id
        payload["_span_id"] = self.span_id
        if self.parent_span_id:
            payload["_parent_span_id"] = self.parent_span_id
        if self.operation:
            payload["_operation"] = self.operation
        return payload

    def extract_from_envelope(self, envelope_payload: dict) -> Optional[TraceContext]:
        if "_trace_id" in envelope_payload and "_span_id" in envelope_payload:
            return TraceContext(
                trace_id=envelope_payload["_trace_id"],
                span_id=envelope_payload["_span_id"],
                parent_span_id=envelope_payload.get("_parent_span_id"),
                operation=envelope_payload.get("_operation"),
            )
        return None


@dataclass
class TraceCollector:
    """Collects all spans for a given trace_id to reconstruct the call chain."""

    _spans: dict[str, list[dict]] = field(default_factory=dict)

    def record_span(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str] = None,
        operation: str = "",
        session_id: str = "",
        corr_id: str = "",
        provider_name: str = "",
        timestamp: Optional[float] = None,
        duration_ms: Optional[float] = None,
        **extra: object,
    ) -> None:
        span = {
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "operation": operation,
            "session_id": session_id,
            "corr_id": corr_id,
            "provider_name": provider_name,
            "timestamp": timestamp or time.time(),
            "duration_ms": duration_ms,
        }
        span.update(extra)
        self._spans.setdefault(trace_id, []).append(span)

    def get_trace(self, trace_id: str) -> list[dict]:
        return self._spans.get(trace_id, [])

    def all_traces(self) -> dict[str, list[dict]]:
        return dict(self._spans)