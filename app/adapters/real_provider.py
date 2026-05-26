"""A2A_min_v1 Real Provider Adapter — backward-compatible wrapper."""

from __future__ import annotations

import os
from typing import Optional

from app.adapters.openai_provider import OpenAIProviderAdapter
from app.adapters.provider import ProviderConfig, ProviderType


class RealProviderAdapter(OpenAIProviderAdapter):
    """Backward-compatible real provider adapter.

    Defaults to DeepSeek OpenAI-compatible API.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        request_timeout: float = 30.0,
    ) -> None:
        config = ProviderConfig(
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            name="real_provider",
            base_url=endpoint or os.getenv("PROVIDER_ENDPOINT", "https://api.deepseek.com/v1"),
            model=model or os.getenv("PROVIDER_MODEL", "deepseek-chat"),
            api_key=api_key or os.getenv("PROVIDER_API_KEY", ""),
            timeout=request_timeout,
        )
        super().__init__(config)