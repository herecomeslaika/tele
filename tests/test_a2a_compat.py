"""Tests for the official A2A HTTP+JSON compatibility layer."""

import json

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import GatewayConfig, ProviderEntry
from app.main import create_app
from app.models.a2a import Part


def _client() -> TestClient:
    return TestClient(
        create_app(
            GatewayConfig(
                providers=[
                    ProviderEntry(
                        name="mock",
                        provider_type="mock",
                        endpoint="mock://localhost",
                        model="mock-model",
                    )
                ],
                security_enabled=False,
                require_agent_id=False,
                audit_enabled=False,
            )
        )
    )


def _send_request(text: str = "hello") -> dict:
    return {
        "message": {
            "messageId": "msg-1",
            "role": "ROLE_USER",
            "contextId": "ctx-a2a",
            "parts": [{"text": text}],
        },
        "configuration": {"acceptedOutputModes": ["text/plain"]},
        "model": "mock-model",
    }


def test_agent_card_discovery():
    response = _client().get("/.well-known/agent-card.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/a2a+json")
    body = response.json()
    assert body["name"] == "A2A_min_v1 Gateway"
    assert body["capabilities"]["streaming"] is True
    assert body["supportedInterfaces"][0]["protocolBinding"].endswith("/http+json/v1")


def test_part_requires_exactly_one_content_field():
    assert Part(text="ok").text == "ok"
    try:
        Part(text="x", data={"y": 1})
    except ValidationError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("Part accepted multiple content fields")


def test_message_send_returns_completed_task():
    response = _client().post(
        "/message:send",
        json=_send_request(),
        headers={"Content-Type": "application/a2a+json"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/a2a+json")
    task = response.json()["task"]
    assert task["id"].startswith("task-")
    assert task["contextId"] == "ctx-a2a"
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["artifacts"][0]["parts"][0]["text"] == "Hello world!"


def test_task_query_and_list_after_send():
    client = _client()
    send = client.post("/message:send", json=_send_request()).json()
    task_id = send["task"]["id"]

    get_response = client.get(f"/tasks/{task_id}")
    assert get_response.status_code == 200
    assert get_response.json()["task"]["id"] == task_id

    list_response = client.get("/tasks", params={"contextId": "ctx-a2a"})
    assert list_response.status_code == 200
    ids = [task["id"] for task in list_response.json()["tasks"]]
    assert task_id in ids


def test_message_stream_yields_status_artifact_and_task():
    with _client().stream("POST", "/message:stream", json=_send_request()) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line.startswith("data: ")]

    payloads = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert "statusUpdate" in payloads[0]
    assert any("artifactUpdate" in payload for payload in payloads)
    assert "task" in payloads[-1]
    assert payloads[-1]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


def test_unknown_task_uses_standard_error_shape():
    response = _client().get("/tasks/not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["status"] == "NOT_FOUND"
    assert body["error"]["details"][0]["reason"] == "TASK_NOT_FOUND"
    assert body["error"]["details"][0]["domain"] == "a2a-protocol.org"


def test_cancel_completed_task_is_not_cancelable():
    client = _client()
    task_id = client.post("/message:send", json=_send_request()).json()["task"]["id"]
    response = client.post(f"/tasks/{task_id}:cancel")
    assert response.status_code == 400
    assert response.json()["error"]["details"][0]["reason"] == "TASK_NOT_CANCELABLE"


def test_extended_agent_card_not_configured():
    response = _client().get("/extendedAgentCard")
    assert response.status_code == 400
    assert response.json()["error"]["details"][0]["reason"] == "EXTENDED_AGENT_CARD_NOT_CONFIGURED"
