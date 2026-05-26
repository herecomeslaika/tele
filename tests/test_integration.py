# Integration tests: 3 core scenarios via MockProviderAdapter + full Gateway pipeline

import asyncio
import io
import json
import time

import pytest

from app.adapters.mock_provider import MockProviderAdapter, MockScenario
from app.core.errors import ErrorCode
from app.core.logger import StructuredLogger, get_logger
from app.core.seq_checker import SeqChecker
from app.core.state_machine import (
    CANCEL,
    ERROR,
    INVOKE,
    STREAM_CHUNK,
    STREAM_END,
    TIMEOUT,
    GatewayStateMachine,
)
from app.core.timeout import TimeoutChecker, TimeoutKind
from app.models.envelope import Envelope, MessageType
from app.models.state import SessionState


# ---------------------------------------------------------------------------
# Helper: run a full streaming pipeline through mock adapter + state machine + seq checker
# ---------------------------------------------------------------------------

async def _run_stream_pipeline(
    adapter: MockProviderAdapter,
    invoke_envelope: Envelope,
    timeout_checker: TimeoutChecker | None = None,
    cancel_after_chunks: int | None = None,
    stream_timeout: float | None = None,
) -> list[Envelope]:
    """
    Simulate the Gateway processing a stream:
      1. Feed INVOKE to state machine
      2. Pull envelopes from adapter.stream()
      3. Feed each to state machine + seq checker
      4. Optionally cancel after N chunks
      5. Optionally enforce a timeout on the stream coroutine

    Returns all envelopes produced (including errors from timeout/cancel).
    """
    sm = GatewayStateMachine(session_id=invoke_envelope.session_id)
    checker = SeqChecker()
    results: list[Envelope] = []

    # INVOKE -> state machine
    transition = sm.on_event(INVOKE)
    assert transition.accepted

    if timeout_checker:
        timeout_checker.register(invoke_envelope.session_id, invoke_envelope.corr_id)

    try:
        if stream_timeout is not None:
            envelopes = await asyncio.wait_for(
                _collect_envelopes(adapter, invoke_envelope, sm, checker, timeout_checker, cancel_after_chunks),
                timeout=stream_timeout,
            )
            results.extend(envelopes)
        else:
            envelopes = await _collect_envelopes(adapter, invoke_envelope, sm, checker, timeout_checker, cancel_after_chunks)
            results.extend(envelopes)
    except asyncio.TimeoutError:
        # Gateway timeout kicked in
        sm.on_event(TIMEOUT)
        results.append(
            Envelope(
                version=invoke_envelope.version,
                type=MessageType.ERROR,
                session_id=invoke_envelope.session_id,
                corr_id=invoke_envelope.corr_id,
                seq=0,
                payload={"code": "PROVIDER_TIMEOUT", "detail": "Gateway enforced timeout"},
            )
        )

    return results


async def _collect_envelopes(
    adapter: MockProviderAdapter,
    invoke_envelope: Envelope,
    sm: GatewayStateMachine,
    checker: SeqChecker,
    timeout_checker: TimeoutChecker | None,
    cancel_after_chunks: int | None,
) -> list[Envelope]:
    collected: list[Envelope] = []
    chunk_count = 0

    async for env in adapter.stream(invoke_envelope):
        chunk_count += 1

        # Optional cancel injection
        if cancel_after_chunks is not None and chunk_count >= cancel_after_chunks:
            sm.on_event(CANCEL)
            # After cancel, stop collecting — simulate downstream channel cutoff
            collected.append(env)
            return collected

        # Feed to state machine
        event_name = env.type
        transition = sm.on_event(event_name)

        if not transition.accepted:
            # State machine rejected — record as terminal rejection
            collected.append(env)
            return collected

        # Seq check for STREAM_CHUNK
        if env.type == MessageType.STREAM_CHUNK.value:
            seq_result = checker.check(env.corr_id, env.seq)
            if not seq_result.ok:
                collected.append(env)
                return collected

        if timeout_checker:
            if env.type == MessageType.STREAM_CHUNK.value:
                timeout_checker.on_chunk(env.session_id)

        collected.append(env)

    return collected


# ---------------------------------------------------------------------------
# Scenario 1: Normal call — full happy path
# ---------------------------------------------------------------------------

