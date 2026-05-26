"""A2A_min_v1 Provider Adapter — unified interface for LLM providers."""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional

from app.models.envelope import Envelope, MessageType, make_envelope, make_error_envelope
from app.models.envelope import StreamChunkPayload, StreamEndPayload, ErrorPayload


class ProviderType(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC_COMPATIBLE = "anthropic_compatible"
    OLLAMA = "ollama"
    MOCK = "mock"


@dataclass
class ProviderConfig:
    provider_type: ProviderType
    name: str
    base_url: str
    model: str
    api_key: Optional[str] = None
    max_tokens: int = 2048
    temperature: float = 0.7
    timeout: float = 60.0
    stream: bool = True
    extra: dict = field(default_factory=dict)


@dataclass
class StreamEvent:
    """A single event from a streaming LLM response."""
    type: str  # "chunk" | "end" | "error"
    content: Optional[str] = None
    finish_reason: Optional[str] = None
    error_code: Optional[str] = None
    error_msg: Optional[str] = None
    token_count: int = 0


class ProviderAdapter(abc.ABC):
    """Abstract base class for LLM provider adapters."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def provider_type(self) -> ProviderType:
        return self.config.provider_type

    @abc.abstractmethod
    async def invoke(self, prompt: str, **kwargs: Any) -> AsyncIterator[StreamEvent]:
        """Stream invoke the LLM. Yields StreamEvent objects."""
        ...

    @abc.abstractmethod
    async def invoke_sync(self, prompt: str, **kwargs: Any) -> str:
        """Non-streaming invoke. Returns the full response text."""
        ...

    async def close(self) -> None:
        """Clean up resources."""
        pass
