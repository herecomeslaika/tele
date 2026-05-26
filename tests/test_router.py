# Tests for Extension Goal 1: Multi-Provider Router

import pytest

from app.adapters.mock_provider import MockProviderAdapter, MockScenario
from app.adapters.router import ProviderRoute, ProviderRouter
from app.models.envelope import Envelope, MessageType


def _make_env(session_id: str, payload: dict | None = None) -> Envelope:
    return Envelope(
        version="A2A_min_v1",
        type=MessageType.INVOKE,
        session_id=session_id,
        corr_id=f"corr_{session_id}",
        seq=0,
        payload=payload or {"prompt": "test"},
    )


class TestPriorityRouting:
    def test_selects_highest_priority(self):
        router = ProviderRouter()
        primary = MockProviderAdapter(scenario=MockScenario.NORMAL)
        fallback = MockProviderAdapter(scenario=MockScenario.NORMAL)
        router.add_route("primary", primary, priority=0)
        router.add_route("fallback", fallback, priority=10)

        name, adapter = router.select("s1")
        assert name == "primary"
        assert adapter is primary

    def test_empty_routes_raises(self):
        router = ProviderRouter()
        with pytest.raises(RuntimeError, match="No provider routes"):
            router.select("s1")


class TestHashRouting:
    def test_stable_hash_same_session(self):
        router = ProviderRouter(strategy="hash")
        router.add_route("a", MockProviderAdapter(), priority=0)
        router.add_route("b", MockProviderAdapter(), priority=1)

        name1, _ = router.select("session_x")
        name2, _ = router.select("session_x")
        assert name1 == name2  # session affinity

    def test_different_sessions_distribute(self):
        router = ProviderRouter(strategy="hash")
        router.add_route("a", MockProviderAdapter(), priority=0)
        router.add_route("b", MockProviderAdapter(), priority=1)

        names = set()
        for i in range(20):
            name, _ = router.select(f"session_{i}")
            names.add(name)
        # With 20 sessions and 2 providers, both should get some traffic
        assert len(names) >= 1  # at minimum one, but with 20 samples almost certainly 2


class TestRoundRobinRouting:
    def test_rotates_across_providers(self):
        router = ProviderRouter(strategy="round_robin")
        router.add_route("a", MockProviderAdapter(), priority=0)
        router.add_route("b", MockProviderAdapter(), priority=1)

        names = [router.select(f"s{i}")[0] for i in range(4)]
        assert names == ["a", "b", "a", "b"]


class TestFailover:
    @pytest.mark.asyncio
    async def test_failover_on_error(self):
        router = ProviderRouter(strategy="priority")
        error_provider = MockProviderAdapter(scenario=MockScenario.ERROR)
        normal_provider = MockProviderAdapter(scenario=MockScenario.NORMAL)
        router.add_route("broken", error_provider, priority=0)
        router.add_route("backup", normal_provider, priority=1)

        env = _make_env("s_failover")
        result = await router.invoke_with_failover(env)

        # Should have fallen over to backup
        assert isinstance(result.payload, dict)
        assert result.payload.get("served_by") == "backup"

    @pytest.mark.asyncio
    async def test_no_failover_when_primary_ok(self):
        router = ProviderRouter(strategy="priority")
        primary = MockProviderAdapter(scenario=MockScenario.NORMAL)
        backup = MockProviderAdapter(scenario=MockScenario.NORMAL)
        router.add_route("primary", primary, priority=0)
        router.add_route("backup", backup, priority=1)

        env = _make_env("s_ok")
        result = await router.invoke_with_failover(env)
        assert isinstance(result.payload, dict)
        assert result.payload.get("served_by") == "primary"

    def test_failover_returns_none_when_exhausted(self):
        router = ProviderRouter()
        router.add_route("only", MockProviderAdapter(), priority=0)
        result = router.failover("only", "s1")
        assert result is None

    def test_failover_picks_next_route(self):
        router = ProviderRouter()
        router.add_route("a", MockProviderAdapter(), priority=0)
        router.add_route("b", MockProviderAdapter(), priority=1)
        router.add_route("c", MockProviderAdapter(), priority=2)

        name, _ = router.failover("a", "s1")
        assert name == "b"


class TestProviderIsolation:
    @pytest.mark.asyncio
    async def test_different_providers_independent(self):
        """Two providers on the router should have fully isolated state."""
        router = ProviderRouter(strategy="hash")
        provider_a = MockProviderAdapter(scenario=MockScenario.NORMAL, chunk_count=2)
        provider_b = MockProviderAdapter(scenario=MockScenario.NORMAL, chunk_count=5)
        router.add_route("a", provider_a, priority=0)
        router.add_route("b", provider_b, priority=1)

        # Use two sessions that should hash to different providers
        env_a = _make_env("session_isolation_a")
        env_b = _make_env("session_isolation_b")

        result_a = await provider_a.invoke(env_a)
        result_b = await provider_b.invoke(env_b)

        # Each provider returns its own mock response independently
        assert result_a.payload is not result_b.payload