class TestNormalCallIntegration:
    @pytest.mark.asyncio
    async def test_normal_stream_complete(self):
        adapter = MockProviderAdapter(scenario=MockScenario.NORMAL)
        invoke_env = Envelope(
            version="A2A_min_v1",
            type=MessageType.INVOKE,
            session_id="s_normal_1",
            corr_id="c_normal_1",
            seq=0,
            payload={"prompt": "Hello"},
        )

        envelopes = await _run_stream_pipeline(adapter, invoke_env)

        # Should have: 3 STREAM_CHUNK + 1 STREAM_END
        chunks = [e for e in envelopes if e.type == MessageType.STREAM_CHUNK.value]
        ends = [e for e in envelopes if e.type == MessageType.STREAM_END.value]

        assert len(chunks) == 3
        assert len(ends) == 1
        assert all(e.type != MessageType.ERROR.value for e in envelopes)

    @pytest.mark.asyncio
    async def test_normal_seq_continuous(self):
        adapter = MockProviderAdapter(scenario=MockScenario.NORMAL)
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_normal_2", corr_id="c_normal_2",
            seq=0, payload={"prompt": "Test"},
        )

        envelopes = await _run_stream_pipeline(adapter, invoke_env)
        seqs = [e.seq for e in envelopes if e.type == MessageType.STREAM_CHUNK.value]
        # seqs should be monotonically increasing
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs))  # no duplicates

    @pytest.mark.asyncio
    async def test_normal_state_transitions(self):
        adapter = MockProviderAdapter(scenario=MockScenario.NORMAL)
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_normal_3", corr_id="c_normal_3",
            seq=0, payload={"prompt": "State"},
        )

        sm = GatewayStateMachine(session_id="s_normal_3")
        sm.on_event(INVOKE)
        assert sm.state == SessionState.INVOKED

        # First chunk -> Streaming
        async for env in adapter.stream(invoke_env):
            sm.on_event(env.type)
            if env.type == MessageType.STREAM_END.value:
                break
        assert sm.state == SessionState.DONE


# ---------------------------------------------------------------------------
# Scenario 2: Upstream timeout — Gateway enforced cutoff
# ---------------------------------------------------------------------------

class TestTimeoutIntegration:
    @pytest.mark.asyncio
    async def test_timeout_scenario_cutoff(self):
        adapter = MockProviderAdapter(scenario=MockScenario.TIMEOUT)
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_timeout_1", corr_id="c_timeout_1",
            seq=0, payload={"prompt": "Hang"},
        )

        # Enforce a 2-second timeout on the stream coroutine
        envelopes = await _run_stream_pipeline(
            adapter, invoke_env, stream_timeout=2.0,
        )

        # Should get a Gateway-enforced ERROR (no chunks)
        errors = [e for e in envelopes if e.type == MessageType.ERROR.value]
        assert len(errors) >= 1
        assert any(
            e.payload.get("code") == "PROVIDER_TIMEOUT"
            for e in errors
            if isinstance(e.payload, dict)
        )

    @pytest.mark.asyncio
    async def test_timeout_checker_first_token(self):
        adapter = MockProviderAdapter(scenario=MockScenario.TIMEOUT)
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_timeout_2", corr_id="c_timeout_2",
            seq=0, payload={"prompt": "Slow"},
        )

        tc = TimeoutChecker(first_token_timeout=0.5, provider_overall_timeout=100.0)
        tc.register("s_timeout_2", "c_timeout_2")

        # No chunk received — check timeouts after simulated wait
        time.sleep(0.6)
        results = tc.check_timeouts()
        assert len(results) == 1
        assert results[0][1] == TimeoutKind.FIRST_TOKEN

    @pytest.mark.asyncio
    async def test_timeout_checker_provider_overall(self):
        tc = TimeoutChecker(
            first_token_timeout=100.0,
            provider_overall_timeout=0.5,
        )
        tc.register("s_timeout_3", "c_timeout_3")

        time.sleep(0.6)
        results = tc.check_timeouts()
        assert len(results) == 1
        assert results[0][1] == TimeoutKind.PROVIDER_OVERALL


# ---------------------------------------------------------------------------
# Scenario 3: Upstream error — structured error propagation
# ---------------------------------------------------------------------------

class TestErrorIntegration:
    @pytest.mark.asyncio
    async def test_error_scenario_propagation(self):
        adapter = MockProviderAdapter(
            scenario=MockScenario.ERROR,
            error_after_chunk=1,
        )
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_error_1", corr_id="c_error_1",
            seq=0, payload={"prompt": "Crash"},
        )

        envelopes = await _run_stream_pipeline(adapter, invoke_env)

        # Should have: 1 STREAM_CHUNK + 1 ERROR
        chunks = [e for e in envelopes if e.type == MessageType.STREAM_CHUNK.value]
        errors = [e for e in envelopes if e.type == MessageType.ERROR.value]

        assert len(chunks) >= 1  # at least 1 chunk before crash
        assert len(errors) >= 1

        error_payload = errors[0].payload
        assert isinstance(error_payload, dict)
        assert error_payload["code"] == ErrorCode.PROVIDER_TIMEOUT.value

    @pytest.mark.asyncio
    async def test_error_state_transitions(self):
        adapter = MockProviderAdapter(scenario=MockScenario.ERROR, error_after_chunk=1)
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_error_2", corr_id="c_error_2",
            seq=0, payload={"prompt": "Fail"},
        )

        sm = GatewayStateMachine(session_id="s_error_2")
        sm.on_event(INVOKE)
        assert sm.state == SessionState.INVOKED

        async for env in adapter.stream(invoke_env):
            sm.on_event(env.type)
        assert sm.state == SessionState.FAILED

    @pytest.mark.asyncio
    async def test_error_then_terminal_reject(self):
        """After ERROR leads to Failed state, late STREAM_CHUNK must be rejected."""
        adapter = MockProviderAdapter(scenario=MockScenario.ERROR, error_after_chunk=1)
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_error_3", corr_id="c_error_3",
            seq=0, payload={"prompt": "Reject"},
        )

        sm = GatewayStateMachine(session_id="s_error_3")
        sm.on_event(INVOKE)

        async for env in adapter.stream(invoke_env):
            sm.on_event(env.type)

        assert sm.state == SessionState.FAILED

        # Late arrival
        late = sm.on_event(STREAM_CHUNK)
        assert not late.accepted
        assert sm.state == SessionState.FAILED  # unchanged


