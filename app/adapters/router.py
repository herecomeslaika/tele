"""A2A_min_v1 Provider Router — multi-provider routing with capability-based selection."""

from __future__ import annotations

import hashlib
import time
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
    runtime: str = ""
    healthy: bool = True
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    last_error: str = ""
    last_health_check: float = 0.0

    @property
    def circuit_open(self) -> bool:
        return self.circuit_open_until > time.time()

    @property
    def available(self) -> bool:
        return self.healthy and not self.circuit_open


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
      - runtime: match by runtime label (e.g. "python", "node", "go")
    """

    routes: list[ProviderRoute] = field(default_factory=list)
    strategy: str = "priority"
    capability_registry: CapabilityRegistry = field(default_factory=CapabilityRegistry)
    _rr_index: int = field(default=0, repr=False)
    failure_threshold: int = 3
    circuit_breaker_cooldown: float = 30.0

    def add_route(
        self,
        name: str,
        adapter: ProviderAdapter,
        priority: int = 0,
        weight: int = 100,
        capabilities: Optional[list[str]] = None,
        models: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None,
        runtime: str = "",
    ) -> None:
        self.routes.append(ProviderRoute(
            name=name, adapter=adapter, priority=priority, weight=weight,
            capabilities=capabilities or [],
            models=models or [],
            task_types=task_types or [],
            runtime=runtime,
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
        if not self._available_routes():
            raise RuntimeError("No healthy provider routes available")

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
        elif self.strategy == "runtime":
            return self._select_by_runtime(session_id, capabilities or [])
        else:
            raise ValueError(f"Unknown routing strategy: {self.strategy}")

    def _select_priority(self, session_id: str) -> tuple[str, ProviderAdapter]:
        route = self._available_routes()[0]
        log_event(logger, "router.priority_select", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_hash(self, session_id: str) -> tuple[str, ProviderAdapter]:
        routes = self._available_routes()
        h = int(hashlib.sha256(session_id.encode()).hexdigest(), 16)
        idx = h % len(routes)
        route = routes[idx]
        log_event(logger, "router.hash_select", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_round_robin(self, session_id: str) -> tuple[str, ProviderAdapter]:
        routes = self._available_routes()
        idx = self._rr_index % len(routes)
        self._rr_index += 1
        route = routes[idx]
        log_event(logger, "router.round_robin_select", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_by_model(self, session_id: str, model: str) -> tuple[str, ProviderAdapter]:
        """Route based on model name in the request."""
        routes = self._available_routes()
        available_names = {r.name for r in routes}
        # Use capability registry for smart matching
        match = self.capability_registry.best_match(model=model)
        if match and match in available_names:
            for route in routes:
                if route.name == match:
                    log_event(logger, "router.model_select", state=f"provider={route.name},model={model}")
                    return route.name, route.adapter
        # Fallback: direct scan
        for route in routes:
            if model in route.models or not route.models:
                log_event(logger, "router.model_select", state=f"provider={route.name},model={model}")
                return route.name, route.adapter
        # Fallback to first route
        route = routes[0]
        log_event(logger, "router.model_select_fallback", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_by_task_type(self, session_id: str, task_type: str) -> tuple[str, ProviderAdapter]:
        """Route based on task type (e.g. 'chat', 'code', 'reasoning')."""
        routes = self._available_routes()
        available_names = {r.name for r in routes}
        match = self.capability_registry.best_match(task_type=task_type)
        if match and match in available_names:
            for route in routes:
                if route.name == match:
                    log_event(logger, "router.task_type_select", state=f"provider={route.name},task={task_type}")
                    return route.name, route.adapter
        for route in routes:
            if task_type in route.task_types or not route.task_types:
                log_event(logger, "router.task_type_select", state=f"provider={route.name},task={task_type}")
                return route.name, route.adapter
        route = routes[0]
        log_event(logger, "router.task_type_select_fallback", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_by_capability(self, session_id: str, capabilities: list[str]) -> tuple[str, ProviderAdapter]:
        """Route based on required capability tags."""
        routes = self._available_routes()
        available_names = {r.name for r in routes}
        match = self.capability_registry.best_match(capabilities=capabilities)
        if match and match in available_names:
            for route in routes:
                if route.name == match:
                    log_event(logger, "router.capability_select", state=f"provider={route.name}")
                    return route.name, route.adapter
        for route in routes:
            if all(c in route.capabilities for c in capabilities):
                log_event(logger, "router.capability_select", state=f"provider={route.name}")
                return route.name, route.adapter
        route = routes[0]
        log_event(logger, "router.capability_select_fallback", state=f"provider={route.name}")
        return route.name, route.adapter

    def _select_by_runtime(self, session_id: str, runtime_labels: list[str]) -> tuple[str, ProviderAdapter]:
        """Route based on runtime label (e.g. 'python', 'node', 'go').

        If runtime_labels are provided, match against ProviderRoute.runtime.
        Falls back to first route if no match.
        """
        routes = self._available_routes()
        for label in runtime_labels:
            for route in routes:
                if route.runtime and route.runtime.lower() == label.lower():
                    log_event(logger, "router.runtime_select",
                              state=f"provider={route.name},runtime={label}")
                    return route.name, route.adapter
        # Fallback: try capabilities as runtime hint
        for label in runtime_labels:
            for route in routes:
                if label.lower() in [c.lower() for c in route.capabilities]:
                    log_event(logger, "router.runtime_select_cap",
                              state=f"provider={route.name},runtime={label}")
                    return route.name, route.adapter
        route = routes[0]
        log_event(logger, "router.runtime_select_fallback", state=f"provider={route.name}")
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

        candidates = [r for r in self.routes[failed_idx + 1:] if r.available]
        if not candidates:
            log_event(logger, "router.failover_exhausted",
                      error_code="PROVIDER_ERROR", state=f"failed={failed_name}")
            return None
        next_route = candidates[0]
        log_event(logger, "router.failover",
                  state=f"from={failed_name} to={next_route.name}")
        return next_route.name, next_route.adapter

    def record_success(self, provider_name: str) -> None:
        route = self.get_route(provider_name)
        if not route:
            return
        route.healthy = True
        route.consecutive_failures = 0
        route.circuit_open_until = 0.0
        route.last_error = ""

    def record_failure(self, provider_name: str, error: str = "") -> None:
        route = self.get_route(provider_name)
        if not route:
            return
        route.consecutive_failures += 1
        route.last_error = error
        if route.consecutive_failures >= self.failure_threshold:
            route.healthy = False
            route.circuit_open_until = time.time() + self.circuit_breaker_cooldown
            log_event(
                logger,
                "router.circuit_opened",
                error_code="PROVIDER_ERROR",
                state=f"provider={provider_name},failures={route.consecutive_failures}",
            )

    async def check_health(self) -> dict[str, dict[str, Any]]:
        """Run provider health checks and update route availability."""
        results: dict[str, dict[str, Any]] = {}
        now = time.time()
        for route in self.routes:
            ok = False
            error = ""
            try:
                ok = await route.adapter.health_check()
            except Exception as exc:
                error = str(exc)
                ok = False

            route.last_health_check = now
            if ok:
                route.healthy = True
                route.consecutive_failures = 0
                route.circuit_open_until = 0.0
                route.last_error = ""
            else:
                route.healthy = False
                route.last_error = error or "health_check_failed"

            results[route.name] = self._route_health_dict(route)
            log_event(logger, "router.health_check", state=f"provider={route.name},healthy={route.healthy}")
        return results

    def get_route(self, provider_name: str) -> Optional[ProviderRoute]:
        for route in self.routes:
            if route.name == provider_name:
                return route
        return None

    def health_summary(self) -> dict[str, dict[str, Any]]:
        return {route.name: self._route_health_dict(route) for route in self.routes}

    def _available_routes(self) -> list[ProviderRoute]:
        now = time.time()
        for route in self.routes:
            if route.circuit_open_until and route.circuit_open_until <= now:
                route.circuit_open_until = 0.0
        return [route for route in self.routes if route.available]

    def _route_health_dict(self, route: ProviderRoute) -> dict[str, Any]:
        return {
            "healthy": route.healthy,
            "available": route.available,
            "consecutive_failures": route.consecutive_failures,
            "circuit_open": route.circuit_open,
            "circuit_open_until": route.circuit_open_until,
            "last_error": route.last_error,
            "last_health_check": route.last_health_check,
        }
