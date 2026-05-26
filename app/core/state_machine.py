# A2A_min_v1 Gateway State Machine Engine

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.models.envelope import MessageType
from app.models.state import SessionState

logger = logging.getLogger(__name__)


@dataclass
class TransitionResult:
    accepted: bool
    old_state: SessionState
    new_state: SessionState
    reason: str = ""


# Event type names (derived from MessageType + synthetic events)
INVOKE = MessageType.INVOKE.value
STREAM_CHUNK = MessageType.STREAM_CHUNK.value
STREAM_END = MessageType.STREAM_END.value
ERROR = MessageType.ERROR.value
CANCEL = MessageType.CANCEL.value
HEARTBEAT = MessageType.HEARTBEAT.value
TIMEOUT = "TIMEOUT"  # synthetic event, not a message type

# Legal transitions: (from_state, event) -> to_state
_TRANSITIONS: dict[tuple[SessionState, str], SessionState] = {
    (SessionState.IDLE, INVOKE): SessionState.INVOKED,
    (SessionState.INVOKED, STREAM_CHUNK): SessionState.STREAMING,
    (SessionState.INVOKED, STREAM_END): SessionState.DONE,
    (SessionState.INVOKED, ERROR): SessionState.FAILED,
    (SessionState.INVOKED, CANCEL): SessionState.CANCELLED,
    (SessionState.INVOKED, TIMEOUT): SessionState.FAILED,
    (SessionState.STREAMING, STREAM_CHUNK): SessionState.STREAMING,
    (SessionState.STREAMING, STREAM_END): SessionState.DONE,
    (SessionState.STREAMING, ERROR): SessionState.FAILED,
    (SessionState.STREAMING, CANCEL): SessionState.CANCELLED,
    (SessionState.STREAMING, TIMEOUT): SessionState.FAILED,
}


@dataclass
class GatewayStateMachine:
    """
    Per-session state machine for the A2A_min_v1 Gateway.

    Drives state transitions based on incoming events.
    Terminal states (Done, Failed, Cancelled) reject all further events.
    """

    session_id: str
    state: SessionState = SessionState.IDLE

    def on_event(self, event: str) -> TransitionResult:
        """Process an event and return the transition result."""
        old = self.state

        # Terminal state guard — reject everything after terminal
        if old.is_terminal:
            reason = f"event '{event}' rejected: session in terminal state '{old.value}'"
            logger.warning(
                "terminal-state-reject",
                extra={"session_id": self.session_id, "event": event, "state": old.value},
            )
            return TransitionResult(accepted=False, old_state=old, new_state=old, reason=reason)

        # HEARTBEAT is only valid in non-idle, non-terminal states
        if event == HEARTBEAT:
            if old == SessionState.IDLE:
                return TransitionResult(
                    accepted=False,
                    old_state=old,
                    new_state=old,
                    reason="HEARTBEAT ignored in Idle state",
                )
            # Heartbeat doesn't change state, just confirms liveness
            return TransitionResult(accepted=True, old_state=old, new_state=old, reason="heartbeat acknowledged")

        # Look up the transition
        key = (old, event)
        new_state = _TRANSITIONS.get(key)

        if new_state is None:
            reason = f"illegal transition: event '{event}' not allowed in state '{old.value}'"
            logger.warning(
                "illegal-transition",
                extra={"session_id": self.session_id, "event": event, "state": old.value},
            )
            return TransitionResult(accepted=False, old_state=old, new_state=old, reason=reason)

        self.state = new_state
        logger.info(
            "state-transition",
            extra={
                "session_id": self.session_id,
                "event": event,
                "old_state": old.value,
                "new_state": new_state.value,
            },
        )
        return TransitionResult(accepted=True, old_state=old, new_state=new_state)
