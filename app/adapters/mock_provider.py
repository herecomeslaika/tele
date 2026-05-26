# A2A_min_v1 Mock Provider Adapter — scenario-injectable test double

from __future__ import annotations

import asyncio
from enum import Enum
from typing import AsyncIterator

from app.adapters.provider import ProviderAdapter
from app.core.errors import ErrorCode, make_error_envelope
from app.core.logger import get_logger
from app.models.envelope import Envelope, MessageType

logger = get_logger("mock_provider")


class MockScenario(str, Enum):
    NORMAL = "normal"
    DELAY = "delay"
    ERROR = "error"
    TIMEOUT = "timeout"


class MockProviderAdapter(ProviderAdapter):
    """
    Highly controllable mock provider for integration testing.

    Accepts a `scenario` parameter to simulate:
      - normal:  yields 3 STREAM_CHUNKs then STREAM_END
      - delay:   inserts artificial delay between chunks
      - error:   yields one chunk then emits a structured ERROR
      - timeout: never yields any chunk (hangs indefinitely)
    """

    def __init__(
        self,
        scenario: MockScenario = MockScenario.NORMAL,
        chunk_count: int = 3,
        chunk_delay: float = 0.1,
        error_after_chunk: int = 1,
    ) -> None:
        self.scenario = scenario
        self.chunk_count = chunk_count
        self.chunk_delay = chunk_delay
        self.error_after_chunk = error_after_chunk

    async def invoke(self, envelope: Envelope) -> Envelope:
        if self.scenario == MockScenario.ERROR:
            return make_error_envelope(
                code=ErrorCode.PROVIDER_TIMEOUT,
                detail="Mock provider simulated error",
                version=envelope.version,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
            )

        if self.scenario == MockScenario.TIMEOUT:
            await asyncio.sleep(9999)
            # unreachable, but for type checker
            return make_error_envelope(
                code=ErrorCode.PROVIDER_TIMEOUT,
                detail="Mock provider simulated timeout",
                version=envelope.version,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
            )

        if self.scenario == MockScenario.DELAY:
            await asyncio.sleep(self.chunk_delay)

        return Envelope(
            version=envelope.version,
            type=MessageType.STREAM_END,
            session_id=envelope.session_id,
            corr_id=envelope.corr_id,
            seq=envelope.seq + 1,
            payload={"mock": True, "echo": envelope.payload},
        )

    async def stream(self, envelope: Envelope) -> AsyncIterator[Envelope]:
        seq = envelope.seq

        if self.scenario == MockScenario.TIMEOUT:
            logger.log(
                event="mock_provider.timeout_start",
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
            )
            # Hang forever — the Gateway's TimeoutChecker should catch this
            await asyncio.sleep(9999)
            return  # unreachable

        for i in range(1, self.chunk_count + 1):
            # Error scenario: emit N chunks then ERROR
            if self.scenario == MockScenario.ERROR and i > self.error_after_chunk:
                logger.log(
                    event="mock_provider.error_injected",
                    session_id=envelope.session_id,
                    corr_id=envelope.corr_id,
                    error_code=ErrorCode.PROVIDER_TIMEOUT.value,
                )
                yield make_error_envelope(
                    code=ErrorCode.PROVIDER_TIMEOUT,
                    detail="Mock provider simulated upstream crash",
                    version=envelope.version,
                    session_id=envelope.session_id,
                    corr_id=envelope.corr_id,
                    seq=seq + 1,
                )
                return

            # Delay scenario: pause between chunks
            if self.scenario == MockScenario.DELAY and i > 1:
                await asyncio.sleep(self.chunk_delay)

            seq += 1
            logger.log(
                event="mock_provider.chunk",
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
            )
            yield Envelope(
                version=envelope.version,
                type=MessageType.STREAM_CHUNK,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                seq=seq,
                payload={"mock": True, "chunk": i, "token": f"token_{i}"},
            )

        # Normal / Delay: end with STREAM_END
        seq += 1
        logger.log(
            event="mock_provider.stream_end",
            session_id=envelope.session_id,
            corr_id=envelope.corr_id,
        )
        yield Envelope(
            version=envelope.version,
            type=MessageType.STREAM_END,
            session_id=envelope.session_id,
            corr_id=envelope.corr_id,
            seq=seq,
            payload={"mock": True, "reason": "complete"},
        )

    async def cancel(self, session_id: str) -> None:
        logger.log(event="mock_provider.cancel", session_id=session_id)
