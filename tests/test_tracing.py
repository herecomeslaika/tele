# Tests for Extension Goal 2: OpenTelemetry-style Tracing

import pytest

from app.core.tracing import TraceContext, TraceCollector


class TestTraceContext:
    def test_new_root_context(self):
        ctx = TraceContext.new()
        assert len(ctx.trace_id) == 32
        assert len(ctx.span_id) == 16
        assert ctx.parent_span_id is None

    def test_child_inherits_trace_id(self):
        parent = TraceContext.new()
        child = parent.child()
        assert child.trace_id == parent.trace_id
        assert child.span_id != parent.span_id
        assert child.parent_span_id == parent.span_id

    def test_inject_into_payload(self):
        ctx = TraceContext.new()
        payload = {"prompt": "hello"}
        injected = ctx.inject_into_payload(payload)
        assert "_trace_id" in injected
        assert "_span_id" in injected
        assert injected["prompt"] == "hello"

    def test_extract_from_payload(self):
        ctx = TraceContext.new()
        payload = ctx.inject_into_payload({"data": 1})
        extracted = ctx.extract_from_envelope(payload)
        assert extracted is not None
        assert extracted.trace_id == ctx.trace_id
        assert extracted.span_id == ctx.span_id

    def test_extract_missing_fields_returns_none(self):
        ctx = TraceContext.new()
        result = ctx.extract_from_envelope({"no_trace": True})
        assert result is None

    def test_chain_depth(self):
        """Verify a 3-level span chain: root → child → grandchild."""
        root = TraceContext.new()
        child = root.child()
        grandchild = child.child()
        assert grandchild.trace_id == root.trace_id
        assert grandchild.parent_span_id == child.span_id
        assert child.parent_span_id == root.span_id


class TestTraceCollector:
    def test_record_and_retrieve(self):
        collector = TraceCollector()
        ctx = TraceContext.new()
        collector.record_span(
            trace_id=ctx.trace_id,
            span_id=ctx.span_id,
            operation="gateway.invoke",
            session_id="s1",
        )
        trace = collector.get_trace(ctx.trace_id)
        assert len(trace) == 1
        assert trace[0]["operation"] == "gateway.invoke"

    def test_multi_span_trace_chain(self):
        """Simulate a full invoke→stream→end chain under one trace_id."""
        collector = TraceCollector()
        root = TraceContext.new()

        operations = ["gateway.invoke", "provider.stream.chunk", "provider.stream.end"]
        for op in operations:
            child = root.child()
            collector.record_span(
                trace_id=root.trace_id,
                span_id=child.span_id,
                parent_span_id=root.span_id,
                operation=op,
                session_id="s_chain",
            )

        trace = collector.get_trace(root.trace_id)
        assert len(trace) == 3
        assert [s["operation"] for s in trace] == operations

    def test_isolation_between_traces(self):
        collector = TraceCollector()
        t1 = TraceContext.new()
        t2 = TraceContext.new()
        collector.record_span(trace_id=t1.trace_id, span_id=t1.span_id, operation="op1")
        collector.record_span(trace_id=t2.trace_id, span_id=t2.span_id, operation="op2")

        assert len(collector.get_trace(t1.trace_id)) == 1
        assert len(collector.get_trace(t2.trace_id)) == 1
        assert collector.get_trace(t1.trace_id)[0]["operation"] == "op1"

    def test_all_traces(self):
        collector = TraceCollector()
        t1 = TraceContext.new()
        t2 = TraceContext.new()
        collector.record_span(trace_id=t1.trace_id, span_id=t1.span_id, operation="a")
        collector.record_span(trace_id=t2.trace_id, span_id=t2.span_id, operation="b")

        all_t = collector.all_traces()
        assert len(all_t) == 2

    def test_record_span_extra_fields(self):
        collector = TraceCollector()
        ctx = TraceContext.new()
        collector.record_span(
            trace_id=ctx.trace_id,
            span_id=ctx.span_id,
            operation="provider.invoke",
            provider_name="deepseek",
            latency_ms=150.0,
        )
        span = collector.get_trace(ctx.trace_id)[0]
        assert span["provider_name"] == "deepseek"
        assert span["latency_ms"] == 150.0
