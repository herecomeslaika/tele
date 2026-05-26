"""A2A_min_v1 Mock Provider Adapter — scenario-injectable test double."""

from __future__ import annotations

import asyncio
import json
import time
from enum import Enum
from typing import Any, AsyncIterator, Optional

from app.adapters.provider import ProviderAdapter, ProviderConfig, ProviderType, StreamEvent
from app.core.logger import setup_logger, log_event

logger = setup_logger("mock_provider")


class MockScenario(str, Enum):
    NORMAL = "normal"
    DELAY = "delay"
    ERROR = "error"
    TIMEOUT = "timeout"
    MID_STREAM_ERROR = "mid_stream_error"
    BAD_JSON = "bad_json"
    DUPLICATE_TOKEN = "duplicate_token"
    OUT_OF_ORDER = "out_of_order"
    PARTIAL_DISCONNECT = "partial_disconnect"
    LONG_RESPONSE = "long_response"


class MockProviderAdapter(ProviderAdapter):
    """Highly controllable mock provider for integration testing.

    Scenarios:
      - normal:  yields N chunks then end
      - delay:   inserts artificial delay between chunks
      - error:   immediate error on invoke
      - timeout: never yields (hangs indefinitely)
      - mid_stream_error: yields K chunks then error
      - bad_json: yields malformed JSON content
      - duplicate_token: yields the same token twice
      - out_of_order: yields seq numbers out of order
      - partial_disconnect: yields some chunks then stops (no end event)
      - long_response: yields a very long response
    """

    def __init__(
        self,
        scenario: MockScenario = MockScenario.NORMAL,
        chunk_count: int = 3,
        chunk_delay: float = 0.1,
        error_after_chunk: int = 1,
        chunk_content: Optional[list[str]] = None,
    ) -> None:
        config = ProviderConfig(
            provider_type=ProviderType.MOCK,
            name=f"mock_{scenario.value}",
            base_url="mock://localhost",
            model="mock-model",
        )
        super().__init__(config)
        self.scenario = scenario
        self.chunk_count = chunk_count
        self.chunk_delay = chunk_delay
        self.error_after_chunk = error_after_chunk
        self.chunk_content = chunk_content or ["Hello", " world", "!"]

    async def invoke(self, prompt: str, **kwargs: Any) -> AsyncIterator[StreamEvent]:
        start = time.time()

        if self.scenario == MockScenario.ERROR:
            yield StreamEvent(type="error", error_code="PROVIDER_ERROR",
                              error_msg="Mock provider simulated immediate error")
            return

        if self.scenario == MockScenario.TIMEOUT:
            log_event(logger, "mock_provider.timeout_start")
            await asyncio.sleep(9999)
            return

        if self.scenario == MockScenario.BAD_JSON:
            yield StreamEvent(type="chunk", content="{'malformed': json,}")
            yield StreamEvent(type="chunk", content="<not valid>")
            yield StreamEvent(type="end", finish_reason="stop")
            return

        if self.scenario == MockScenario.PARTIAL_DISCONNECT:
            for i in range(min(2, self.chunk_count)):
                await asyncio.sleep(self.chunk_delay)
                yield StreamEvent(type="chunk", content=self.chunk_content[i % len(self.chunk_content)])
            # Just stop — no end event, no error event
            return

        if self.scenario == MockScenario.DUPLICATE_TOKEN:
            for i in range(self.chunk_count):
                await asyncio.sleep(self.chunk_delay)
                content = self.chunk_content[i % len(self.chunk_content)]
                yield StreamEvent(type="chunk", content=content)
                # Yield the same content again (duplicate token)
                yield StreamEvent(type="chunk", content=content)
            yield StreamEvent(type="end", finish_reason="stop")
            return

        if self.scenario == MockScenario.OUT_OF_ORDER:
            # Yield tokens in reverse order
            for i in range(self.chunk_count - 1, -1, -1):
                await asyncio.sleep(self.chunk_delay)
                yield StreamEvent(type="chunk", content=self.chunk_content[i % len(self.chunk_content)])
            yield StreamEvent(type="end", finish_reason="stop")
            return

        if self.scenario == MockScenario.LONG_RESPONSE:
            for i in range(50):
                await asyncio.sleep(0.02)
                yield StreamEvent(type="chunk", content=f"word_{i} ")
            yield StreamEvent(type="end", finish_reason="stop")
            return

        # Normal / Delay / Mid-stream error
        for i in range(self.chunk_count):
            # Delay scenario: pause between chunks
            if self.scenario == MockScenario.DELAY and i > 0:
                await asyncio.sleep(self.chunk_delay)

            # Mid-stream error: emit N chunks then error
            if self.scenario == MockScenario.MID_STREAM_ERROR and i >= self.error_after_chunk:
                log_event(logger, "mock_provider.error_injected",
                          error_code="PROVIDER_ERROR")
                yield StreamEvent(type="error", error_code="PROVIDER_ERROR",
                                  error_msg="Mock provider simulated upstream crash")
                return

            content = self.chunk_content[i % len(self.chunk_content)]
            latency_ms = (time.time() - start) * 1000
            log_event(logger, "mock_provider.chunk", latency_ms=round(latency_ms, 1))
            yield StreamEvent(type="chunk", content=content)

        # End
        latency_ms = (time.time() - start) * 1000
        log_event(logger, "mock_provider.stream_end", latency_ms=round(latency_ms, 1))
        yield StreamEvent(type="end", finish_reason="stop")

    async def invoke_sync(self, prompt: str, **kwargs: Any) -> str:
        if self.scenario == MockScenario.ERROR:
            raise Exception("Mock provider error")
        if self.scenario == MockScenario.TIMEOUT:
            await asyncio.sleep(9999)
        return " ".join(self.chunk_content[:self.chunk_count])

    async def cancel(self, session_id: str) -> None:
        log_event(logger, "mock_provider.cancel")