# ---------------------------------------------------------------------------
# Scenario bonus: Cancel cuts off downstream
# ---------------------------------------------------------------------------

class TestCancelIntegration:
    @pytest.mark.asyncio
    async def test_cancel_mid_stream(self):
        adapter = MockProviderAdapter(scenario=MockScenario.NORMAL)
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_cancel_1", corr_id="c_cancel_1",
            seq=0, payload={"prompt": "Stop"},
        )

        envelopes = await _run_stream_pipeline(
            adapter, invoke_env, cancel_after_chunks=1,
        )

        sm = GatewayStateMachine(session_id="s_cancel_1")
        sm.on_event(INVOKE)
        sm.on_event(CANCEL)
        assert sm.state == SessionState.CANCELLED

        # After cancel, no STREAM_END should arrive
        ends = [e for e in envelopes if e.type == MessageType.STREAM_END.value]
        assert len(ends) == 0


# ---------------------------------------------------------------------------
# Structured Logger validation
# ---------------------------------------------------------------------------

class TestStructuredLoggerIntegration:
    def test_json_output_all_mandatory_fields(self):
        buf = io.StringIO()
        logger = StructuredLogger("test", output=buf)

        logger.log(
            event="provider.invoke.complete",
            level="INFO",
            session_id="s_log_1",
            corr_id="c_log_1",
            state="Done",
            latency_ms=150.3,
        )

        line = buf.getvalue().strip()
        entry = json.loads(line)

        mandatory = ["timestamp", "level", "event", "session_id", "corr_id", "state", "error_code", "latency_ms"]
        for field in mandatory:
            assert field in entry, f"missing mandatory field: {field}"

        assert entry["event"] == "provider.invoke.complete"
        assert entry["session_id"] == "s_log_1"
        assert entry["latency_ms"] == 150.3

    def test_logger_with_error_code(self):
        buf = io.StringIO()
        logger = StructuredLogger("test", output=buf)

        logger.log(
            event="provider.invoke.timeout",
            level="ERROR",
            session_id="s_log_2",
            corr_id="c_log_2",
            error_code="PROVIDER_TIMEOUT",
            latency_ms=30000.0,
        )

        entry = json.loads(buf.getvalue().strip())
        assert entry["error_code"] == "PROVIDER_TIMEOUT"
        assert entry["level"] == "ERROR"

    def test_logger_extra_kwargs(self):
        buf = io.StringIO()
        logger = StructuredLogger("test", output=buf)

        logger.log(
            event="custom",
            session_id="s_log_3",
            custom_field="hello",
        )

        entry = json.loads(buf.getvalue().strip())
        assert entry["custom_field"] == "hello"

    @pytest.mark.asyncio
    async def test_logger_in_normal_pipeline(self):
        """Verify that logger output is captured during a normal streaming pipeline."""
        buf = io.StringIO()
        logger = StructuredLogger("mock_provider", output=buf)

        adapter = MockProviderAdapter(scenario=MockScenario.NORMAL)
        invoke_env = Envelope(
            version="A2A_min_v1", type=MessageType.INVOKE,
            session_id="s_log_pipe", corr_id="c_log_pipe",
            seq=0, payload={"prompt": "Log"},
        )

        # Override mock's logger to capture output
        from app.adapters.mock_provider import logger as mock_logger_ref
        # Patch temporarily
        import app.adapters.mock_provider as mock_mod
        original_logger = mock_mod.logger
        mock_mod.logger = logger

        envelopes = await _run_stream_pipeline(adapter, invoke_env)

        # Restore
        mock_mod.logger = original_logger

        lines = buf.getvalue().strip().split("\n")
        assert len(lines) >= 1  # at least some log entries

        for line in lines:
            entry = json.loads(line)
            assert "timestamp" in entry
            assert "event" in entry