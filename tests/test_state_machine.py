# Tests for GatewayStateMachine

import pytest

from app.core.state_machine import (
    EventType,
    GatewayStateMachine,
)
from app.models.state import SessionState

INVOKE = EventType.INVOKE
STREAM_CHUNK = EventType.STREAM_CHUNK
STREAM_END = EventType.STREAM_END
CANCEL = EventType.CANCEL
HEARTBEAT = EventType.HEARTBEAT
ERROR = EventType.ERROR
TIMEOUT = EventType.TIMEOUT


class TestStateMachineHappyPath:
    def test_invoke_from_idle(self):
        sm = GatewayStateMachine(session_id="s1")
        result = sm.on_event(INVOKE)
        assert result.accepted
        assert result.new_state == SessionState.INVOKED

    def test_streaming_flow(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        result = sm.on_event(STREAM_CHUNK)
        assert result.accepted
        assert result.new_state == SessionState.STREAMING

    def test_streaming_to_done(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        sm.on_event(STREAM_CHUNK)
        result = sm.on_event(STREAM_END)
        assert result.accepted
        assert result.new_state == SessionState.DONE

    def test_invoke_direct_to_done(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        result = sm.on_event(STREAM_END)
        assert result.accepted
        assert result.new_state == SessionState.DONE

    def test_invoke_direct_to_failed(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        result = sm.on_event(ERROR)
        assert result.accepted
        assert result.new_state == SessionState.FAILED

    def test_multiple_chunks(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        assert sm.on_event(STREAM_CHUNK).accepted
        assert sm.on_event(STREAM_CHUNK).accepted
        assert sm.on_event(STREAM_CHUNK).accepted
        assert sm.state == SessionState.STREAMING


class TestStateMachineCancel:
    def test_cancel_from_invoked(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        result = sm.on_event(CANCEL)
        assert result.accepted
        assert result.new_state == SessionState.CANCELLED

    def test_cancel_from_streaming(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        sm.on_event(STREAM_CHUNK)
        result = sm.on_event(CANCEL)
        assert result.accepted
        assert result.new_state == SessionState.CANCELLED

    def test_cancel_blocks_downstream(self):
        """After CANCEL, no more STREAM_CHUNK should be accepted."""
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        sm.on_event(STREAM_CHUNK)
        sm.on_event(CANCEL)
        result = sm.on_event(STREAM_CHUNK)
        assert not result.accepted
        assert sm.state == SessionState.CANCELLED


class TestStateMachineTerminalGuard:
    """All three terminal states must reject further events."""

    @pytest.fixture(params=[SessionState.DONE, SessionState.FAILED, SessionState.CANCELLED])
    def terminal_sm(self, request):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        if request.param == SessionState.DONE:
            sm.on_event(STREAM_END)
        elif request.param == SessionState.FAILED:
            sm.on_event(ERROR)
        elif request.param == SessionState.CANCELLED:
            sm.on_event(CANCEL)
        assert sm.state.is_terminal
        return sm

    def test_terminal_rejects_chunk(self, terminal_sm):
        result = terminal_sm.on_event(STREAM_CHUNK)
        assert not result.accepted

    def test_terminal_rejects_invoke(self, terminal_sm):
        result = terminal_sm.on_event(INVOKE)
        assert not result.accepted

    def test_terminal_rejects_heartbeat(self, terminal_sm):
        result = terminal_sm.on_event(HEARTBEAT)
        assert not result.accepted

    def test_terminal_rejects_cancel(self, terminal_sm):
        result = terminal_sm.on_event(CANCEL)
        assert not result.accepted

    def test_state_unchanged_after_rejection(self, terminal_sm):
        original = terminal_sm.state
        terminal_sm.on_event(STREAM_CHUNK)
        assert terminal_sm.state == original


class TestStateMachineIllegalTransitions:
    def test_stream_from_idle(self):
        sm = GatewayStateMachine(session_id="s1")
        result = sm.on_event(STREAM_CHUNK)
        assert not result.accepted
        assert sm.state == SessionState.IDLE

    def test_cancel_from_idle(self):
        sm = GatewayStateMachine(session_id="s1")
        result = sm.on_event(CANCEL)
        assert not result.accepted

    def test_invoke_from_invoked(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        result = sm.on_event(INVOKE)
        assert not result.accepted


class TestStateMachineTimeout:
    def test_timeout_from_invoked(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        result = sm.on_event(TIMEOUT)
        assert result.accepted
        assert result.new_state == SessionState.FAILED

    def test_timeout_from_streaming(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        sm.on_event(STREAM_CHUNK)
        result = sm.on_event(TIMEOUT)
        assert result.accepted
        assert result.new_state == SessionState.FAILED

    def test_timeout_from_idle_rejected(self):
        sm = GatewayStateMachine(session_id="s1")
        result = sm.on_event(TIMEOUT)
        assert not result.accepted


class TestStateMachineHeartbeat:
    def test_heartbeat_in_invoked(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        result = sm.on_event(HEARTBEAT)
        assert result.accepted
        assert sm.state == SessionState.INVOKED  # no state change

    def test_heartbeat_in_streaming(self):
        sm = GatewayStateMachine(session_id="s1")
        sm.on_event(INVOKE)
        sm.on_event(STREAM_CHUNK)
        result = sm.on_event(HEARTBEAT)
        assert result.accepted
        assert sm.state == SessionState.STREAMING

    def test_heartbeat_in_idle_rejected(self):
        sm = GatewayStateMachine(session_id="s1")
        result = sm.on_event(HEARTBEAT)
        assert not result.accepted
