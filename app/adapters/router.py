# A2A_min_v1 Provider Router — multi-provider routing with priority

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.adapters.provider import ProviderAdapter
from app.core.errors import ErrorCode, make_error_envelope
from app.core.logger import get_logger
from app.models.envelope import Envelope, MessageType

logger = get_logger("provider_router")


@dataclass
class ProviderRoute:
    """A named provider entry with priority and weight for load distribution."""

    name: str
    adapter: ProviderAdapter
    priority: int = 0      # Lower number = higher priority (tried first)
    weight: int = 100      # Relative weight for weighted-round-robin among same-priority routes


@dataclass
class ProviderRouter:
    """
    Routes requests to different providers based on strategy.

    Strategies:
      - priority: always pick the highest-priority healthy provider; failover to next priority on ERROR
      - hash: stable-hash on session_id to distribute across providers (session affinity)
      - round_robin: simple sequential rotation across providers

    Provider selection is isolated per route — no shared state leaks between providers.
    """

    routes: list[ProviderRoute] = field(default_factory=list)
    strategy: str = "priority"  # priority | hash | round_robin
    _rr_index: int = field(default=0, repr=False)

    def add_route(self, name: str, adapter: ProviderAdapter, priority: int = 0, weight: int = 100) -> None:
        self.routes.append(ProviderRoute(name=name, adapter=adapter, priority=priority, weight=weight))
        # Keep routes sorted by priority for deterministic behavior
        self.routes.sort(key=lambda r: r.priority)

    def select(self, session_id: str) -> tuple[str, ProviderAdapter]:
        """Select a provider for the given session_id according to the routing strategy."""
        if not self.routes:
            raise RuntimeError("No provider routes configured")

        if self.strategy == "priority":
            return self._select_priority(session_id)
        elif self.strategy == "hash":
            return self._select_hash(session_id)
        elif self.strategy == "round_robin":
            return self._select_round_robin(session_id)
        else:
            raise ValueError(f"Unknown routing strategy: {self.strategy}")

    def _select_priority(self, session_id: str) -> tuple[str, ProviderAdapter]:
        # Return the first (highest-priority) route
        route = self.routes[0]
        logger.log(
            event="router.priority_select",
            session_id=session_id,
            state=f"provider={route.name}",
        )
        return route.name, route.adapter

    def _select_hash(self, session_id: str) -> tuple[str, ProviderAdapter]:
        # Stable hash-based distribution — same session_id always goes to same provider
        h = int(hashlib.sha256(session_id.encode()).hexdigest(), 16)
        idx = h % len(self.routes)
        route = self.routes[idx]
        logger.log(
            event="router.hash_select",
            session_id=session_id,
            state=f"provider={route.name}",
        )
        return route.name, route.adapter

    def _select_round_robin(self, session_id: str) -> tuple[str, ProviderAdapter]:
        idx = self._rr_index % len(self.routes)
        self._rr_index += 1
        route = self.routes[idx]
        logger.log(
            event="router.round_robin_select",
            session_id=session_id,
            state=f"provider={route.name}",
        )
        return route.name, route.adapter

    def failover(self, failed_name: str, session_id: str) -> tuple[str, ProviderAdapter] | None:
        """
        Given a failed provider name, try the next provider at the same or lower priority.
        Returns None if no fallback available.
        """
        # Find the index of the failed route
        failed_idx = None
        for i, r in enumerate(self.routes):
            if r.name == failed_name:
                failed_idx = i
                break

        if failed_idx is None or failed_idx + 1 >= len(self.routes):
            logger.log(
                event="router.failover_exhausted",
                session_id=session_id,
                error_code="PROVIDER_TIMEOUT",
                state=f"failed={failed_name}",
            )
            return None

        next_route = self.routes[failed_idx + 1]
        logger.log(
            event="router.failover",
            session_id=session_id,
            state=f"from={failed_name} to={next_route.name}",
        )
        return next_route.name, next_route.adapter

    async def invoke_with_failover(self, envelope: Envelope) -> Envelope:
        """Invoke with automatic failover: if primary returns ERROR, try next provider."""
        name, adapter = self.select(envelope.session_id)
        result = await adapter.invoke(envelope)

        if result.type == MessageType.ERROR.value:
            fallback = self.failover(name, envelope.session_id)
            if fallback is not None:
                fb_name, fb_adapter = fallback
                result = await fb_adapter.invoke(envelope)
                # Tag the envelope with which provider actually served it
                if isinstance(result.payload, dict):
                    result.payload["served_by"] = fb_name

        if isinstance(result.payload, dict):
            result.payload.setdefault("served_by", name)

        return result