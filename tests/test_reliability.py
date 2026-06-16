import asyncio

import pytest
from fastapi.testclient import TestClient

from app.adapters.mock_provider import MockProviderAdapter, MockScenario
from app.adapters.router import ProviderRouter
from app.core.config import GatewayConfig, ProviderEntry
from app.core.flow_control import BoundedQueue
from app.core.metrics import Metrics
from app.core.state_machine import EventType
from app.main import GatewayApp, create_app
from app.models.envelope import Envelope, MessageType


@pytest.mark.asyncio
async def test_upstream_cancel_calls_active_provider():
    config = GatewayConfig(
        providers=[ProviderEntry(
            provider_type="mock",
            name="mock",
            endpoint="mock://localhost",
            model="mock-model",
            api_key="unused",
        )],
        security_enabled=False,
        require_agent_id=False,
        audit_enabled=False,
    )
    gateway = GatewayApp(config)
    provider = gateway.router.routes[0].adapter
    assert isinstance(provider, MockProviderAdapter)

    sm = gateway.session_store.get_or_create("s1", "c1")
    sm.on_event(EventType.INVOKE)
    gateway.session_store.set_active_provider("c1", "mock", provider)

    result = await gateway.handle_cancel(Envelope(
        type=MessageType.CANCEL,
        session_id="s1",
        corr_id="c1",
        payload={"reason": "user requested"},
    ))

    assert result["payload"]["error_code"] == "CANCELLED"
    assert result["payload"]["upstream_cancelled"] is True
    assert ("s1", "c1") in provider.cancelled_requests


def test_provider_circuit_breaker_skips_failed_provider():
    router = ProviderRouter(strategy="priority")
    router.failure_threshold = 2
    router.circuit_breaker_cooldown = 60
    router.add_route("primary", MockProviderAdapter(), priority=10)
    router.add_route("secondary", MockProviderAdapter(), priority=5)

    assert router.select("s1")[0] == "primary"
    router.record_failure("primary", "boom")
    assert router.select("s1")[0] == "primary"
    router.record_failure("primary", "boom again")

    health = router.health_summary()["primary"]
    assert health["circuit_open"] is True
    assert router.select("s1")[0] == "secondary"


@pytest.mark.asyncio
async def test_health_check_restores_provider_after_failure():
    router = ProviderRouter(strategy="priority")
    router.failure_threshold = 1
    router.add_route("primary", MockProviderAdapter(), priority=10)
    router.record_failure("primary", "transient")
    assert router.health_summary()["primary"]["available"] is False

    results = await router.check_health()
    assert results["primary"]["healthy"] is True
    assert results["primary"]["available"] is True
    assert router.select("s1")[0] == "primary"


@pytest.mark.asyncio
async def test_bounded_queue_put_waits_for_space():
    queue = BoundedQueue(max_length=1)
    assert await queue.put("first", timeout=0.01)

    waiter = asyncio.create_task(queue.put("second", timeout=1.0))
    await asyncio.sleep(0.05)
    assert waiter.done() is False

    assert queue.pop() == "first"
    assert await waiter is True
    assert queue.pop() == "second"


@pytest.mark.asyncio
async def test_bounded_queue_put_times_out_when_full():
    queue = BoundedQueue(max_length=1)
    assert await queue.put("first", timeout=0.01)
    assert await queue.put("second", timeout=0.01) is False
    assert queue.pop() == "first"


def test_metrics_records_reliability_signals():
    metrics = Metrics()
    metrics.record_upstream_cancel(True)
    metrics.record_backpressure_wait(12.5)
    metrics.record_backpressure_reject()
    metrics.record_provider_circuit_open()
    metrics.update_provider_health("mock", {"healthy": True, "available": True})

    summary = metrics.summary()
    assert summary["upstream_cancel_count"] == 1
    assert summary["upstream_cancel_success_count"] == 1
    assert summary["backpressure_wait_count"] == 1
    assert summary["backpressure_reject_count"] == 1
    assert summary["provider_circuit_open_count"] == 1
    assert summary["provider_health"]["mock"]["available"] is True


def test_provider_health_endpoint_and_dashboard_data():
    config = GatewayConfig(
        providers=[ProviderEntry(
            provider_type="mock",
            name="mock",
            endpoint="mock://localhost",
            model="mock-model",
            api_key="unused",
        )],
        security_enabled=False,
        require_agent_id=False,
        audit_enabled=False,
    )
    client = TestClient(create_app(config))

    health = client.get("/providers/health")
    assert health.status_code == 200
    assert "mock" in health.json()

    checked = client.post("/providers/health/check")
    assert checked.status_code == 200
    assert checked.json()["mock"]["healthy"] is True

    dashboard = client.get("/dashboard/reliability-data")
    assert dashboard.status_code == 200
    assert "metrics" in dashboard.json()
    assert "providers" in dashboard.json()

    prometheus = client.get("/metrics/prometheus")
    assert prometheus.status_code == 200
    assert "tele_laika_request_count" in prometheus.text
