"""A2A_min_v1 structured error code table."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class ErrorCodeDef:
    code: str
    source: str          # "gateway" | "agent" | "provider"
    trigger: str         # human-readable trigger condition
    recoverable: bool
    retry_recommended: bool
    description: str     # message returned to agent


_ERROR_REGISTRY: Dict[str, ErrorCodeDef] = {}


def _reg(defn: ErrorCodeDef) -> ErrorCodeDef:
    _ERROR_REGISTRY[defn.code] = defn
    return defn


# ---- BAD REQUEST family ----
BAD_REQUEST = _reg(ErrorCodeDef(
    code="BAD_REQUEST",
    source="gateway",
    trigger="Envelope validation failed: missing/invalid fields",
    recoverable=False,
    retry_recommended=False,
    description="请求格式错误，请检查消息结构与字段",
))

INVALID_VERSION = _reg(ErrorCodeDef(
    code="INVALID_VERSION",
    source="gateway",
    trigger="version field is not a supported protocol version",
    recoverable=False,
    retry_recommended=False,
    description="不支持的协议版本",
))

INVALID_MESSAGE_TYPE = _reg(ErrorCodeDef(
    code="INVALID_MESSAGE_TYPE",
    source="gateway",
    trigger="type field is not a recognised message type",
    recoverable=False,
    retry_recommended=False,
    description="未知的消息类型",
))

INVALID_PAYLOAD = _reg(ErrorCodeDef(
    code="INVALID_PAYLOAD",
    source="gateway",
    trigger="Payload does not match the expected schema for its message type",
    recoverable=False,
    retry_recommended=False,
    description="消息体内容不合法",
))

# ---- SESSION / CORR family ----
UNKNOWN_SESSION = _reg(ErrorCodeDef(
    code="UNKNOWN_SESSION",
    source="gateway",
    trigger="session_id not found in active sessions",
    recoverable=False,
    retry_recommended=False,
    description="会话不存在",
))

UNKNOWN_CORR = _reg(ErrorCodeDef(
    code="UNKNOWN_CORR",
    source="gateway",
    trigger="corr_id not found",
    recoverable=False,
    retry_recommended=False,
    description="关联ID不存在",
))

# ---- SEQ family ----
SEQ_DUPLICATE = _reg(ErrorCodeDef(
    code="SEQ_DUPLICATE",
    source="gateway",
    trigger="STREAM_CHUNK seq already seen for this corr_id",
    recoverable=False,
    retry_recommended=False,
    description="seq序号重复",
))

SEQ_GAP = _reg(ErrorCodeDef(
    code="SEQ_GAP",
    source="gateway",
    trigger="STREAM_CHUNK seq skipped one or more values",
    recoverable=True,
    retry_recommended=True,
    description="seq序号跳号",
))

SEQ_ROLLBACK = _reg(ErrorCodeDef(
    code="SEQ_ROLLBACK",
    source="gateway",
    trigger="STREAM_CHUNK seq is less than the last seen seq",
    recoverable=False,
    retry_recommended=False,
    description="seq序号回退",
))

# ---- TIMEOUT family ----
FIRST_TOKEN_TIMEOUT = _reg(ErrorCodeDef(
    code="FIRST_TOKEN_TIMEOUT",
    source="gateway",
    trigger="No first token received within first_token_timeout",
    recoverable=True,
    retry_recommended=True,
    description="首token超时",
))

TOKEN_INTERVAL_TIMEOUT = _reg(ErrorCodeDef(
    code="TOKEN_INTERVAL_TIMEOUT",
    source="gateway",
    trigger="Time between consecutive tokens exceeded token_interval_timeout",
    recoverable=True,
    retry_recommended=True,
    description="token间隔超时",
))

TOTAL_TASK_TIMEOUT = _reg(ErrorCodeDef(
    code="TOTAL_TASK_TIMEOUT",
    source="gateway",
    trigger="Total task duration exceeded total_task_timeout",
    recoverable=False,
    retry_recommended=False,
    description="任务总超时",
))

PROVIDER_RESPONSE_TIMEOUT = _reg(ErrorCodeDef(
    code="PROVIDER_RESPONSE_TIMEOUT",
    source="provider",
    trigger="LLM Provider did not respond within provider_timeout",
    recoverable=True,
    retry_recommended=True,
    description="Provider响应超时",
))

# ---- PROVIDER family ----
PROVIDER_ERROR = _reg(ErrorCodeDef(
    code="PROVIDER_ERROR",
    source="provider",
    trigger="LLM Provider returned an error or unexpected response",
    recoverable=True,
    retry_recommended=True,
    description="Provider返回错误",
))

PROVIDER_AUTH_ERROR = _reg(ErrorCodeDef(
    code="PROVIDER_AUTH_ERROR",
    source="provider",
    trigger="LLM Provider authentication failed (invalid API key)",
    recoverable=False,
    retry_recommended=False,
    description="Provider认证失败",
))

# ---- CANCEL family ----
CANCELLED = _reg(ErrorCodeDef(
    code="CANCELLED",
    source="agent",
    trigger="Agent sent CANCEL for this corr_id",
    recoverable=False,
    retry_recommended=False,
    description="任务已被取消",
))

ALREADY_CANCELLED = _reg(ErrorCodeDef(
    code="ALREADY_CANCELLED",
    source="gateway",
    trigger="CANCEL received for a task already in Cancelled state",
    recoverable=False,
    retry_recommended=False,
    description="任务已取消，无需重复取消",
))

ALREADY_CANCELLED = _reg(ErrorCodeDef(
    code="ALREADY_CANCELLED",
    source="gateway",
    trigger="CANCEL received for a task already in Cancelled state",
    recoverable=False,
    retry_recommended=False,
    description="任务已取消，无需重复取消",
))

# ---- TERMINAL STATE family ----
MSG_AFTER_TERMINAL = _reg(ErrorCodeDef(
    code="MSG_AFTER_TERMINAL",
    source="gateway",
    trigger="Message received after task reached terminal state",
    recoverable=False,
    retry_recommended=False,
    description="任务已终态，后续消息被拒绝",
))

# ---- IDEMPOTENCY family ----
DUPLICATE_INVOKE = _reg(ErrorCodeDef(
    code="DUPLICATE_INVOKE",
    source="gateway",
    trigger="INVOKE with duplicate corr_id while task is still active",
    recoverable=False,
    retry_recommended=False,
    description="重复INVOKE，任务已在执行中",
))

DUPLICATE_STREAM_END = _reg(ErrorCodeDef(
    code="DUPLICATE_STREAM_END",
    source="gateway",
    trigger="STREAM_END with corr_id already in terminal state",
    recoverable=False,
    retry_recommended=False,
    description="重复STREAM_END",
))

# ---- HEARTBEAT family ----
HEARTBEAT_RECEIVED = _reg(ErrorCodeDef(
    code="HEARTBEAT_RECEIVED",
    source="gateway",
    trigger="Heartbeat received and processed",
    recoverable=False,
    retry_recommended=False,
    description="心跳已收到",
))

# ---- SECURITY family ----
AUTH_FAILED = _reg(ErrorCodeDef(
    code="AUTH_FAILED",
    source="gateway",
    trigger="API key or agent identity validation failed",
    recoverable=False,
    retry_recommended=False,
    description="认证失败",
))

RATE_LIMITED = _reg(ErrorCodeDef(
    code="RATE_LIMITED",
    source="gateway",
    trigger="Request rate exceeded configured limit",
    recoverable=True,
    retry_recommended=True,
    description="请求频率超限",
))

INPUT_TOO_LONG = _reg(ErrorCodeDef(
    code="INPUT_TOO_LONG",
    source="gateway",
    trigger="Input exceeds configured max length",
    recoverable=False,
    retry_recommended=False,
    description="输入过长",
))

OUTPUT_TOO_LONG = _reg(ErrorCodeDef(
    code="OUTPUT_TOO_LONG",
    source="gateway",
    trigger="Output exceeds configured max length",
    recoverable=False,
    retry_recommended=False,
    description="输出过长",
))

EMPTY_REQUEST = _reg(ErrorCodeDef(
    code="EMPTY_REQUEST",
    source="gateway",
    trigger="Request body is empty or contains no content",
    recoverable=False,
    retry_recommended=False,
    description="请求内容为空",
))

# ---- FLOW CONTROL family ----
QUEUE_FULL = _reg(ErrorCodeDef(
    code="QUEUE_FULL",
    source="gateway",
    trigger="Internal buffer queue has reached max capacity",
    recoverable=True,
    retry_recommended=True,
    description="队列已满，请稍后重试",
))

# ---- CONFIG family ----
CONFIG_ERROR = _reg(ErrorCodeDef(
    code="CONFIG_ERROR",
    source="gateway",
    trigger="Missing or invalid configuration parameter",
    recoverable=False,
    retry_recommended=False,
    description="配置错误",
))

# ---- INTERNAL family ----
INTERNAL_ERROR = _reg(ErrorCodeDef(
    code="INTERNAL_ERROR",
    source="gateway",
    trigger="Unexpected internal gateway error",
    recoverable=True,
    retry_recommended=True,
    description="内部错误",
))


def get_error_def(code: str) -> ErrorCodeDef:
    """Look up error definition; returns INTERNAL_ERROR if unknown."""
    return _ERROR_REGISTRY.get(code, INTERNAL_ERROR)


def all_error_codes() -> Dict[str, ErrorCodeDef]:
    """Return the full error code registry."""
    return dict(_ERROR_REGISTRY)
