# A2A_min_v1 Session State

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
