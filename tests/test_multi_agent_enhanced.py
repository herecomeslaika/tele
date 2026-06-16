import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import GatewayConfig, ProviderEntry
from app.core.multi_agent import AgentProfile, MultiAgentManager
from app.main import create_app
from app.models.envelope import Envelope, MessageType


def make_delegate(payload: dict) -> Envelope:
    return Envelope(
        version="v1",
        type=MessageType.AGENT_DELEGATE,
        session_id="s1",
        corr_id="c1",
        seq=1,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_fan_in_concat_aggregates_results():
    manager = MultiAgentManager()
    manager.register_agent(AgentProfile(agent_id="researcher", name="Researcher"))
    manager.register_agent(AgentProfile(agent_id="coder", name="Coder"))

    envelope = make_delegate({
        "pattern": "fan-in",
        "target_agents": ["researcher", "coder"],
        "task": "analyze multi-agent design",
        "aggregation": "concat",
        "failure_policy": "partial",
    })

    responses = []
    async for response in manager.handle_fan_in(envelope):
        responses.append(response)

    assert len(responses) == 1
    payload = responses[0]["payload"]
    assert responses[0]["type"] == "AGENT_RESPONSE"
    assert payload["pattern"] == "fan-in"
    assert payload["status"] == "completed"
    assert payload["sub_count"] == 2
    assert "[researcher]" in payload["result"]
    assert "[coder]" in payload["result"]


@pytest.mark.asyncio
async def test_pipeline_passes_previous_step_result():
    manager = MultiAgentManager()
    manager.register_agent(AgentProfile(agent_id="planner", name="Planner"))
    manager.register_agent(AgentProfile(agent_id="worker", name="Worker"))

    envelope = make_delegate({
        "pattern": "pipeline",
        "task": "build feature",
        "steps": [
            {"agent": "planner", "task": "step1 {input}"},
            {"agent": "worker", "task": "step2 saw {previous}"},
        ],
        "failure_policy": "fail_fast",
    })

    responses = []
    async for response in manager.handle_pipeline(envelope):
        responses.append(response)

    payload = responses[0]["payload"]
    assert payload["pattern"] == "pipeline"
    assert payload["status"] == "completed"
    assert payload["step_count"] == 2
    assert payload["result"] == "step2 saw step1 build feature"


@pytest.mark.asyncio
async def test_planner_worker_reviewer_flow_by_roles():
    manager = MultiAgentManager()
    manager.register_agent(AgentProfile(agent_id="planner-1", name="Planner", roles=["planner"]))
    manager.register_agent(AgentProfile(agent_id="worker-1", name="Worker", roles=["worker"]))
    manager.register_agent(AgentProfile(agent_id="reviewer-1", name="Reviewer", roles=["reviewer"]))

    envelope = make_delegate({
        "pattern": "planner-worker-reviewer",
        "task": "ship multi-agent enhancement",
        "planner_task": "plan {input}",
        "worker_task": "work from {previous}",
        "reviewer_task": "review {work}",
        "aggregation": "summary",
    })

    responses = []
    async for response in manager.handle_planner_worker_reviewer(envelope):
        responses.append(response)

    payload = responses[0]["payload"]
    assert payload["pattern"] == "planner-worker-reviewer"
    assert payload["status"] == "completed"
    assert payload["plan"]["target_agent"] == "planner-1"
    assert payload["worker_results"][0]["target_agent"] == "worker-1"
    assert payload["review"]["target_agent"] == "reviewer-1"
    result = json.loads(payload["result"])
    assert "worker_aggregate" in result


@pytest.mark.asyncio
async def test_cross_http_agent_endpoint_is_used():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "chunks": [
                    {"type": "STREAM_CHUNK", "payload": {"content": "remote"}},
                    {"type": "STREAM_CHUNK", "payload": {"content": " ok"}},
                    {"type": "STREAM_END", "payload": {"reason": "stop"}},
                ]
            },
        )

    manager = MultiAgentManager(http_transport=httpx.MockTransport(handler))
    manager.register_agent(AgentProfile(
        agent_id="remote-agent",
        name="Remote",
        endpoint="https://remote.example/invoke",
        api_key="remote-key",
    ))

    envelope = make_delegate({
        "target_agent": "remote-agent",
        "task": "call remote",
        "model": "mock-model",
    })

    responses = []
    async for response in manager.handle_delegate(envelope):
        responses.append(response)

    assert len(requests) == 1
    assert requests[0].headers["x-api-key"] == "remote-key"
    assert responses[0]["payload"]["result"] == "remote ok"


@pytest.mark.asyncio
async def test_compensation_agent_recovers_failed_http_agent():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/worker"):
            return httpx.Response(500, text="worker failed")
        return httpx.Response(200, json={"result": "compensated result"})

    manager = MultiAgentManager(http_transport=httpx.MockTransport(handler))
    manager.register_agent(AgentProfile(
        agent_id="worker",
        name="Worker",
        endpoint="https://remote.example/worker",
    ))
    manager.register_agent(AgentProfile(
        agent_id="compensator",
        name="Compensator",
        endpoint="https://remote.example/compensator",
    ))

    envelope = make_delegate({
        "pattern": "fan-in",
        "target_agents": ["worker"],
        "task": "do risky work",
        "aggregation": "concat",
        "failure_policy": "compensate",
        "compensation_agent": "compensator",
    })

    responses = []
    async for response in manager.handle_fan_in(envelope):
        responses.append(response)

    payload = responses[0]["payload"]
    assert payload["status"] == "compensated"
    assert "compensated result" in payload["result"]
    assert payload["compensations"][0]["failed_agent"] == "worker"


def test_fan_in_rest_endpoint():
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

    client.post("/agents/register", json={"agent_id": "a1", "name": "Agent 1"})
    client.post("/agents/register", json={"agent_id": "a2", "name": "Agent 2"})
    response = client.post("/delegate/fan-in", json={
        "target_agents": ["a1", "a2"],
        "task": "combine",
        "aggregation": "summary",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "AGENT_RESPONSE"
    assert body["payload"]["pattern"] == "fan-in"
    assert body["payload"]["sub_count"] == 2
