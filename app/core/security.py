"""A2A_min_v1 Security — API key validation, agent identity, permission checks."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentIdentity:
    agent_id: str
    roles: list[str] = field(default_factory=lambda: ["user"])


@dataclass
class SecurityConfig:
    enabled: bool = True
    api_keys: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)
    require_agent_id: bool = True
    max_input_length: int = 10000
    max_output_length: int = 50000
    sensitive_fields: list[str] = field(default_factory=lambda: ["api_key", "password", "token", "secret"])


@dataclass
class SecurityManager:
    """Gateway security boundary.

    Features:
      - API key validation
      - Agent identity requirement
      - Origin restriction
      - Input/output length limits
      - Sensitive field masking
    """

    config: SecurityConfig = field(default_factory=SecurityConfig)
    _registered_agents: dict[str, AgentIdentity] = field(default_factory=dict)

    def validate_api_key(self, api_key: Optional[str]) -> bool:
        if not self.config.enabled:
            return True
        if not api_key:
            return False
        return api_key in self.config.api_keys

    def validate_origin(self, origin: Optional[str]) -> bool:
        if not self.config.enabled:
            return True
        if not self.config.allowed_origins:
            return True
        return origin in self.config.allowed_origins if origin else False

    def validate_agent_id(self, agent_id: Optional[str]) -> bool:
        if not self.config.enabled:
            return True
        if not self.config.require_agent_id:
            return True
        return agent_id is not None and agent_id in self._registered_agents

    def register_agent(self, agent_id: str, roles: Optional[list[str]] = None) -> str:
        """Register an agent and return its API key."""
        key = secrets.token_urlsafe(32)
        self._registered_agents[agent_id] = AgentIdentity(
            agent_id=agent_id, roles=roles or ["user"]
        )
        self.config.api_keys.append(key)
        return key

    def check_input_length(self, text: str) -> tuple[bool, int]:
        length = len(text)
        return (length <= self.config.max_input_length, length)

    def check_output_length(self, text: str) -> tuple[bool, int]:
        length = len(text)
        return (length <= self.config.max_output_length, length)

    def mask_sensitive_fields(self, data: dict) -> dict:
        """Return a copy of data with sensitive fields masked."""
        masked = {}
        for k, v in data.items():
            if k.lower() in self.config.sensitive_fields:
                if isinstance(v, str) and len(v) > 4:
                    masked[k] = v[:2] + "****" + v[-2:]
                else:
                    masked[k] = "****"
            elif isinstance(v, dict):
                masked[k] = self.mask_sensitive_fields(v)
            else:
                masked[k] = v
        return masked
