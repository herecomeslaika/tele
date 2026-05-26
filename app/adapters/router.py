"""A2A_min_v1 Provider Router — multi-provider routing with capability-based selection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from app.adapters.provider import ProviderAdapter, ProviderConfig, ProviderType
from app.core.logger import setup_logger, log_event

logger = setup_logger("provider_router")


@dataclass
class ProviderRoute:
    """A named provider entry with priority, weight, and capability tags."""

    name: str
    adapter: ProviderAdapter
    priority: int = 0
    weight: int = 100
    capabilities: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Capability Registry — #26 model capability routing
# ---------------------------------------------------------------------------
@dataclass
class CapabilityProfile:
    """Declares what a provider can do."""

    name: str
    capabilities: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    max_context_tokens: int = 4096
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_code: bool = False
    supports_reasoning: bool = False


@dataclass
class CapabilityRegistry:
    """Registry of provider capability profiles.

    Allows lookup by capability, model name, or task type,
    returning the best-fit provider with fallback.
    """

    profiles: dict[str, CapabilityProfile] = field(default_factory=dict)

    def register(self, profile: CapabilityProfile) -> None:
        self.profiles[profile.name] = profile

    def get(self, name: str) -> Optional[CapabilityProfile]:
        return self.profiles.get(name)

    def find_by_capability(self, required: list[str]) -> list[str]:
        """Return provider names whose profiles include ALL required capabilities."""
        results = []
        for name, prof in self.profiles.items():
            if all(c in prof.capabilities for c in required):
                results.append(name)
        return results

    def find_by_model(self, model: str) -> list[str]:
        """Return provider names that serve a specific model."""
        results = []
        for name, prof in self.profiles.items():
            if model in prof.models or not prof.models:
                results.append(name)
        return results

    def find_by_task_type(self, task_type: str) -> list[str]:
        """Return provider names that handle a specific task type."""
        results = []
        for name, prof in self.profiles.items():
            if task_type in prof.task_types or not prof.task_types:
                results.append(name)
        return results

    def best_match(self, model: Optional[str] = None,
                   task_type: Optional[str] = None,
                   capabilities: Optional[list[str]] = None) -> Optional[str]:
        """Find the best-matching provider by intersecting model, task_type, and capability filters."""
        candidates = set(self.profiles.keys())
        if model:
            candidates &= set(self.find_by_model(model))
        if task_type:
            candidates &= set(self.find_by_task_type(task_type))
        if capabilities:
            candidates &= set(self.find_by_capability(capabilities))
        return next(iter(sorted(candidates)), None)


@dataclass
class ProviderRouter:
    """Routes requests to different providers based on strategy.

    Strategies:
      - priority: highest-priority healthy provider; failover on ERROR
      - hash: stable-hash on session_id (session affinity)
      - round_robin: sequential rotation
      - model_name: match by model name in the request
      - task_type: match by task_type in the request
      - capability: match by required capability tags
    """

    routes: list[ProviderRoute] = field(default_factory=list)
    strategy: str = "priority"
    capability_registry: CapabilityRegistry = field(default_factory=CapabilityRegistry)
    _rr_index: int = field(default=0, repr=False)

    def add_route(
        self,
        name: str,
        adapter: ProviderAdapter,
        priority: int = 0,
        weight: int = 100,
        capabilities: Optional[list[str]] = None,
        models: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None,
    ) -> None:
        self.routes.append(ProviderRoute(
            name=name, adapter=adapter, priority=priority, weight=weight,
            capabilities=capabilities or [],
            models=models or [],
            task_types=task_types or [],
        ))
        self.routes.sort(key=lambda r: r.priority, reverse=True)

        # Auto-register capability profile (#26)
        self.capability_registry.register(CapabilityProfile(
            name=name,
            capabilities=capabilities or [],
            models=models or [],
            task_types=task_types or [],
        ))

    def select(
        self,
        session_id: str,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        capabilities: Optional[list[str]] = None,
    ) -> tuple[str, ProviderAdapter]:
        """Select a provider based on strategy and request metadata."""
        if not self.routes:
            raise RuntimeError("No provider routes configured")

        if self.strategy == "priority":
            return self._select_priority(session_id)
        elif self.strategy == "hash":
            return self._select_hash(session_id)
        elif self.strategy == "round_robin":
            return self._select_round_robin(session_id)
        elif self.strategy == "model_name":
            return self._select_by_model(session_id, model or "")
        elif self.strategy == "task_type":
            return self._select_by_task_type(session_id, task_type or "")
        elif self.strategy == "capability":
            return self._select_by_capability(session_id, capabilities or [])
        else:
            raise ValueError(f"Unknown routing strategy: {self.strategy}")

    def _select_priority(self, session_id: str) -> tuple[str, ProviderAdapter]:
        route = self.routes[0]
        log_event(logger, "router.priority_select", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_hash(self, session_id: str) -> tuple[str, ProviderAdapter]:
        h = int(hashlib.sha256(session_id.encode()).hexdigest(), 16)
        idx = h % len(self.routes)
        route = self.routes[idx]
        log_event(logger, "router.hash_select", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_round_robin(self, session_id: str) -> tuple[str, ProviderAdapter]:
        idx = self._rr_index % len(self.routes)
        self._rr_index += 1
        route = self.routes[idx]
        log_event(logger, "router.round_robin_select", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_by_model(self, session_id: str, model: str) -> tuple[str, ProviderAdapter]:
        """Route based on model name in the request."""
        # Use capability registry for smart matching
        match = self.capability_registry.best_match(model=model)
        if match:
            for route in self.routes:
                if route.name == match:
                    log_event(logger, "router.model_select", state=f"provider={route.name},model={model}")
                    return route.name, route.adapter
        # Fallback: direct scan
        for route in self.routes:
            if model in route.models or not route.models:
                log_event(logger, "router.model_select", state=f"provider={route.name},model={model}")
                return route.name, route.adapter
        # Fallback to first route
        route = self.routes[0]
        log_event(logger, "router.model_select_fallback", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_by_task_type(self, session_id: str, task_type: str) -> tuple[str, ProviderAdapter]:
        """Route based on task type (e.g. 'chat', 'code', 'reasoning')."""
        match = self.capability_registry.best_match(task_type=task_type)
        if match:
            for route in self.routes:
                if route.name == match:
                    log_event(logger, "router.task_type_select", state=f"provider={route.name},task={task_type}")
                    return route.name, route.adapter
        for route in self.routes:
            if task_type in route.task_types or not route.task_types:
                log_event(logger, "router.task_type_select", state=f"provider={route.name},task={task_type}")
                return route.name, route.adapter
        route = self.routes[0]
        log_event(logger, "router.task_type_select_fallback", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_by_capability(self, session_id: str, capabilities: list[str]) -> tuple[str, ProviderAdapter]:
        """Route based on required capability tags."""
        match = self.capability_registry.best_match(capabilities=capabilities)
        if match:
            for route in self.routes:
                if route.name == match:
                    log_event(logger, "router.capability_select", state=f"provider={route.name}")
                    return route.name, route.adapter
        for route in self.routes:
            if all(c in route.capabilities for c in capabilities):
                log_event(logger, "router.capability_select", state=f"provider={route.name}")
                return route.name, route.adapter
        route = self.routes[0]
        log_event(logger, "router.capability_select_fallback", state=f"provider={route.name}")
        return route.name, route.adapter

    def failover(self, failed_name: str, session_id: str) -> Optional[tuple[str, ProviderAdapter]]:
        """Given a failed provider name, try the next provider."""
        failed_idx = None
        for i, r in enumerate(self.routes):
            if r.name == failed_name:
                failed_idx = i
                break

        if failed_idx is None or failed_idx + 1 >= len(self.routes):
            log_event(logger, "router.failover_exhausted",
                      error_code="PROVIDER_ERROR", state=f"failed={failed_name}")
            return None

        next_route = self.routes[failed_idx + 1]
        log_event(logger, "router.failover",
                  state=f"from={failed_name} to={next_route.name}")
        return next_route.name, next_route.adapter