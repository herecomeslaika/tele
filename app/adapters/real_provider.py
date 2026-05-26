# A2A_min_v1 Real Provider Adapter — OpenAI-compatible API

from __future__ import annotations

import os
import time
from typing import AsyncIterator

from openai import AsyncOpenAI, APIError, APITimeoutError

from app.adapters.provider import ProviderAdapter
from app.core.errors import ErrorCode, make_error_envelope
from app.core.logger import get_logger
from app.models.envelope import Envelope, MessageType

logger = get_logger("real_provider")


class RealProviderAdapter(ProviderAdapter):
    """
    Calls a real LLM via OpenAI-compatible API (e.g. DeepSeek).
    Converts streaming responses into A2A_min_v1 envelopes.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self.endpoint = endpoint or os.getenv("PROVIDER_ENDPOINT", "https://api.deepseek.com/v1")
        self.api_key = api_key or os.getenv("PROVIDER_API_KEY", "")
        self.model = model or os.getenv("PROVIDER_MODEL", "deepseek-chat")
        self.request_timeout = request_timeout

        self._client = AsyncOpenAI(
            base_url=self.endpoint,
            api_key=self.api_key,
            timeout=request_timeout,
        )

    async def invoke(self, envelope: Envelope) -> Envelope:
        """Non-streaming call — returns a single STREAM_END envelope."""
        start = time.time()
        prompt = envelope.payload.get("prompt", "") if isinstance(envelope.payload, dict) else str(envelope.payload)

        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
            content = resp.choices[0].message.content or ""
            latency_ms = (time.time() - start) * 1000

            logger.log(
                event="provider.invoke.complete",
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                latency_ms=round(latency_ms, 1),
            )

            return Envelope(
                version=envelope.version,
                type=MessageType.STREAM_END,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                seq=envelope.seq + 1,
                payload={"content": content, "model": self.model},
            )

        except APITimeoutError:
            latency_ms = (time.time() - start) * 1000
            logger.log(
                event="provider.invoke.timeout",
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                error_code=ErrorCode.PROVIDER_TIMEOUT.value,
                latency_ms=round(latency_ms, 1),
            )
            return make_error_envelope(
                code=ErrorCode.PROVIDER_TIMEOUT,
                detail=f"Provider timed out after {latency_ms:.0f}ms",
                version=envelope.version,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
            )

        except APIError as e:
            latency_ms = (time.time() - start) * 1000
            logger.log(
                event="provider.invoke.error",
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                error_code=ErrorCode.PROVIDER_TIMEOUT.value,
                latency_ms=round(latency_ms, 1),
            )
            return make_error_envelope(
                code=ErrorCode.PROVIDER_TIMEOUT,
                detail=f"Provider API error: {e}",
                version=envelope.version,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
            )

    async def stream(self, envelope: Envelope) -> AsyncIterator[Envelope]:
        """Streaming call — yields STREAM_CHUNK envelopes, ends with STREAM_END."""
        start = time.time()
        prompt = envelope.payload.get("prompt", "") if isinstance(envelope.payload, dict) else str(envelope.payload)
        seq = envelope.seq

        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    seq += 1
                    latency_ms = (time.time() - start) * 1000

                    logger.log(
                        event="provider.stream.chunk",
                        session_id=envelope.session_id,
                        corr_id=envelope.corr_id,
                        latency_ms=round(latency_ms, 1),
                    )

                    yield Envelope(
                        version=envelope.version,
                        type=MessageType.STREAM_CHUNK,
                        session_id=envelope.session_id,
                        corr_id=envelope.corr_id,
                        seq=seq,
                        payload={"token": delta.content},
                    )

            # Stream complete
            seq += 1
            latency_ms = (time.time() - start) * 1000
            logger.log(
                event="provider.stream.end",
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                latency_ms=round(latency_ms, 1),
            )

            yield Envelope(
                version=envelope.version,
                type=MessageType.STREAM_END,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                seq=seq,
                payload={"model": self.model},
            )

        except APITimeoutError:
            latency_ms = (time.time() - start) * 1000
            logger.log(
                event="provider.stream.timeout",
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                error_code=ErrorCode.PROVIDER_TIMEOUT.value,
                latency_ms=round(latency_ms, 1),
            )
            yield make_error_envelope(
                code=ErrorCode.PROVIDER_TIMEOUT,
                detail=f"Provider stream timed out after {latency_ms:.0f}ms",
                version=envelope.version,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
            )

        except APIError as e:
            latency_ms = (time.time() - start) * 1000
            logger.log(
                event="provider.stream.error",
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                error_code=ErrorCode.PROVIDER_TIMEOUT.value,
                latency_ms=round(latency_ms, 1),
            )
            yield make_error_envelope(
                code=ErrorCode.PROVIDER_TIMEOUT,
                detail=f"Provider stream error: {e}",
                version=envelope.version,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
            )

    async def cancel(self, session_id: str) -> None:
        logger.log(event="provider.cancel", session_id=session_id)
