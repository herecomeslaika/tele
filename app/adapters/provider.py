# A2A_min_v1 Provider Adapter Interface

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.models.envelope import Envelope


class ProviderAdapter(ABC):
    """
    Abstract interface that decouples the Gateway's protocol handling
    from the concrete LLM provider invocation logic.

    Two implementations are planned:
      - RealProviderAdapter: calls an actual external LLM API.
      - MockProviderAdapter: returns canned responses for testing.
    """

    @abstractmethod
    async def invoke(self, envelope: Envelope) -> Envelope:
        """Send a non-streaming invocation and return the response envelope."""
        ...

    @abstractmethod
    async def stream(self, envelope: Envelope) -> AsyncIterator[Envelope]:
        """Send a streaming invocation and yield response envelopes chunk by chunk."""
        ...

    @abstractmethod
    async def cancel(self, session_id: str) -> None:
        """Cancel an ongoing invocation for the given session."""
        ...
