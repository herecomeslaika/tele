"""A2A_min_v1 session states and terminal guard."""

from enum import Enum


class SessionState(str, Enum):
    IDLE = "Idle"
    INVOKED = "Invoked"
    STREAMING = "Streaming"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (SessionState.DONE, SessionState.FAILED, SessionState.CANCELLED)

    @property
    def is_active(self) -> bool:
        return self in (SessionState.INVOKED, SessionState.STREAMING)