"""A2A_min_v1 OpenAI-compatible Provider Adapter."""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Optional

from openai import AsyncOpenAI, APIError, APITimeoutError

from app.adapters.provider import ProviderAdapter, ProviderConfig, ProviderType, StreamEvent
from app.core.logger import setup_logger, log_event

logger = setup_logger("openai_provider")


class OpenAIProviderAdapter(ProviderAdapter):
    """Calls an LLM via OpenAI-compatible API (DeepSeek, Ollama, LMStudio, etc.).

    OpenAI-compatible protocol specifics:
      - Request: POST /chat/completions with {model, messages, stream}
      - Stream response: SSE chunks with delta.content until finish_reason="stop"
      - Error: HTTP status code + JSON body with error.message
      - Stop condition: finish_reason in ("stop", "length", "content_filter")
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "unused",
            timeout=config.timeout,
        )

    async def invoke(self, prompt: str, **kwargs: Any) -> AsyncIterator[StreamEvent]:
        """Streaming invoke via OpenAI-compatible API."""
        start = time.time()
        model = kwargs.get("model", self.config.model)
        messages = kwargs.get("messages", [{"role": "user", "content": prompt}])

        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                temperature=kwargs.get("temperature", self.config.temperature),
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                if delta.content:
                    latency_ms = (time.time() - start) * 1000
                    log_event(logger, "provider.stream.chunk", latency_ms=round(latency_ms, 1))
                    yield StreamEvent(
                        type="chunk",
                        content=delta.content,
                        token_count=1,
                    )

                if finish_reason:
                    latency_ms = (time.time() - start) * 1000
                    log_event(logger, "provider.stream.end", latency_ms=round(latency_ms, 1))
                    yield StreamEvent(
                        type="end",
                        finish_reason=finish_reason,
                    )
                    return

        except APITimeoutError:
            latency_ms = (time.time() - start) * 1000
            log_event(logger, "provider.timeout", error_code="PROVIDER_RESPONSE_TIMEOUT",
                      latency_ms=round(latency_ms, 1))
            yield StreamEvent(type="error", error_code="PROVIDER_RESPONSE_TIMEOUT",
                              error_msg=f"Provider timed out after {latency_ms:.0f}ms")

        except APIError as e:
            latency_ms = (time.time() - start) * 1000
            log_event(logger, "provider.error", error_code="PROVIDER_ERROR",
                      latency_ms=round(latency_ms, 1))
            yield StreamEvent(type="error", error_code="PROVIDER_ERROR",
                              error_msg=str(e))

    async def invoke_sync(self, prompt: str, **kwargs: Any) -> str:
        """Non-streaming invoke."""
        start = time.time()
        model = kwargs.get("model", self.config.model)
        messages = kwargs.get("messages", [{"role": "user", "content": prompt}])

        try:
            resp = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                temperature=kwargs.get("temperature", self.config.temperature),
            )
            content = resp.choices[0].message.content or ""
            latency_ms = (time.time() - start) * 1000
            log_event(logger, "provider.invoke.complete", latency_ms=round(latency_ms, 1))
            return content

        except APITimeoutError:
            latency_ms = (time.time() - start) * 1000
            log_event(logger, "provider.timeout", error_code="PROVIDER_RESPONSE_TIMEOUT",
                      latency_ms=round(latency_ms, 1))
            raise

        except APIError as e:
            latency_ms = (time.time() - start) * 1000
            log_event(logger, "provider.error", error_code="PROVIDER_ERROR",
                      latency_ms=round(latency_ms, 1))
            raise