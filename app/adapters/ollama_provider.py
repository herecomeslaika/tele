"""A2A_min_v1 Ollama Provider Adapter (OpenAI-compatible subset)."""

from __future__ import annotations

from app.adapters.openai_provider import OpenAIProviderAdapter
from app.adapters.provider import ProviderConfig, ProviderType


class OllamaProviderAdapter(OpenAIProviderAdapter):
    """Ollama uses the OpenAI-compatible API at /v1 endpoint.

    Differences from generic OpenAI-compatible:
      - No API key required (api_key is "unused")
      - Base URL is typically http://localhost:11434/v1
      - Models are local names (e.g. qwen2.5:0.5b, llama3.2)
      - No rate limits from server side
    """

    def __init__(self, config: ProviderConfig) -> None:
        # Ollama doesn't need API keys
        config.api_key = config.api_key or "unused"
        super().__init__(config)