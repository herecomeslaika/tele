"""A2A_min_v1 Gateway state machine engine with full transition table."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.models.state import SessionState

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    INVOKE = "INVOKE"
    STREAM_CHUNK = "STREAM_CHUNK"
    STREAM_END = "STREAM_END"
    CANCEL = "CANCEL"
    HEARTBEAT = "HEARTBEAT"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


@dataclass
class TransitionResult:
    accepted: bool
    old_state: SessionState
    new_state: SessionState
    event: str = ""
    reason: str = ""


# Legal transitions: (from_state, event) -> to_state
_TRANSITIONS: dict[tuple[SessionState, EventType], SessionState] = {
    # Idle
    (SessionState.IDLE, EventType.INVOKE): SessionState.INVOKED,
    # Invoked
    (SessionState.INVOKED, EventType.STREAM_CHUNK): SessionState.STREAMING,
    (SessionState.INVOKED, EventType.STREAM_END): SessionState.DONE,
    (SessionState.INVOKED, EventType.ERROR): SessionState.FAILED,
    (SessionState.INVOKED, EventType.CANCEL): SessionState.CANCELLED,
    (SessionState.INVOKED, EventType.TIMEOUT): SessionState.FAILED,
    # Streaming
    (SessionState.STREAMING, EventType.STREAM_CHUNK): SessionState.STREAMING,
    (SessionState.STREAMING, EventType.STREAM_END): SessionState.DONE,
    (SessionState.STREAMING, EventType.ERROR): SessionState.FAILED,
    (SessionState.STREAMING, EventType.CANCEL): SessionState.CANCELLED,
    (SessionState.STREAMING, EventType.TIMEOUT): SessionState.FAILED,
}


@dataclass
class GatewayStateMachine:
    """Per-session state machine for the A2A_min_v1 Gateway.

    Terminal states (Done, Failed, Cancelled) reject all further events.
    HEARTBEAT is a no-op in non-idle, non-terminal states.
    """

    session_id: str
    state: SessionState = SessionState.IDLE
    terminal_reason: Optional[str] = None

    def on_event(self, event: EventType | str) -> TransitionResult:
        """Process an event and return the transition result."""
        if isinstance(event, str):
            try:
                event = EventType(event)
            except ValueError:
                return TransitionResult(
                    accepted=False,
                    old_state=self.state,
                    new_state=self.state,
                    event=event,
                    reason=f"unknown event type: {event}",
                )

        old = self.state

        # Terminal state guard — reject everything after terminal
        if old.is_terminal:
            reason = f"event '{event.value}' rejected: session in terminal state '{old.value}'"
            logger.warning(
                "terminal-state-reject",
                extra={"session_id": self.session_id, "event": event.value, "state": old.value},
            )
            return TransitionResult(
                accepted=False, old_state=old, new_state=old, event=event.value, reason=reason
            )

        # HEARTBEAT is only valid in non-idle, non-terminal states
        if event == EventType.HEARTBEAT:
            if old == SessionState.IDLE:
                return TransitionResult(
                    accepted=False,
                    old_state=old,
                    new_state=old,
                    event=event.value,
                    reason="HEARTBEAT ignored in Idle state",
                )
            return TransitionResult(
                accepted=True,
                old_state=old,
                new_state=old,
                event=event.value,
                reason="heartbeat acknowledged",
            )

        # Look up the transition
        key = (old, event)
        new_state = _TRANSITIONS.get(key)

        if new_state is None:
            reason = f"illegal transition: event '{event.value}' not allowed in state '{old.value}'"
            logger.warning(
                "illegal-transition",
                extra={"session_id": self.session_id, "event": event.value, "state": old.value},
            )
            return TransitionResult(
                accepted=False, old_state=old, new_state=old, event=event.value, reason=reason
            )

        self.state = new_state
        if new_state.is_terminal:
            self.terminal_reason = f"reached {new_state.value} via {event.value}"

        logger.info(
            "state-transition",
            extra={
                "session_id": self.session_id,
                "event": event.value,
                "old_state": old.value,
                "new_state": new_state.value,
            },
        )
        return TransitionResult(
            accepted=True, old_state=old, new_state=new_state, event=event.value
        )
