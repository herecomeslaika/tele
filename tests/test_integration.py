"""Integration checks using the current GatewayApp and MockProviderAdapter APIs."""

import json

import pytest

from app.adapters.mock_provider import MockProviderAdapter, MockScenario
from app.core.config import GatewayConfig, ProviderEntry
from app.core.logger import StructuredFormatter
from app.main import GatewayApp
from app.models.envelope import Envelope, MessageType


def _config() -> GatewayConfig:
    return GatewayConfig(
        providers=[
            ProviderEntry(
                name="mock",
                provider_type="mock",
                endpoint="mock://localhost",
                model="mock-model",
            )
        ],
        audit_enabled=False,
        security_enabled=False,
    )


def _invoke(session_id: str = "s1", corr_id: str = "c1") -> dict:
    return {
        "version": "v1",
        "type": "INVOKE",
        "session_id": session_id,
        "corr_id": corr_id,
        "payload": {"prompt": "hello", "model": "mock-model"},
    }


@pytest.mark.asyncio
async def test_full_gateway_invoke_pipeline():
    app = GatewayApp(_config())
    chunks = [chunk async for chunk in app.handle_envelope(_invoke())]

    assert [c["type"] for c in chunks].count(MessageType.STREAM_CHUNK) == 3
    assert chunks[-1]["type"] == MessageType.STREAM_END
    assert chunks[-1]["payload"]["reason"] == "stop"


@pytest.mark.asyncio
async def test_bad_request_returns_error():
    app = GatewayApp(_config())
    chunks = [
        chunk
        async for chunk in app.handle_envelope(
            {"version": "v1", "type": "INVOKE", "session_id": "s", "corr_id": "c", "payload": {}}
        )
    ]
    assert chunks[0]["type"] == MessageType.ERROR
    assert chunks[0]["payload"]["error_code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_provider_adapter_error_event():
    adapter = MockProviderAdapter(scenario=MockScenario.ERROR)
    events = [event async for event in adapter.invoke("hello", model="mock-model")]
    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].error_code == "PROVIDER_ERROR"


@pytest.mark.asyncio
async def test_cancel_unknown_session_returns_error():
    app = GatewayApp(_config())
    env = Envelope(
        type=MessageType.CANCEL,
        session_id="missing",
        corr_id="missing-corr",
        payload={},
    )
    result = await app.handle_cancel(env)
    assert result["type"] == MessageType.ERROR
    assert result["payload"]["error_code"] == "UNKNOWN_SESSION"


def test_structured_formatter_includes_required_fields():
    import logging

    formatter = StructuredFormatter()
    record = logging.LogRecord("test", logging.INFO, "x.py", 1, "hello", (), None)
    record.structured_extra = {"event": "unit.test", "session_id": "s1", "corr_id": "c1"}
    entry = json.loads(formatter.format(record))

    for field in ["timestamp", "session_id", "corr_id", "seq", "state", "event", "latency_ms", "error_code"]:
        assert field in entry
    assert entry["event"] == "unit.test"
