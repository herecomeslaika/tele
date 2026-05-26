"""A2A_min_v1 Anthropic-compatible Provider Adapter."""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Optional

from app.adapters.provider import ProviderAdapter, ProviderConfig, ProviderType, StreamEvent
from app.core.logger import setup_logger, log_event

logger = setup_logger("anthropic_provider")

try:
    import anthropic
    from anthropic import AsyncAnthropic, APIError, APITimeoutError
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


class AnthropicProviderAdapter(ProviderAdapter):
    """Calls an LLM via Anthropic-compatible API.

    Anthropic-compatible protocol specifics (differences from OpenAI):
      - Request: POST /messages with {model, messages, max_tokens, stream}
        - messages format: [{role: "user"|"assistant", content: str}] (same)
        - system prompt is a top-level field, not in messages
        - max_tokens is REQUIRED (not optional like OpenAI)
      - Stream response: SSE events with type="content_block_delta" containing
        delta.text, ending with type="message_stop"
        - Different event types: message_start, content_block_start,
          content_block_delta, content_block_stop, message_stop
      - Error: HTTP status + JSON with error.type + error.message
        - Error types: invalid_request_error, authentication_error,
          rate_limit_error, api_error, overloaded_error
      - Stop condition: stop_reason in ("end_turn", "max_tokens", "stop_sequence")
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not HAS_ANTHROPIC:
            raise ImportError(
                "anthropic package not installed. Install with: pip install anthropic"
            )
        self._client = AsyncAnthropic(
            base_url=config.base_url if config.base_url != "default" else None,
            api_key=config.api_key,
            timeout=config.timeout,
        )

    async def invoke(self, prompt: str, **kwargs: Any) -> AsyncIterator[StreamEvent]:
        """Streaming invoke via Anthropic-compatible API."""
        start = time.time()
        model = kwargs.get("model", self.config.model)
        messages = kwargs.get("messages", [{"role": "user", "content": prompt}])
        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

        try:
            async with self._client.messages.stream(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=kwargs.get("temperature", self.config.temperature),
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "text") and event.delta.text:
                            latency_ms = (time.time() - start) * 1000
                            log_event(logger, "provider.stream.chunk",
                                      latency_ms=round(latency_ms, 1))
                            yield StreamEvent(
                                type="chunk",
                                content=event.delta.text,
                                token_count=1,
                            )

                    elif event.type == "message_stop":
                        latency_ms = (time.time() - start) * 1000
                        log_event(logger, "provider.stream.end",
                                  latency_ms=round(latency_ms, 1))
                        yield StreamEvent(type="end", finish_reason="end_turn")
                        return

        except Exception as e:
            error_type = type(e).__name__
            latency_ms = (time.time() - start) * 1000

            if "timeout" in error_type.lower():
                log_event(logger, "provider.timeout", error_code="PROVIDER_RESPONSE_TIMEOUT",
                          latency_ms=round(latency_ms, 1))
                yield StreamEvent(type="error", error_code="PROVIDER_RESPONSE_TIMEOUT",
                                  error_msg=str(e))
            else:
                log_event(logger, "provider.error", error_code="PROVIDER_ERROR",
                          latency_ms=round(latency_ms, 1))
                yield StreamEvent(type="error", error_code="PROVIDER_ERROR",
                                  error_msg=str(e))

    async def invoke_sync(self, prompt: str, **kwargs: Any) -> str:
        """Non-streaming invoke via Anthropic API."""
        start = time.time()
        model = kwargs.get("model", self.config.model)
        messages = kwargs.get("messages", [{"role": "user", "content": prompt}])
        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

        try:
            resp = await self._client.messages.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=kwargs.get("temperature", self.config.temperature),
            )
            content = resp.content[0].text if resp.content else ""
            latency_ms = (time.time() - start) * 1000
            log_event(logger, "provider.invoke.complete", latency_ms=round(latency_ms, 1))
            return content

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            log_event(logger, "provider.error", error_code="PROVIDER_ERROR",
                      latency_ms=round(latency_ms, 1))
            raise