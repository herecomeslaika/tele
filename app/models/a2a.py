"""Official A2A HTTP+JSON compatible data models.

These models intentionally cover the subset needed by this gateway's REST
compatibility layer while keeping field names aligned with the official JSON
shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


A2A_MEDIA_TYPE = "application/a2a+json"
A2A_VERSION = "1.0"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class A2ABaseModel(BaseModel):
    model_config = {"extra": "forbid"}


class TaskState(str, Enum):
    TASK_STATE_UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    TASK_STATE_SUBMITTED = "TASK_STATE_SUBMITTED"
    TASK_STATE_WORKING = "TASK_STATE_WORKING"
    TASK_STATE_COMPLETED = "TASK_STATE_COMPLETED"
    TASK_STATE_FAILED = "TASK_STATE_FAILED"
    TASK_STATE_CANCELED = "TASK_STATE_CANCELED"
    TASK_STATE_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    TASK_STATE_REJECTED = "TASK_STATE_REJECTED"
    TASK_STATE_AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"


class Role(str, Enum):
    ROLE_UNSPECIFIED = "ROLE_UNSPECIFIED"
    ROLE_USER = "ROLE_USER"
    ROLE_AGENT = "ROLE_AGENT"


class Part(A2ABaseModel):
    text: Optional[str] = None
    raw: Optional[str] = None
    url: Optional[str] = None
    data: Any = None
    metadata: Optional[dict[str, Any]] = None
    filename: Optional[str] = None
    mediaType: Optional[str] = None

    @model_validator(mode="after")
    def validate_one_content(self) -> "Part":
        present = [
            self.text is not None,
            self.raw is not None,
            self.url is not None,
            self.data is not None,
        ]
        if sum(present) != 1:
            raise ValueError("Part must contain exactly one of text, raw, url, data")
        return self


class Message(A2ABaseModel):
    messageId: str
    role: Role
    parts: list[Part] = Field(..., min_length=1)
    contextId: Optional[str] = None
    taskId: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    extensions: Optional[list[str]] = None
    referenceTaskIds: Optional[list[str]] = None


class TaskStatus(A2ABaseModel):
    state: TaskState
    message: Optional[Message] = None
    timestamp: Optional[str] = Field(default_factory=utc_now_iso)


class Artifact(A2ABaseModel):
    artifactId: str
    parts: list[Part] = Field(..., min_length=1)
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    extensions: Optional[list[str]] = None


class Task(A2ABaseModel):
    id: str
    status: TaskStatus
    contextId: Optional[str] = None
    artifacts: Optional[list[Artifact]] = None
    history: Optional[list[Message]] = None
    metadata: Optional[dict[str, Any]] = None


class TaskStatusUpdateEvent(A2ABaseModel):
    taskId: str
    contextId: str
    status: TaskStatus
    metadata: Optional[dict[str, Any]] = None


class TaskArtifactUpdateEvent(A2ABaseModel):
    taskId: str
    contextId: str
    artifact: Artifact
    append: Optional[bool] = None
    lastChunk: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None


class StreamResponse(A2ABaseModel):
    task: Optional[Task] = None
    message: Optional[Message] = None
    statusUpdate: Optional[TaskStatusUpdateEvent] = None
    artifactUpdate: Optional[TaskArtifactUpdateEvent] = None

    @model_validator(mode="after")
    def validate_one_payload(self) -> "StreamResponse":
        present = [
            self.task is not None,
            self.message is not None,
            self.statusUpdate is not None,
            self.artifactUpdate is not None,
        ]
        if sum(present) != 1:
            raise ValueError("StreamResponse must contain exactly one payload field")
        return self


class SendMessageConfiguration(A2ABaseModel):
    acceptedOutputModes: Optional[list[str]] = None
    blocking: Optional[bool] = None
    historyLength: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None


class SendMessageRequest(A2ABaseModel):
    message: Message
    configuration: Optional[SendMessageConfiguration] = None
    metadata: Optional[dict[str, Any]] = None
    model: Optional[str] = None
    taskType: Optional[str] = None


class AgentProvider(A2ABaseModel):
    url: str
    organization: str


class AgentCapabilities(A2ABaseModel):
    streaming: bool = True
    pushNotifications: bool = False
    extendedAgentCard: bool = False
    extensions: Optional[list[dict[str, Any]]] = None


class AgentSkill(A2ABaseModel):
    id: str
    name: str
    description: str
    tags: list[str]
    examples: Optional[list[str]] = None
    inputModes: Optional[list[str]] = None
    outputModes: Optional[list[str]] = None
    securityRequirements: Optional[list[dict[str, list[str]]]] = None


class AgentInterface(A2ABaseModel):
    url: str
    protocolBinding: str
    tenant: Optional[str] = None


class APIKeySecurityScheme(A2ABaseModel):
    location: str = "header"
    name: str = "X-API-Key"
    description: Optional[str] = None


class SecurityScheme(A2ABaseModel):
    apiKeySecurityScheme: Optional[APIKeySecurityScheme] = None
    httpAuthSecurityScheme: Optional[dict[str, Any]] = None
    oauth2SecurityScheme: Optional[dict[str, Any]] = None
    openIdConnectSecurityScheme: Optional[dict[str, Any]] = None
    mtlsSecurityScheme: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_one_scheme(self) -> "SecurityScheme":
        present = [
            self.apiKeySecurityScheme is not None,
            self.httpAuthSecurityScheme is not None,
            self.oauth2SecurityScheme is not None,
            self.openIdConnectSecurityScheme is not None,
            self.mtlsSecurityScheme is not None,
        ]
        if sum(present) != 1:
            raise ValueError("SecurityScheme must contain exactly one scheme")
        return self


class AgentCard(A2ABaseModel):
    name: str
    description: str
    supportedInterfaces: list[AgentInterface]
    version: str
    capabilities: AgentCapabilities
    defaultInputModes: list[str]
    defaultOutputModes: list[str]
    skills: list[AgentSkill]
    provider: Optional[AgentProvider] = None
    documentationUrl: Optional[str] = None
    securitySchemes: Optional[dict[str, SecurityScheme]] = None
    securityRequirements: Optional[list[dict[str, list[str]]]] = None
    signatures: Optional[list[dict[str, Any]]] = None
    iconUrl: Optional[str] = None


class ErrorInfo(A2ABaseModel):
    type_: str = Field(default="type.googleapis.com/google.rpc.ErrorInfo", alias="@type")
    reason: str
    domain: str = "a2a-protocol.org"
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2AErrorBody(A2ABaseModel):
    code: int
    status: str
    message: str
    details: list[ErrorInfo] = Field(default_factory=list)


class A2AErrorResponse(A2ABaseModel):
    error: A2AErrorBody
