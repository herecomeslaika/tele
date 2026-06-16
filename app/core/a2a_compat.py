"""Official A2A compatibility helpers built on top of A2A_min_v1."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from app.core.errors import ErrorCodeDef
from app.models.a2a import (
    A2AErrorBody,
    A2AErrorResponse,
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    APIKeySecurityScheme,
    Artifact,
    ErrorInfo,
    Message,
    Part,
    Role,
    SecurityScheme,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    utc_now_iso,
)
from app.models.envelope import Envelope, MessageType
from app.models.state import SessionState


REST_BINDING_URI = "https://a2a-protocol.org/bindings/http+json/v1"


def dump_a2a(model: Any) -> dict:
    """Dump Pydantic A2A models as clean JSON-compatible dicts."""
    return model.model_dump(by_alias=True, exclude_none=True)


def text_from_parts(parts: Iterable[Part]) -> str:
    """Build a provider prompt from A2A message parts."""
    rendered: list[str] = []
    for part in parts:
        if part.text is not None:
            rendered.append(part.text)
        elif part.data is not None:
            rendered.append(json.dumps(part.data, ensure_ascii=False))
        elif part.url is not None:
            rendered.append(f"[file:url={part.url}]")
        elif part.raw is not None:
            rendered.append(f"[file:raw:{part.mediaType or 'application/octet-stream'}]")
    return "\n".join(rendered).strip()


def response_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/a2a+json",
        "A2A-Version": "1.0",
    }


def sse_headers() -> dict[str, str]:
    return {
        "A2A-Version": "1.0",
    }


def make_agent_card(base_url: str, security_enabled: bool = False) -> AgentCard:
    """Return the public Agent Card for this gateway."""
    base = base_url.rstrip("/") or "http://localhost:8000"
    security_schemes = None
    security_requirements = None
    if security_enabled:
        security_schemes = {
            "apiKey": SecurityScheme(
                apiKeySecurityScheme=APIKeySecurityScheme(
                    description="Gateway API key passed through X-API-Key.",
                )
            )
        }
        security_requirements = [{"apiKey": []}]

    return AgentCard(
        name="A2A_min_v1 Gateway",
        description=(
            "Course gateway with an official A2A HTTP+JSON compatibility layer, "
            "provider routing, streaming, audit, and multi-agent delegation."
        ),
        supportedInterfaces=[
            AgentInterface(url=base, protocolBinding=REST_BINDING_URI),
        ],
        provider=AgentProvider(
            organization="BUPT Communication Software Lab03 Team",
            url=base,
        ),
        version="2.0.0",
        documentationUrl=f"{base}/docs",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            extendedAgentCard=False,
        ),
        securitySchemes=security_schemes,
        securityRequirements=security_requirements,
        defaultInputModes=["text/plain", "application/json"],
        defaultOutputModes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id="llm-gateway-invoke",
                name="LLM Gateway Invocation",
                description="Routes user messages to configured LLM providers and returns artifacts.",
                tags=["chat", "gateway", "streaming", "provider-routing"],
                examples=["Explain the A2A_min_v1 state machine.", "Summarize this prompt."],
                inputModes=["text/plain", "application/json"],
                outputModes=["text/plain", "application/json"],
            ),
            AgentSkill(
                id="multi-agent-fanout",
                name="Multi-Agent Fan-out",
                description="Delegates a task to multiple registered agents and aggregates results.",
                tags=["multi-agent", "fan-out", "delegation"],
                examples=["Ask two agents to solve the same task and compare results."],
                inputModes=["text/plain", "application/json"],
                outputModes=["application/json"],
            ),
        ],
    )


def envelope_from_send_request(request: SendMessageRequest, default_model: str) -> Envelope:
    message = request.message
    task_id = message.taskId or f"task-{uuid.uuid4().hex[:12]}"
    context_id = message.contextId or f"ctx-{uuid.uuid4().hex[:12]}"
    prompt = text_from_parts(message.parts)
    metadata = request.metadata or {}
    model = request.model or metadata.get("model") or default_model

    return Envelope(
        type=MessageType.INVOKE,
        session_id=context_id,
        corr_id=task_id,
        payload={
            "prompt": prompt,
            "model": model,
            "task_type": request.taskType or metadata.get("task_type") or "chat",
            "stream": True,
        },
    )


def message_for_status(task_id: str, context_id: str, text: str) -> Message:
    return Message(
        messageId=f"msg-{uuid.uuid4().hex[:12]}",
        role=Role.ROLE_AGENT,
        taskId=task_id,
        contextId=context_id,
        parts=[Part(text=text, mediaType="text/plain")],
    )


def task_from_error(task_id: str, context_id: str, error_code: str, message: str) -> Task:
    return Task(
        id=task_id,
        contextId=context_id,
        status=TaskStatus(
            state=TaskState.TASK_STATE_FAILED,
            message=message_for_status(task_id, context_id, f"{error_code}: {message}"),
        ),
        metadata={"errorCode": error_code},
    )


def task_from_content(
    task_id: str,
    context_id: str,
    user_message: Message,
    content: str,
    state: TaskState = TaskState.TASK_STATE_COMPLETED,
    metadata: Optional[dict[str, Any]] = None,
) -> Task:
    artifact = Artifact(
        artifactId=f"artifact-{task_id}",
        name="response",
        description="Gateway provider response",
        parts=[Part(text=content, mediaType="text/plain")],
    )
    return Task(
        id=task_id,
        contextId=context_id,
        status=TaskStatus(state=state),
        artifacts=[artifact],
        history=[user_message],
        metadata=metadata,
    )


def session_state_to_task_state(state: SessionState) -> TaskState:
    if state == SessionState.DONE:
        return TaskState.TASK_STATE_COMPLETED
    if state == SessionState.FAILED:
        return TaskState.TASK_STATE_FAILED
    if state == SessionState.CANCELLED:
        return TaskState.TASK_STATE_CANCELED
    if state in (SessionState.INVOKED, SessionState.STREAMING):
        return TaskState.TASK_STATE_WORKING
    return TaskState.TASK_STATE_SUBMITTED


def artifact_update_from_chunk(task_id: str, context_id: str, content: str, seq: int) -> StreamResponse:
    artifact = Artifact(
        artifactId=f"artifact-{task_id}",
        name="response",
        parts=[Part(text=content, mediaType="text/plain", metadata={"seq": seq})],
    )
    return StreamResponse(
        artifactUpdate=TaskArtifactUpdateEvent(
            taskId=task_id,
            contextId=context_id,
            artifact=artifact,
            append=True,
            lastChunk=False,
        )
    )


def status_update(task_id: str, context_id: str, state: TaskState, message: Optional[str] = None) -> StreamResponse:
    return StreamResponse(
        statusUpdate=TaskStatusUpdateEvent(
            taskId=task_id,
            contextId=context_id,
            status=TaskStatus(
                state=state,
                message=message_for_status(task_id, context_id, message) if message else None,
            ),
        )
    )


def task_stream_response(task: Task) -> StreamResponse:
    return StreamResponse(task=task)


@dataclass
class A2ATaskStore:
    """In-memory A2A task snapshots for the compatibility layer."""

    tasks: dict[str, Task] = field(default_factory=dict)

    def put(self, task: Task) -> Task:
        self.tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def list(self, context_id: Optional[str] = None, state: Optional[TaskState] = None) -> list[Task]:
        results = list(self.tasks.values())
        if context_id:
            results = [t for t in results if t.contextId == context_id]
        if state:
            results = [t for t in results if t.status.state == state]
        return results


def error_response(
    status_code: int,
    status: str,
    reason: str,
    message: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict:
    body = A2AErrorResponse(
        error=A2AErrorBody(
            code=status_code,
            status=status,
            message=message,
            details=[
                ErrorInfo(
                    reason=reason,
                    metadata={
                        "timestamp": utc_now_iso(),
                        **(metadata or {}),
                    },
                )
            ],
        )
    )
    return dump_a2a(body)


def error_from_gateway_payload(payload: dict, task_id: str, context_id: str) -> tuple[int, dict]:
    code = payload.get("error_code", "INTERNAL_ERROR")
    message = payload.get("message", "Gateway returned an error")
    status_code = 400
    status = "FAILED_PRECONDITION"
    reason = code
    if code in {"AUTH_FAILED"}:
        status_code = 401
        status = "UNAUTHENTICATED"
    elif code in {"UNKNOWN_SESSION", "UNKNOWN_CORR", "AGENT_NOT_FOUND"}:
        status_code = 404
        status = "NOT_FOUND"
    elif code in {"RATE_LIMITED", "QUEUE_FULL"}:
        status_code = 429
        status = "RESOURCE_EXHAUSTED"
    elif code in {"PROVIDER_ERROR", "INTERNAL_ERROR"}:
        status_code = 500
        status = "INTERNAL"
    return status_code, error_response(
        status_code=status_code,
        status=status,
        reason=reason,
        message=message,
        metadata={"taskId": task_id, "contextId": context_id},
    )
