"""A2A_min_v1 Comprehensive Test Suite — covers all extension goals."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any

import pytest

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.envelope import (
    Envelope, MessageType, ProtocolVersion, LEGACY_MESSAGE_MAP,
    make_envelope, make_error_envelope, InvokePayload, StreamChunkPayload,
    ErrorPayload, HeartbeatPayload, CancelPayload,
)
from app.models.state import SessionState
from app.core.errors import (
    ALREADY_CANCELLED, AUTH_FAILED, BAD_REQUEST, CANCELLED, DUPLICATE_INVOKE,
    EMPTY_REQUEST, FIRST_TOKEN_TIMEOUT, INVALID_MESSAGE_TYPE, INVALID_PAYLOAD,
    INVALID_VERSION, MSG_AFTER_TERMINAL, PROVIDER_ERROR, PROVIDER_RESPONSE_TIMEOUT,
    QUEUE_FULL, RATE_LIMITED, SEQ_DUPLICATE, SEQ_GAP, SEQ_ROLLBACK,
    TOTAL_TASK_TIMEOUT, TOKEN_INTERVAL_TIMEOUT, UNKNOWN_SESSION,
    get_error_def, all_error_codes,
)
from app.core.state_machine import EventType, GatewayStateMachine
from app.core.seq_checker import SeqChecker, SeqViolationKind
from app.core.timeout import TimeoutChecker, TimeoutKind
from app.core.idempotency import IdempotencyManager, IdempotencyAction
from app.core.flow_control import BoundedQueue, RateLimiter
from app.core.retry import RetryConfig, RetryManager
from app.core.metrics import Metrics
from app.core.security import SecurityConfig, SecurityManager
from app.core.policy_filter import PolicyFilter, FilterConfig
from app.core.audit import AuditEntry, AuditLogger
from app.core.tracing import SpanOperation, TraceContext, TraceCollector
from app.core.config import GatewayConfig, load_config, validate_config
from app.adapters.mock_provider import MockProviderAdapter, MockScenario
from app.adapters.provider import ProviderType
from app.adapters.router import CapabilityProfile, CapabilityRegistry


# ===========================================================================
# #1 — Protocol Schema Validation Tests
# ===========================================================================
class TestSchemaValidation:
    """Test envelope and payload validation (#1)."""

    def test_valid_invoke(self):
        env = Envelope(
            type=MessageType.INVOKE,
            session_id="s1",
            corr_id="c1",
            payload={"model": "test", "prompt": "hello"},
        )
        assert env.type == MessageType.INVOKE

    def test_missing_prompt_and_messages(self):
        with pytest.raises(ValueError, match="prompt.*messages"):
            Envelope(
                type=MessageType.INVOKE,
                session_id="s1",
                corr_id="c1",
                payload={"model": "test"},
            )

    def test_missing_model_in_invoke(self):
        with pytest.raises(ValueError, match="model"):
            Envelope(
                type=MessageType.INVOKE,
                session_id="s1",
                corr_id="c1",
                payload={"prompt": "hello"},
            )

    def test_stream_chunk_requires_content(self):
        with pytest.raises(ValueError, match="content"):
            Envelope(
                type=MessageType.STREAM_CHUNK,
                session_id="s1",
                corr_id="c1",
                seq=1,
                payload={},
            )

    def test_stream_chunk_requires_seq(self):
        with pytest.raises(ValueError, match="seq"):
            Envelope(
                type=MessageType.STREAM_CHUNK,
                session_id="s1",
                corr_id="c1",
                payload={"content": "hi"},
            )

    def test_error_requires_error_code(self):
        with pytest.raises(ValueError, match="error_code"):
            Envelope(
                type=MessageType.ERROR,
                session_id="s1",
                corr_id="c1",
                payload={"message": "something broke"},
            )

    def test_empty_session_id(self):
        with pytest.raises(ValueError):
            Envelope(
                type=MessageType.INVOKE,
                session_id="",
                corr_id="c1",
                payload={"model": "test", "prompt": "hi"},
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValueError):
            Envelope(
                type=MessageType.INVOKE,
                session_id="s1",
                corr_id="c1",
                payload={"model": "test", "prompt": "hi"},
                unknown_field="bad",
            )

    def test_invalid_version(self):
        with pytest.raises(ValueError, match="Unknown protocol version"):
            Envelope(
                type=MessageType.INVOKE,
                session_id="s1",
                corr_id="c1",
                version="v99",
                payload={"model": "test", "prompt": "hi"},
            )


# ===========================================================================
# #2 — Error Code System Tests
# ===========================================================================
class TestErrorCodeSystem:
    """Test error code table completeness and lookup (#2)."""

    def test_all_codes_have_required_fields(self):
        for code, defn in all_error_codes().items():
            assert defn.code == code
            assert defn.source in ("gateway", "agent", "provider")
            assert isinstance(defn.recoverable, bool)
            assert isinstance(defn.retry_recommended, bool)
            assert defn.description

    def test_get_unknown_error(self):
        defn = get_error_def("NONEXISTENT_CODE")
        assert defn.code == "INTERNAL_ERROR"

    def test_recoverable_codes_are_retryable(self):
        """All recoverable errors should recommend retry."""
        for code, defn in all_error_codes().items():
            if defn.recoverable:
                assert defn.retry_recommended, f"{code} is recoverable but retry_recommended=False"

    def test_timeout_errors_are_recoverable(self):
        assert FIRST_TOKEN_TIMEOUT.recoverable is True
        assert TOKEN_INTERVAL_TIMEOUT.recoverable is True
        assert TOTAL_TASK_TIMEOUT.recoverable is False  # total task is not recoverable

    def test_provider_errors_are_recoverable(self):
        assert PROVIDER_ERROR.recoverable is True


# ===========================================================================
# #5 — Seq Order Validation Tests
# ===========================================================================
class TestSeqChecker:
    """Test seq order validation (#5)."""

    def test_sequential_ok(self):
        checker = SeqChecker()
        assert checker.check("c1", 1).ok
        assert checker.check("c1", 2).ok
        assert checker.check("c1", 3).ok

    def test_duplicate_detected(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        result = checker.check("c1", 1)
        assert not result.ok
        assert result.violation == SeqViolationKind.DUPLICATE

    def test_gap_detected(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        result = checker.check("c1", 4)
        assert not result.ok
        assert result.violation == SeqViolationKind.GAP

    def test_rollback_detected(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        checker.check("c1", 2)
        result = checker.check("c1", 1)
        assert not result.ok
        assert result.violation == SeqViolationKind.ROLLBACK

    def test_independent_corr_ids(self):
        checker = SeqChecker()
        assert checker.check("c1", 1).ok
        assert checker.check("c2", 1).ok  # different corr_id, independent seq

    def test_reset(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        checker.reset("c1")
        assert checker.check("c1", 1).ok  # should work after reset


# ===========================================================================
# #6 — Terminal State Message Handling Tests
# ===========================================================================
class TestTerminalStateHandling:
    """Test message handling after terminal state (#6)."""

    def test_reject_stream_chunk_after_done(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        sm.on_event(EventType.STREAM_CHUNK)
        sm.on_event(EventType.STREAM_END)  # -> Done
        result = sm.on_event(EventType.STREAM_CHUNK)
        assert not result.accepted
        assert "terminal" in result.reason.lower()

    def test_reject_cancel_after_done(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        sm.on_event(EventType.STREAM_END)  # -> Done
        result = sm.on_event(EventType.CANCEL)
        assert not result.accepted

    def test_reject_invoke_after_cancelled(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        sm.on_event(EventType.CANCEL)  # -> Cancelled
        result = sm.on_event(EventType.INVOKE)
        assert not result.accepted

    def test_reject_error_after_failed(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        sm.on_event(EventType.ERROR)  # -> Failed
        result = sm.on_event(EventType.ERROR)
        assert not result.accepted


# ===========================================================================
# #7 — State Machine Tests
# ===========================================================================
class TestStateMachine:
    """Test state machine transitions (#7)."""

    def test_full_happy_path(self):
        sm = GatewayStateMachine(session_id="s1")
        r = sm.on_event(EventType.INVOKE)
        assert r.accepted and r.new_state == SessionState.INVOKED

        r = sm.on_event(EventType.STREAM_CHUNK)
        assert r.accepted and r.new_state == SessionState.STREAMING

        r = sm.on_event(EventType.STREAM_CHUNK)
        assert r.accepted and r.new_state == SessionState.STREAMING

        r = sm.on_event(EventType.STREAM_END)
        assert r.accepted and r.new_state == SessionState.DONE

    def test_cancel_path(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        r = sm.on_event(EventType.CANCEL)
        assert r.accepted and r.new_state == SessionState.CANCELLED

    def test_error_path(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        r = sm.on_event(EventType.ERROR)
        assert r.accepted and r.new_state == SessionState.FAILED

    def test_timeout_path(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        r = sm.on_event(EventType.TIMEOUT)
        assert r.accepted and r.new_state == SessionState.FAILED

    def test_invoke_from_idle_only(self):
        sm = GatewayStateMachine(session_id="s1")
        r = sm.on_event(EventType.STREAM_CHUNK)
        assert not r.accepted

    def test_state_corresponds_to_lab02(self):
        """SessionState values correspond to D5 state path:
        Idle -> Invoked -> Streaming -> Done/Failed/Cancelled"""
        assert SessionState.IDLE.value == "Idle"
        assert SessionState.INVOKED.value == "Invoked"
        assert SessionState.STREAMING.value == "Streaming"
        assert SessionState.DONE.value == "Done"
        assert SessionState.FAILED.value == "Failed"
        assert SessionState.CANCELLED.value == "Cancelled"
        assert SessionState.DONE.is_terminal
        assert SessionState.FAILED.is_terminal
        assert SessionState.CANCELLED.is_terminal


# ===========================================================================
# #8 — HEARTBEAT Tests
# ===========================================================================
class TestHeartbeat:
    """Test HEARTBEAT handling (#8)."""

    def test_heartbeat_in_invoked_state(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        r = sm.on_event(EventType.HEARTBEAT)
        assert r.accepted

    def test_heartbeat_in_idle_rejected(self):
        sm = GatewayStateMachine(session_id="s1")
        r = sm.on_event(EventType.HEARTBEAT)
        assert not r.accepted

    def test_heartbeat_updates_last_seen(self):
        checker = TimeoutChecker()
        checker.register("s1", "c1")
        old_last = checker.get("s1").last_seen
        time.sleep(0.01)
        checker.on_heartbeat("s1")
        new_last = checker.get("s1").last_seen
        assert new_last > old_last


# ===========================================================================
# #9 — CANCEL Propagation Tests
# ===========================================================================
class TestCancelPropagation:
    """Test CANCEL propagation (#9)."""

    def test_cancel_sets_cancelled_state(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        r = sm.on_event(EventType.CANCEL)
        assert r.new_state == SessionState.CANCELLED

    def test_cancel_in_streaming_state(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        sm.on_event(EventType.STREAM_CHUNK)
        r = sm.on_event(EventType.CANCEL)
        assert r.new_state == SessionState.CANCELLED

    def test_cancel_after_terminal_rejected(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(EventType.INVOKE)
        sm.on_event(EventType.STREAM_END)  # Done
        r = sm.on_event(EventType.CANCEL)
        assert not r.accepted

    def test_idempotency_cancel_already_cancelled(self):
        im = IdempotencyManager()
        im.register("c1", "INVOKE", SessionState.INVOKED)
        im.update_state("c1", SessionState.CANCELLED)
        action, _ = im.check_cancel("c1")
        assert action == IdempotencyAction.IGNORE


# ===========================================================================
# #11 — Timeout Classification Tests
# ===========================================================================
class TestTimeoutClassification:
    """Test timeout type classification (#11)."""

    def test_first_token_timeout(self):
        checker = TimeoutChecker(first_token_timeout=0.01, total_task_timeout=999,
                                  provider_response_timeout=999, token_interval_timeout=999)
        checker.register("s1", "c1")
        time.sleep(0.02)
        results = checker.check_timeouts()
        kinds = [r[1] for r in results]
        assert TimeoutKind.FIRST_TOKEN in kinds

    def test_total_task_timeout(self):
        checker = TimeoutChecker(first_token_timeout=999, total_task_timeout=0.01,
                                  provider_response_timeout=999, token_interval_timeout=999)
        checker.register("s1", "c1")
        time.sleep(0.02)
        results = checker.check_timeouts()
        kinds = [r[1] for r in results]
        assert TimeoutKind.TOTAL_TASK in kinds

    def test_token_interval_timeout(self):
        checker = TimeoutChecker(first_token_timeout=999, total_task_timeout=999,
                                  provider_response_timeout=999, token_interval_timeout=0.01)
        checker.register("s1", "c1")
        checker.on_chunk("s1")
        time.sleep(0.02)
        results = checker.check_timeouts()
        kinds = [r[1] for r in results]
        assert TimeoutKind.TOKEN_INTERVAL in kinds

    def test_provider_response_timeout(self):
        checker = TimeoutChecker(first_token_timeout=999, total_task_timeout=999,
                                  provider_response_timeout=0.01, token_interval_timeout=999)
        checker.register("s1", "c1")
        time.sleep(0.02)
        results = checker.check_timeouts()
        kinds = [r[1] for r in results]
        assert TimeoutKind.PROVIDER_RESPONSE in kinds


# ===========================================================================
# #3 — Retry Mechanism Tests
# ===========================================================================
class TestRetryMechanism:
    """Test retry for recoverable errors (#3)."""

    @pytest.mark.asyncio
    async def test_retry_on_recoverable_error(self):
        rm = RetryManager(config=RetryConfig(max_retries=2, base_delay=0.01))
        call_count = 0

        async def failing_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                from app.models.envelope import make_error_envelope
                return make_error_envelope("s1", "c1", "PROVIDER_ERROR", "transient")
            return {"type": "SUCCESS"}

        result = await rm.execute_with_retry(failing_fn)
        assert result.success
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_recoverable(self):
        rm = RetryManager(config=RetryConfig(max_retries=3, base_delay=0.01))

        async def failing_fn():
            from app.models.envelope import make_error_envelope
            return make_error_envelope("s1", "c1", "BAD_REQUEST", "invalid")

        result = await rm.execute_with_retry(failing_fn)
        assert not result.success
        assert result.attempts == 1


# ===========================================================================
# #4 — Idempotency Tests
# ===========================================================================
class TestIdempotency:
    """Test idempotent handling of duplicate messages (#4)."""

    def test_duplicate_invoke_rejected(self):
        im = IdempotencyManager()
        im.register("c1", "INVOKE", SessionState.INVOKED)
        action, _ = im.check_invoke("c1")
        assert action == IdempotencyAction.REJECT

    def test_duplicate_invoke_terminal_reuses(self):
        im = IdempotencyManager()
        im.register("c1", "INVOKE", SessionState.DONE)
        action, cached = im.check_invoke("c1")
        assert action == IdempotencyAction.REUSE
        assert cached.state == SessionState.DONE

    def test_duplicate_cancel_ignored(self):
        im = IdempotencyManager()
        im.register("c1", "INVOKE", SessionState.CANCELLED)
        action, _ = im.check_cancel("c1")
        assert action == IdempotencyAction.IGNORE

    def test_duplicate_stream_end_ignored(self):
        im = IdempotencyManager()
        im.register("c1", "INVOKE", SessionState.DONE)
        action, _ = im.check_stream_end("c1")
        assert action == IdempotencyAction.IGNORE


# ===========================================================================
# #10 — Flow Control Tests
# ===========================================================================
class TestFlowControl:
    """Test bounded queue and rate limiter (#10)."""

    def test_bounded_queue_push_pop(self):
        q = BoundedQueue(max_length=3)
        assert q.push("a")
        assert q.push("b")
        assert q.push("c")
        assert q.is_full
        q.push("d")  # should drop "a", returns False (dropped)
        assert q.pop() == "b"

    def test_bounded_queue_full_drops_oldest(self):
        q = BoundedQueue(max_length=2)
        q.push("a")
        q.push("b")
        q.push("c")  # drops "a"
        assert q.pop() == "b"

    def test_rate_limiter_allows_within_limit(self):
        rl = RateLimiter(max_tokens=10, refill_rate=100)
        for _ in range(10):
            assert rl.acquire()

    def test_rate_limiter_blocks_over_limit(self):
        rl = RateLimiter(max_tokens=2, refill_rate=0)
        assert rl.acquire()
        assert rl.acquire()
        assert not rl.acquire()


# ===========================================================================
# #12 — Provider Adapter Tests
# ===========================================================================
class TestProviderAdapter:
    """Test provider adapter system (#12, #36)."""

    @pytest.mark.asyncio
    async def test_mock_provider_normal(self):
        provider = MockProviderAdapter(scenario=MockScenario.NORMAL, chunk_count=3)
        chunks = []
        async for event in provider.invoke("test"):
            chunks.append(event)
        assert any(e.type == "end" for e in chunks)
        assert sum(1 for e in chunks if e.type == "chunk") == 3

    @pytest.mark.asyncio
    async def test_mock_provider_error(self):
        provider = MockProviderAdapter(scenario=MockScenario.ERROR)
        chunks = []
        async for event in provider.invoke("test"):
            chunks.append(event)
        assert chunks[0].type == "error"

    @pytest.mark.asyncio
    async def test_mock_provider_timeout(self):
        provider = MockProviderAdapter(scenario=MockScenario.TIMEOUT)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                anext(provider.invoke("test").__aiter__()),
                timeout=0.1,
            )

    @pytest.mark.asyncio
    async def test_mock_provider_mid_stream_error(self):
        provider = MockProviderAdapter(scenario=MockScenario.MID_STREAM_ERROR,
                                        error_after_chunk=1)
        chunks = []
        async for event in provider.invoke("test"):
            chunks.append(event)
        assert any(e.type == "error" for e in chunks)


# ===========================================================================
# #16, #18 — Structured Logging and Tracing Tests
# ===========================================================================
class TestLoggingAndTracing:
    """Test structured logging and tracing (#16, #18)."""

    def test_trace_context_hierarchy(self):
        parent = TraceContext.new(operation="agent.invoke")
        child = parent.child(operation="gateway.receive")
        grandchild = child.child(operation="provider.call")

        assert child.parent_span_id == parent.span_id
        assert grandchild.parent_span_id == child.span_id
        assert parent.trace_id == child.trace_id == grandchild.trace_id

    def test_trace_duration(self):
        ctx = TraceContext.new()
        ctx.start_time = time.time() - 1.0
        ctx.finish()
        assert ctx.duration_ms() is not None
        assert ctx.duration_ms() >= 900

    def test_trace_collector(self):
        tc = TraceCollector()
        tc.record_span(
            trace_id="t1", span_id="s1", operation="agent.invoke",
            session_id="sess1", corr_id="c1"
        )
        tc.record_span(
            trace_id="t1", span_id="s2", parent_span_id="s1",
            operation="gateway.receive", session_id="sess1", corr_id="c1"
        )
        trace = tc.get_trace("t1")
        assert len(trace) == 2
        assert trace[1]["parent_span_id"] == "s1"

    def test_span_operations_defined(self):
        """All required span operations exist."""
        for op in ["agent.invoke", "gateway.receive", "provider.call", "gateway.stream"]:
            assert any(s.value == op for s in SpanOperation)

    def test_span_attributes_defined(self):
        """All required spans have attribute lists."""
        for op in SpanOperation:
            assert op in SpanOperation.__members__.values() or isinstance(op, SpanOperation)
            assert op in SPAN_ATTRIBUTES or any(
                s == op for s in SPAN_ATTRIBUTES.keys()
            )


# ===========================================================================
# #17 — Metrics Tests
# ===========================================================================
class TestMetrics:
    """Test metrics collection (#17)."""

    def test_record_success(self):
        m = Metrics()
        m.record_request()
        m.record_success(first_token_latency=150.0, total_duration=2000.0)
        assert m.request_count == 1
        assert m.success_count == 1
        assert m.avg_first_token_latency() == 150.0

    def test_record_failure(self):
        m = Metrics()
        m.record_request()
        m.record_failure()
        assert m.failure_count == 1

    def test_record_cancel(self):
        m = Metrics()
        m.record_request()
        m.record_cancel()
        assert m.cancel_count == 1

    def test_record_timeout(self):
        m = Metrics()
        m.record_request()
        m.record_timeout()
        assert m.timeout_count == 1

    def test_summary(self):
        m = Metrics()
        m.record_request()
        m.record_success(first_token_latency=100.0, total_duration=500.0)
        summary = m.summary()
        assert "request_count" in summary
        assert "avg_first_token_latency_ms" in summary


# ===========================================================================
# #27 — Audit Tests
# ===========================================================================
class TestAudit:
    """Test persistent audit (#27)."""

    def test_audit_record_and_query(self, tmp_path):
        audit = AuditLogger(log_dir=str(tmp_path / "audit"))
        audit.record(AuditEntry(
            session_id="s1", corr_id="c1", event="INVOKE",
            model="test-model", trace_id="t1",
        ))
        audit.record(AuditEntry(
            session_id="s1", corr_id="c1", event="STREAM_END",
            duration_ms=1500.0,
        ))

        entries = audit.query_by_corr_id("c1")
        assert len(entries) == 2
        assert entries[0].event == "INVOKE"
        assert entries[1].event == "STREAM_END"

    def test_audit_persistence(self, tmp_path):
        audit = AuditLogger(log_dir=str(tmp_path / "audit"))
        audit.record(AuditEntry(session_id="s1", corr_id="c1", event="INVOKE"))
        assert audit.count() == 1
        assert os.path.exists(audit._file_path)
        # Verify file content is valid JSONL
        with open(audit._file_path, "r", encoding="utf-8") as f:
            line = json.loads(f.readline())
            assert line["event"] == "INVOKE"

    def test_audit_reload_across_instances(self, tmp_path):
        """Audit entries persist across logger instances (#27)."""
        log_dir = str(tmp_path / "audit")
        audit1 = AuditLogger(log_dir=log_dir)
        audit1.record(AuditEntry(session_id="s1", corr_id="c1", event="INVOKE"))
        audit1.record(AuditEntry(session_id="s1", corr_id="c1", event="STREAM_END", duration_ms=500.0))
        assert audit1.count() == 2

        # Simulate restart — new instance loads existing files
        audit2 = AuditLogger(log_dir=log_dir)
        assert audit2.count() == 2
        entries = audit2.query_by_corr_id("c1")
        assert len(entries) == 2

    def test_audit_flexible_query(self, tmp_path):
        """Query with session_id, event, and time range filters."""
        audit = AuditLogger(log_dir=str(tmp_path / "audit"))
        t0 = time.time()
        audit.record(AuditEntry(session_id="s1", corr_id="c1", event="INVOKE"))
        audit.record(AuditEntry(session_id="s1", corr_id="c2", event="CANCEL"))
        audit.record(AuditEntry(session_id="s2", corr_id="c3", event="INVOKE"))

        # Filter by session_id
        results = audit.query(session_id="s1")
        assert len(results) == 2

        # Filter by event
        results = audit.query(event="INVOKE")
        assert len(results) == 2

        # Filter by time range
        results = audit.query(start_time=t0 - 1, end_time=time.time() + 1)
        assert len(results) == 3

        # Combined filter
        results = audit.query(session_id="s1", event="CANCEL")
        assert len(results) == 1
        assert results[0].corr_id == "c2"

    def test_audit_export_to_file(self, tmp_path):
        """Export all entries to a standalone JSON file."""
        audit = AuditLogger(log_dir=str(tmp_path / "audit"))
        audit.record(AuditEntry(session_id="s1", corr_id="c1", event="INVOKE", model="test"))
        out_path = str(tmp_path / "export.json")
        audit.export_to_file(out_path)
        assert os.path.exists(out_path)
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["event"] == "INVOKE"


# ===========================================================================
# #26 — Capability Routing Tests
# ===========================================================================
class TestCapabilityRouting:
    """Test model capability routing with CapabilityRegistry (#26)."""

    def test_register_and_lookup(self):
        reg = CapabilityRegistry()
        reg.register(CapabilityProfile(
            name="deepseek",
            capabilities=["chat", "code", "reasoning"],
            models=["deepseek-chat", "deepseek-coder"],
            task_types=["chat", "code"],
            supports_streaming=True,
            supports_tools=True,
        ))
        reg.register(CapabilityProfile(
            name="ollama-local",
            capabilities=["chat", "code"],
            models=["llama3", "mistral"],
            task_types=["chat"],
            max_context_tokens=8192,
        ))
        assert reg.get("deepseek") is not None
        assert reg.get("nonexistent") is None

    def test_find_by_capability(self):
        reg = CapabilityRegistry()
        reg.register(CapabilityProfile(name="p1", capabilities=["chat", "reasoning"]))
        reg.register(CapabilityProfile(name="p2", capabilities=["chat", "code"]))
        reg.register(CapabilityProfile(name="p3", capabilities=["vision"]))

        results = reg.find_by_capability(["chat"])
        assert "p1" in results
        assert "p2" in results
        assert "p3" not in results

        results = reg.find_by_capability(["reasoning"])
        assert results == ["p1"]

        results = reg.find_by_capability(["chat", "code"])
        assert results == ["p2"]

    def test_find_by_model(self):
        reg = CapabilityRegistry()
        reg.register(CapabilityProfile(name="p1", models=["deepseek-chat", "deepseek-coder"]))
        reg.register(CapabilityProfile(name="p2", models=["llama3"]))

        results = reg.find_by_model("deepseek-chat")
        assert results == ["p1"]

        results = reg.find_by_model("llama3")
        assert results == ["p2"]

        results = reg.find_by_model("unknown-model")
        assert results == []

    def test_find_by_task_type(self):
        reg = CapabilityRegistry()
        reg.register(CapabilityProfile(name="p1", task_types=["chat", "code"]))
        reg.register(CapabilityProfile(name="p2", task_types=["reasoning"]))

        results = reg.find_by_task_type("code")
        assert results == ["p1"]

        results = reg.find_by_task_type("reasoning")
        assert results == ["p2"]

    def test_best_match_intersection(self):
        """best_match intersects model + capability + task_type filters."""
        reg = CapabilityRegistry()
        reg.register(CapabilityProfile(
            name="full-provider",
            capabilities=["chat", "code", "reasoning"],
            models=["model-a"],
            task_types=["chat", "code"],
        ))
        reg.register(CapabilityProfile(
            name="chat-only",
            capabilities=["chat"],
            models=["model-b"],
            task_types=["chat"],
        ))

        # Model + capability
        match = reg.best_match(model="model-a", capabilities=["code"])
        assert match == "full-provider"

        # Capability that only full-provider has
        match = reg.best_match(capabilities=["reasoning"])
        assert match == "full-provider"

        # No match
        match = reg.best_match(model="model-b", capabilities=["vision"])
        assert match is None

    def test_capability_routing_in_router(self):
        """ProviderRouter with capability strategy uses CapabilityRegistry."""
        from app.adapters.router import ProviderRouter

        mock1 = MockProviderAdapter(scenario=MockScenario.NORMAL)
        mock2 = MockProviderAdapter(scenario=MockScenario.NORMAL)

        router = ProviderRouter(strategy="capability")
        router.add_route(name="code-provider", adapter=mock1,
                         capabilities=["code", "reasoning"], models=["coder-v1"])
        router.add_route(name="chat-provider", adapter=mock2,
                         capabilities=["chat"], models=["chat-v1"])

        name, _ = router.select(session_id="s1", capabilities=["code"])
        assert name == "code-provider"

        name, _ = router.select(session_id="s1", capabilities=["chat"])
        assert name == "chat-provider"

    def test_capability_routing_fallback(self):
        """If no capability matches, fallback to first provider."""
        from app.adapters.router import ProviderRouter

        mock1 = MockProviderAdapter(scenario=MockScenario.NORMAL)
        mock2 = MockProviderAdapter(scenario=MockScenario.NORMAL)

        router = ProviderRouter(strategy="capability")
        router.add_route(name="code-provider", adapter=mock1,
                         capabilities=["code"], models=["coder-v1"])
        router.add_route(name="chat-provider", adapter=mock2,
                         capabilities=["chat"], models=["chat-v1"])

        # Request vision (no provider has it) → fallback to first
        name, _ = router.select(session_id="s1", capabilities=["vision"])
        assert name == "code-provider"

    def test_model_routing_uses_registry(self):
        """model_name strategy leverages CapabilityRegistry for smart match."""
        from app.adapters.router import ProviderRouter

        mock1 = MockProviderAdapter(scenario=MockScenario.NORMAL)
        mock2 = MockProviderAdapter(scenario=MockScenario.NORMAL)

        router = ProviderRouter(strategy="model_name")
        router.add_route(name="deepseek", adapter=mock1, models=["deepseek-chat"])
        router.add_route(name="ollama", adapter=mock2, models=["llama3"])

        name, _ = router.select(session_id="s1", model="deepseek-chat")
        assert name == "deepseek"

        name, _ = router.select(session_id="s1", model="llama3")
        assert name == "ollama"


# ===========================================================================
# #28 — Security Tests
# ===========================================================================
class TestSecurity:
    """Test security boundary (#28)."""

    def test_api_key_validation(self):
        sm = SecurityManager(SecurityConfig(api_keys=["key1", "key2"]))
        assert sm.validate_api_key("key1")
        assert not sm.validate_api_key("bad")
        assert not sm.validate_api_key(None)

    def test_agent_registration(self):
        sm = SecurityManager(SecurityConfig(require_agent_id=True))
        key = sm.register_agent("agent-1", roles=["admin"])
        assert sm.validate_api_key(key)
        assert sm.validate_agent_id("agent-1")

    def test_input_length_check(self):
        sm = SecurityManager(SecurityConfig(max_input_length=10))
        ok, length = sm.check_input_length("short")
        assert ok
        ok, length = sm.check_input_length("a" * 20)
        assert not ok

    def test_sensitive_field_masking(self):
        sm = SecurityManager()
        data = {"name": "Alice", "api_key": "sk-12345678", "password": "secret123"}
        masked = sm.mask_sensitive_fields(data)
        assert masked["name"] == "Alice"
        assert "****" in masked["api_key"]
        assert "****" in masked["password"]


# ===========================================================================
# #29 — I/O Policy Filter Tests
# ===========================================================================
class TestPolicyFilter:
    """Test I/O policy filtering (#29)."""

    def test_empty_request_rejected(self):
        pf = PolicyFilter()
        result = pf.filter_input({"prompt": "", "messages": []})
        assert not result.passed
        assert result.error_code == "EMPTY_REQUEST"

    def test_input_too_long(self):
        pf = PolicyFilter(FilterConfig(max_input_chars=10))
        result = pf.filter_input({"prompt": "a" * 100, "messages": []})
        assert not result.passed
        assert result.error_code == "INPUT_TOO_LONG"

    def test_output_too_long(self):
        pf = PolicyFilter(FilterConfig(max_output_chars=10))
        result = pf.filter_output("a" * 100)
        assert not result.passed
        assert result.error_code == "OUTPUT_TOO_LONG"

    def test_sensitive_field_masking_in_filter(self):
        pf = PolicyFilter()
        result = pf.filter_input({"prompt": "hello", "messages": [], "api_key": "sk-secret"})
        assert result.passed
        assert result.masked_data is not None
        assert "****" in result.masked_data.get("api_key", "")


# ===========================================================================
# #32 — Protocol Compatibility Tests
# ===========================================================================
class TestProtocolCompatibility:
    """Test CSD_Stream_v0 legacy message name support (#32)."""

    def test_legacy_task_start_mapped_to_invoke(self):
        env = Envelope(
            type="TASK_START",
            session_id="s1",
            corr_id="c1",
            payload={"model": "test", "prompt": "hi"},
        )
        assert env.type == MessageType.INVOKE

    def test_legacy_chunk_mapped(self):
        env = Envelope(
            type="CHUNK",
            session_id="s1",
            corr_id="c1",
            seq=1,
            payload={"content": "hello"},
        )
        assert env.type == MessageType.STREAM_CHUNK

    def test_legacy_stop_mapped(self):
        env = Envelope(
            type="STOP",
            session_id="s1",
            corr_id="c1",
            payload={},
        )
        assert env.type == MessageType.CANCEL

    def test_legacy_ping_mapped(self):
        env = Envelope(
            type="PING",
            session_id="s1",
            corr_id="c1",
            payload={},
        )
        assert env.type == MessageType.HEARTBEAT

    def test_legacy_fail_mapped(self):
        env = Envelope(
            type="FAIL",
            session_id="s1",
            corr_id="c1",
            payload={"error_code": "TEST"},
        )
        assert env.type == MessageType.ERROR

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError, match="Unknown message type"):
            Envelope(
                type="NONEXISTENT",
                session_id="s1",
                corr_id="c1",
                payload={},
            )


# ===========================================================================
# #33 — Version Negotiation Tests
# ===========================================================================
class TestVersionNegotiation:
    """Test version handling (#33)."""

    def test_v1_accepted(self):
        env = Envelope(
            type=MessageType.INVOKE,
            session_id="s1",
            corr_id="c1",
            version="v1",
            payload={"model": "test", "prompt": "hi"},
        )
        assert env.version == ProtocolVersion.V1

    def test_numeric_1_accepted(self):
        env = Envelope(
            type=MessageType.INVOKE,
            session_id="s1",
            corr_id="c1",
            version="1",
            payload={"model": "test", "prompt": "hi"},
        )
        assert env.version == ProtocolVersion.V1

    def test_v99_rejected(self):
        with pytest.raises(ValueError, match="Unknown protocol version"):
            Envelope(
                type=MessageType.INVOKE,
                session_id="s1",
                corr_id="c1",
                version="v99",
                payload={"model": "test", "prompt": "hi"},
            )


# ===========================================================================
# #22 — Fault Injection Tests
# ===========================================================================
class TestFaultInjection:
    """Test fault injection scenarios (#22)."""

    @pytest.mark.asyncio
    async def test_delay_injection(self):
        provider = MockProviderAdapter(scenario=MockScenario.DELAY, chunk_delay=0.05)
        start = time.time()
        chunks = []
        async for event in provider.invoke("test"):
            chunks.append(event)
        elapsed = time.time() - start
        assert elapsed >= 0.1  # should have some delay

    @pytest.mark.asyncio
    async def test_mid_stream_error_injection(self):
        provider = MockProviderAdapter(scenario=MockScenario.MID_STREAM_ERROR,
                                        error_after_chunk=1)
        chunks = []
        async for event in provider.invoke("test"):
            chunks.append(event)
        types = [c.type for c in chunks]
        assert "chunk" in types
        assert "error" in types

    @pytest.mark.asyncio
    async def test_duplicate_token_injection(self):
        provider = MockProviderAdapter(scenario=MockScenario.DUPLICATE_TOKEN,
                                        chunk_count=2)
        chunks = []
        async for event in provider.invoke("test"):
            if event.type == "chunk":
                chunks.append(event.content)
        # Each token should appear twice
        assert len(chunks) == 4  # 2 chunks * 2 duplicates

    @pytest.mark.asyncio
    async def test_bad_json_injection(self):
        provider = MockProviderAdapter(scenario=MockScenario.BAD_JSON)
        chunks = []
        async for event in provider.invoke("test"):
            chunks.append(event)
        assert len(chunks) >= 2

    @pytest.mark.asyncio
    async def test_partial_disconnect_injection(self):
        provider = MockProviderAdapter(scenario=MockScenario.PARTIAL_DISCONNECT)
        chunks = []
        async for event in provider.invoke("test"):
            chunks.append(event)
        types = [c.type for c in chunks]
        assert "end" not in types  # Should NOT have an end event


# ===========================================================================
# #15 — Configuration Tests
# ===========================================================================
class TestConfiguration:
    """Test configurable gateway (#15)."""

    def test_default_config_valid(self):
        config = GatewayConfig()
        errors = validate_config(config)
        # Default config has no providers, so expect that error
        assert any("No providers" in e for e in errors)

    def test_config_with_provider(self):
        from app.core.config import ProviderEntry
        config = GatewayConfig(
            providers=[ProviderEntry(
                provider_type="mock", name="test",
                endpoint="http://localhost:9000", model="test-model",
            )]
        )
        errors = validate_config(config)
        assert len(errors) == 0

    def test_load_config_from_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "GATEWAY_PORT=9999\n"
            "PROVIDER1_TYPE=mock\n"
            "PROVIDER1_NAME=test\n"
            "PROVIDER1_ENDPOINT=http://localhost:9000\n"
            "PROVIDER1_MODEL=test-model\n"
        )
        config = load_config(str(env_file))
        assert config.port == 9999
        assert len(config.providers) == 1

    def test_invalid_strategy_detected(self):
        from app.core.config import ProviderEntry
        config = GatewayConfig(
            strategy="invalid",
            providers=[ProviderEntry(
                provider_type="mock", name="test",
                endpoint="http://localhost:9000", model="test",
            )]
        )
        errors = validate_config(config)
        assert any("strategy" in e.lower() for e in errors)


# ===========================================================================
# #24 — Concurrent Session Isolation Tests
# ===========================================================================
class TestConcurrentIsolation:
    """Test concurrent session isolation (#24)."""

    def test_independent_state_machines(self):
        sm1 = GatewayStateMachine(session_id="s1")
        sm2 = GatewayStateMachine(session_id="s2")

        sm1.on_event(EventType.INVOKE)
        sm2.on_event(EventType.INVOKE)
        sm1.on_event(EventType.STREAM_CHUNK)
        # sm2 is still INVOKED

        assert sm1.state == SessionState.STREAMING
        assert sm2.state == SessionState.INVOKED

    def test_independent_seq_checkers(self):
        checker = SeqChecker()
        assert checker.check("c1", 1).ok
        assert checker.check("c2", 1).ok  # different corr_id, independent

    def test_cancel_does_not_affect_other_session(self):
        sm1 = GatewayStateMachine(session_id="s1")
        sm2 = GatewayStateMachine(session_id="s2")

        sm1.on_event(EventType.INVOKE)
        sm2.on_event(EventType.INVOKE)

        sm1.on_event(EventType.CANCEL)
        assert sm1.state == SessionState.CANCELLED
        assert sm2.state == SessionState.INVOKED

    @pytest.mark.asyncio
    async def test_concurrent_invoke_isolation(self):
        """Two concurrent invocations should not interfere."""
        provider1 = MockProviderAdapter(scenario=MockScenario.NORMAL, chunk_count=2)
        provider2 = MockProviderAdapter(scenario=MockScenario.NORMAL, chunk_count=3)

        results: dict[str, list] = {"s1": [], "s2": []}

        async def invoke(session_id, provider):
            async for event in provider.invoke("test"):
                if event.type == "chunk":
                    results[session_id].append(event.content)

        await asyncio.gather(
            invoke("s1", provider1),
            invoke("s2", provider2),
        )

        # Each session should have received its own tokens
        assert len(results["s1"]) == 2
        assert len(results["s2"]) == 3


# ===========================================================================
# #19 — OpenTelemetry Span Tests
# ===========================================================================
class TestOpenTelemetry:
    """Test OTel span definitions (#19)."""

    def test_all_required_spans_exist(self):
        required = ["agent.invoke", "gateway.receive", "provider.call", "gateway.stream"]
        for name in required:
            assert any(s.value == name for s in SpanOperation), f"Missing span: {name}"

    def test_span_attributes_complete(self):
        for op in SpanOperation:
            assert op in SPAN_ATTRIBUTES, f"Missing attributes for span: {op}"
            assert len(SPAN_ATTRIBUTES[op]) > 0

    def test_trace_propagation(self):
        parent = TraceContext.new(operation="agent.invoke")
        parent.attributes["session_id"] = "s1"
        child = parent.child(operation="gateway.receive")

        payload = {}
        injected = child.inject_into_payload(payload)
        assert "_trace_id" in injected
        assert injected["_trace_id"] == parent.trace_id


# ===========================================================================
# Integration Test — Full Pipeline
# ===========================================================================
class TestIntegration:
    """Integration tests covering the full INVOKE -> STREAM -> END pipeline."""

    @pytest.mark.asyncio
    async def test_full_invoke_pipeline(self):
        from app.main import GatewayApp, GatewayConfig
        from app.core.config import ProviderEntry

        config = GatewayConfig(
            providers=[ProviderEntry(
                provider_type="mock", name="mock",
                endpoint="mock://localhost", model="mock-model",
                api_key="unused",
            )],
            security_enabled=False,
        )
        gateway = GatewayApp(config)

        envelope = {
            "version": "v1",
            "type": "INVOKE",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {"model": "mock-model", "prompt": "test"},
        }

        chunks = []
        async for chunk in gateway.handle_envelope(envelope):
            chunks.append(chunk)

        types = [c.get("type") for c in chunks]
        assert "STREAM_CHUNK" in types
        assert "STREAM_END" in types

    @pytest.mark.asyncio
    async def test_cancel_pipeline(self):
        from app.main import GatewayApp, GatewayConfig
        from app.core.config import ProviderEntry

        config = GatewayConfig(
            providers=[ProviderEntry(
                provider_type="mock", name="mock",
                endpoint="mock://localhost", model="mock-model",
                api_key="unused",
            )],
            security_enabled=False,
        )
        gateway = GatewayApp(config)

        # First invoke
        envelope = {
            "version": "v1",
            "type": "INVOKE",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {"model": "mock-model", "prompt": "test"},
        }
        # We don't need to wait for all chunks for cancel test

        # Then cancel
        cancel_env = {
            "version": "v1",
            "type": "CANCEL",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {},
        }
        result = await gateway.handle_cancel(Envelope(**cancel_env))
        assert result.get("type") == "ERROR" or "CANCELLED" in str(result)

    @pytest.mark.asyncio
    async def test_heartbeat_pipeline(self):
        from app.main import GatewayApp, GatewayConfig
        from app.core.config import ProviderEntry

        config = GatewayConfig(
            providers=[ProviderEntry(
                provider_type="mock", name="mock",
                endpoint="mock://localhost", model="mock-model",
                api_key="unused",
            )],
            security_enabled=False,
        )
        gateway = GatewayApp(config)

        env = {
            "version": "v1",
            "type": "HEARTBEAT",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {},
        }
        result = await gateway.handle_heartbeat(Envelope(**env))
        assert result.get("type") == "HEARTBEAT"
        assert "last_seen" in result.get("payload", {})

    @pytest.mark.asyncio
    async def test_bad_request_returns_error(self):
        from app.main import GatewayApp, GatewayConfig

        config = GatewayConfig(security_enabled=False)
        gateway = GatewayApp(config)

        bad_env = {
            "version": "v1",
            "type": "INVOKE",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {},  # missing prompt and model
        }
        chunks = []
        async for chunk in gateway.handle_envelope(bad_env):
            chunks.append(chunk)

        assert len(chunks) >= 1
        assert chunks[0].get("type") == "ERROR"
        assert chunks[0].get("payload", {}).get("error_code") == "BAD_REQUEST"

    @pytest.mark.asyncio
    async def test_seq_error_returns_error(self):
        """Test that a seq error in STREAM_CHUNK produces an error."""
        from app.main import GatewayApp, GatewayConfig

        config = GatewayConfig(security_enabled=False)
        gateway = GatewayApp(config)

        # First, establish a session
        env1 = {
            "version": "v1",
            "type": "STREAM_CHUNK",
            "session_id": "s1",
            "corr_id": "c1",
            "seq": 1,
            "payload": {"content": "chunk1"},
        }
        chunks1 = []
        async for chunk in gateway.handle_envelope(env1):
            chunks1.append(chunk)

        # Now send a duplicate seq
        env2 = {
            "version": "v1",
            "type": "STREAM_CHUNK",
            "session_id": "s1",
            "corr_id": "c1",
            "seq": 1,  # duplicate
            "payload": {"content": "chunk2"},
        }
        chunks2 = []
        async for chunk in gateway.handle_envelope(env2):
            chunks2.append(chunk)

        assert any(c.get("type") == "ERROR" for c in chunks2)


# ===========================================================================
# #20 — Extended Integration Tests (missing scenarios)
# ===========================================================================
class TestExtendedIntegration:
    """Additional integration tests for scenarios not covered above."""

    @pytest.mark.asyncio
    async def test_cancel_during_streaming(self):
        """Cancel a task while it's streaming chunks."""
        from app.main import GatewayApp
        from app.core.config import ProviderEntry

        config = GatewayConfig(
            providers=[ProviderEntry(
                provider_type="mock", name="mock",
                endpoint="mock://localhost", model="mock-model",
                api_key="unused",
            )],
            security_enabled=False,
        )
        gateway = GatewayApp(config)

        # Invoke
        invoke_env = {
            "version": "v1",
            "type": "INVOKE",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {"model": "mock-model", "prompt": "test"},
        }
        chunks = []
        async for chunk in gateway.handle_envelope(invoke_env):
            chunks.append(chunk)
            # After receiving first chunk, cancel
            if chunk.get("type") == "STREAM_CHUNK" and len(chunks) == 1:
                cancel_env = {
                    "version": "v1",
                    "type": "CANCEL",
                    "session_id": "s1",
                    "corr_id": "c1",
                    "payload": {},
                }
                cancel_result = await gateway.handle_cancel(Envelope(**cancel_env))
                assert cancel_result.get("payload", {}).get("error_code") == "CANCELLED"

        # Verify session is in Cancelled state
        sm = gateway.session_store.get("s1")
        assert sm is not None
        assert sm.state == SessionState.CANCELLED

    @pytest.mark.asyncio
    async def test_already_cancelled_returns_error(self):
        """Canceling an already-cancelled task returns ALREADY_CANCELLED error."""
        from app.main import GatewayApp
        from app.core.config import ProviderEntry

        config = GatewayConfig(
            providers=[ProviderEntry(
                provider_type="mock", name="mock",
                endpoint="mock://localhost", model="mock-model",
                api_key="unused",
            )],
            security_enabled=False,
        )
        gateway = GatewayApp(config)

        # Create a session manually in INVOKED state so we can cancel it
        sm = gateway.session_store.get_or_create("s1", "c1")
        sm.on_event(EventType.INVOKE)

        # First cancel — session goes to CANCELLED
        cancel_env = Envelope(
            type=MessageType.CANCEL,
            session_id="s1",
            corr_id="c1",
            payload={},
        )
        result1 = await gateway.handle_cancel(cancel_env)
        assert result1.get("payload", {}).get("error_code") == CANCELLED.code

        # Second cancel — should return ALREADY_CANCELLED via idempotency
        result2 = await gateway.handle_cancel(cancel_env)
        assert result2.get("payload", {}).get("error_code") == ALREADY_CANCELLED.code

    @pytest.mark.asyncio
    async def test_security_auth_required(self):
        """Security enabled: missing API key and agent_id rejected."""
        from app.main import GatewayApp
        from app.core.config import ProviderEntry

        config = GatewayConfig(
            providers=[ProviderEntry(
                provider_type="mock", name="mock",
                endpoint="mock://localhost", model="mock-model",
                api_key="unused",
            )],
            security_enabled=True,
            require_agent_id=True,
        )
        gateway = GatewayApp(config)

        # Register an agent
        api_key = gateway.security.register_agent("test-agent", roles=["user"])

        invoke_env = {
            "version": "v1",
            "type": "INVOKE",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {"model": "mock-model", "prompt": "test"},
        }

        # No auth headers → should fail
        chunks_no_auth = []
        async for chunk in gateway.handle_envelope(invoke_env):
            chunks_no_auth.append(chunk)
        assert any(c.get("type") == "ERROR" for c in chunks_no_auth)
        assert any(c.get("payload", {}).get("error_code") == AUTH_FAILED.code for c in chunks_no_auth)

        # With valid auth → should succeed
        chunks_with_auth = []
        async for chunk in gateway.handle_envelope(
            invoke_env, agent_id="test-agent", api_key=api_key
        ):
            chunks_with_auth.append(chunk)
        assert any(c.get("type") == "STREAM_CHUNK" for c in chunks_with_auth)

    @pytest.mark.asyncio
    async def test_rate_limiting_rejects_excess(self):
        """Rate limiter blocks requests beyond configured limit."""
        from app.core.flow_control import RateLimiter

        limiter = RateLimiter(max_tokens=2, refill_rate=0.1)

        # First two should succeed
        assert limiter.acquire() is True
        assert limiter.acquire() is True

        # Third should be rate-limited
        assert limiter.acquire() is False

    @pytest.mark.asyncio
    async def test_empty_request_rejected_in_pipeline(self):
        """Policy filter rejects empty prompt in invoke."""
        from app.main import GatewayApp

        config = GatewayConfig(security_enabled=False)
        gateway = GatewayApp(config)

        env = {
            "version": "v1",
            "type": "INVOKE",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {"model": "test", "prompt": "", "messages": []},
        }
        chunks = []
        async for chunk in gateway.handle_envelope(env):
            chunks.append(chunk)
        assert any(c.get("type") == "ERROR" for c in chunks)
        assert any(c.get("payload", {}).get("error_code") == EMPTY_REQUEST.code for c in chunks)

    @pytest.mark.asyncio
    async def test_multi_provider_router_select(self):
        """Router selects provider based on strategy."""
        from app.adapters.router import ProviderRouter
        from app.adapters.provider import ProviderConfig, ProviderType

        mock1 = MockProviderAdapter(scenario=MockScenario.NORMAL, chunk_count=2)
        mock1.config.name = "primary"
        mock2 = MockProviderAdapter(scenario=MockScenario.NORMAL, chunk_count=3)
        mock2.config.name = "secondary"

        router = ProviderRouter(strategy="priority")
        router.add_route(name="primary", adapter=mock1, priority=10)
        router.add_route(name="secondary", adapter=mock2, priority=5)

        name, provider = router.select(session_id="s1", model="mock")
        assert name == "primary"

        # Failover
        result = router.failover("primary", session_id="s1")
        assert result is not None
        assert result[0] == "secondary"

    @pytest.mark.asyncio
    async def test_router_hash_select_stable(self):
        """Hash-based routing gives stable selection per session_id."""
        from app.adapters.router import ProviderRouter

        mock1 = MockProviderAdapter()
        mock2 = MockProviderAdapter()

        router = ProviderRouter(strategy="hash")
        router.add_route(name="p1", adapter=mock1)
        router.add_route(name="p2", adapter=mock2)

        name1, _ = router.select(session_id="s1")
        name2, _ = router.select(session_id="s1")
        assert name1 == name2  # Same session → same provider

    @pytest.mark.asyncio
    async def test_router_round_robin_select(self):
        """Round-robin rotates across providers."""
        from app.adapters.router import ProviderRouter

        mock1 = MockProviderAdapter()
        mock2 = MockProviderAdapter()

        router = ProviderRouter(strategy="round_robin")
        router.add_route(name="p1", adapter=mock1)
        router.add_route(name="p2", adapter=mock2)

        name1, _ = router.select(session_id="s1")
        name2, _ = router.select(session_id="s2")
        assert name1 != name2  # Should alternate

    @pytest.mark.asyncio
    async def test_audit_records_invoke_and_end(self):
        """Audit logger captures both INVOKE and STREAM_END events."""
        from app.main import GatewayApp
        from app.core.config import ProviderEntry

        config = GatewayConfig(
            providers=[ProviderEntry(
                provider_type="mock", name="mock",
                endpoint="mock://localhost", model="mock-model",
                api_key="unused",
            )],
            security_enabled=False,
            audit_enabled=True,
        )
        gateway = GatewayApp(config)

        env = {
            "version": "v1",
            "type": "INVOKE",
            "session_id": "s1",
            "corr_id": "c1",
            "payload": {"model": "mock-model", "prompt": "test"},
        }
        async for _ in gateway.handle_envelope(env):
            pass

        audit = gateway.session_store.audit
        assert audit is not None
        entries = audit.query_by_corr_id("c1")
        events = [e.event for e in entries]
        assert "INVOKE" in events
        assert "STREAM_END" in events


# Reimport for test reference
from app.core.tracing import SPAN_ATTRIBUTES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])