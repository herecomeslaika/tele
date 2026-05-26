# A2A_min_v1 OpenTelemetry-style Trace Context

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class TraceContext:
    """
    Lightweight trace context modelled after OpenTelemetry Span conventions.

    Propagates trace_id and span_id through the Envelope payload
    so every message in a session carries a consistent trace chain.
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None = None

    @staticmethod
    def new(parent: TraceContext | None = None) -> TraceContext:
        """Create a new trace context. If parent is given, links as child span."""
        trace_id = parent.trace_id if parent else uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]
        return TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent.span_id if parent else None,
        )

    def child(self) -> TraceContext:
        """Derive a child span under this context."""
        return TraceContext.new(parent=self)

    def inject_into_envelope(self, envelope_payload: dict) -> dict:
        """Inject trace fields into an envelope payload dict."""
        payload = dict(envelope_payload)
        payload["_trace_id"] = self.trace_id
        payload["_span_id"] = self.span_id
        if self.parent_span_id:
            payload["_parent_span_id"] = self.parent_span_id
        return payload

    def extract_from_envelope(self, envelope_payload: dict) -> TraceContext | None:
        """Extract a TraceContext from an envelope payload if trace fields are present."""
        if "_trace_id" in envelope_payload and "_span_id" in envelope_payload:
            return TraceContext(
                trace_id=envelope_payload["_trace_id"],
                span_id=envelope_payload["_span_id"],
                parent_span_id=envelope_payload.get("_parent_span_id"),
            )
        return None


@dataclass
class TraceCollector:
    """
    Collects all spans for a given trace_id to reconstruct the call chain.
    Used for evidence generation and debugging — not a full OTel export pipeline.
    """

    _spans: dict[str, list[dict]] = field(default_factory=dict)

    def record_span(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None = None,
        operation: str = "",
        session_id: str = "",
        corr_id: str = "",
        provider_name: str = "",
        timestamp: float | None = None,
        **extra: object,
    ) -> None:
        import time
        span = {
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "operation": operation,
            "session_id": session_id,
            "corr_id": corr_id,
            "provider_name": provider_name,
            "timestamp": timestamp or time.time(),
        }
        span.update(extra)
        self._spans.setdefault(trace_id, []).append(span)

    def get_trace(self, trace_id: str) -> list[dict]:
        return self._spans.get(trace_id, [])

    def all_traces(self) -> dict[str, list[dict]]:
        return dict(self._spans)