# 06 — 协议说明

## 1. A2A_min_v1 协议定义

### 1.1 协议名称
A2A_min_v1 — Agent-to-Agent 最小可行协议第一版

### 1.2 设计原则
- **最小化**: 仅定义 Agent 通信所需的最小消息集合
- **严格校验**: 信封 Schema 严格，拒绝未定义字段
- **向后兼容**: 支持 CSD_Stream_v0 旧名称自动映射
- **流式优先**: 原生支持流式传输，非流式为流式的特例

---

## 2. 消息类型

### 2.1 INVOKE — 任务发起

Agent 向 Gateway 发起任务请求。

**Payload 必需字段**:
- `prompt` (str) 或 `messages` (list) — 至少提供其一
- `model` (str) — 目标模型名称

**Payload 可选字段**:
- `temperature` (float) — 采样温度
- `max_tokens` (int) — 最大输出 token 数
- `stream` (bool) — 是否流式（默认 true）
- `task_type` (str) — 任务类型（用于能力路由）

**状态转换**: Idle → Invoked

### 2.2 STREAM_CHUNK — 流式片段

Gateway 向 Agent 逐 token 返回生成内容。

**Payload 必需字段**:
- `content` (str) — 本次 token 内容

**信封必需**:
- `seq` (int) — 严格递增序号，从 1 开始

**状态转换**: Invoked → Streaming（首次），Streaming → Streaming（后续）

### 2.3 STREAM_END — 流式结束

Gateway 通知 Agent 生成完成。

**Payload 字段**:
- `reason` (str) — 结束原因（"completed" / "stop" / "end_turn"）
- `total_tokens` (int) — 总 token 数

**状态转换**: Invoked/Streaming → Done

### 2.4 CANCEL — 取消请求

Agent 请求取消正在执行的任务。

**Payload 可选字段**:
- `reason` (str) — 取消原因

**状态转换**: Invoked/Streaming → Cancelled

**幂等性**: 重复 CANCEL 返回 ALREADY_CANCELLED 而非报错。

### 2.5 HEARTBEAT — 心跳

Agent 或 Gateway 发送心跳保活。

**状态行为**:
- Idle 状态：拒绝（返回错误）
- Invoked/Streaming 状态：接受，更新 last_seen
- 终态：被终态守卫拒绝

### 2.6 ERROR — 错误通知

Gateway 或 Provider 返回错误。

**Payload 必需字段**:
- `error_code` (str) — 错误码（来自 29 码注册表）

**Payload 可选字段**:
- `message` (str) — 错误描述
- `recoverable` (bool) — 是否可恢复
- `retry_recommended` (bool) — 是否建议重试
- `source` (str) — 错误来源（gateway / provider / agent）

### 2.7 AGENT_DELEGATE — Agent 委派

Agent 将任务委派给另一个 Agent。

**Payload 必需字段**:
- `target_agent` (str) — 目标 Agent ID
- `task` (str) — 委派任务描述

**Payload 可选字段**:
- `pattern` (str) — 协调模式（"single" / "fan-out" / "fan-in" / "pipeline"）
- `source_agent` (str) — 源 Agent ID
- `context` (dict) — 上下文数据

### 2.8 AGENT_RESPONSE — Agent 响应

被委派的 Agent 返回任务结果。

**Payload 必需字段**:
- `delegation_id` (str) — 委派 ID
- `result` (str) — 任务结果

**Payload 可选字段**:
- `status` (str) — 状态（"completed" / "failed"）
- `source_agent` (str) — 响应 Agent ID

---

## 3. 错误码体系

29 个注册错误码，覆盖三源（gateway / provider / agent）：

| 族 | 错误码 | 可恢复 |
|----|--------|--------|
| BAD_REQUEST | BAD_REQUEST, INVALID_VERSION, INVALID_MESSAGE_TYPE, INVALID_PAYLOAD | 否 |
| SESSION | UNKNOWN_SESSION, UNKNOWN_CORR | 否 |
| SEQ | SEQ_DUPLICATE, SEQ_GAP, SEQ_ROLLBACK | GAP 可恢复 |
| TIMEOUT | FIRST_TOKEN_TIMEOUT, TOKEN_INTERVAL_TIMEOUT, TOTAL_TASK_TIMEOUT, PROVIDER_RESPONSE_TIMEOUT | 首 Token/间隔/Provider 可恢复 |
| PROVIDER | PROVIDER_ERROR, PROVIDER_AUTH_ERROR | ERROR 可恢复 |
| CANCEL | CANCELLED, ALREADY_CANCELLED | 否 |
| TERMINAL | MSG_AFTER_TERMINAL | 否 |
| IDEMPOTENCY | DUPLICATE_INVOKE, DUPLICATE_STREAM_END | 否 |
| HEARTBEAT | HEARTBEAT_RECEIVED | 否 |
| SECURITY | AUTH_FAILED, RATE_LIMITED, INPUT_TOO_LONG, OUTPUT_TOO_LONG, EMPTY_REQUEST | RATE_LIMITED 可恢复 |
| FLOW | QUEUE_FULL | 可恢复 |
| CONFIG | CONFIG_ERROR | 否 |
| MULTI_AGENT | AGENT_NOT_FOUND, DELEGATION_FAILED | DELEGATION_FAILED 可恢复 |
| INTERNAL | INTERNAL_ERROR | 可恢复 |

---

## 4. 双协议兼容

Gateway 通过统一 ProviderAdapter 接口兼容 OpenAI-compatible 与 Anthropic-compatible 两类协议。

### 4.1 协议差异

| 维度 | OpenAI-compatible | Anthropic-compatible |
|------|-------------------|----------------------|
| 请求端点 | `POST /v1/chat/completions` | `POST /v1/messages` |
| 认证方式 | `Authorization: Bearer sk-xxx` | `x-api-key: sk-ant-xxx` |
| 请求结构 | `{model, messages}` | `{model, messages, max_tokens}` |
| 流式返回 | `data: {choices:[{delta:{content:"..."}}]}` | `event: content_block_delta` + `data: {delta:{text:"..."}}` |
| 流式结束 | `data: [DONE]` | `event: message_stop` |
| 错误格式 | `{error:{message,type,code}}` | `{type:"error",error:{type,message}}` |

### 4.2 Gateway 统一映射

- OpenAI `delta.content` → `STREAM_CHUNK.payload.content`
- Anthropic `delta.text` → `STREAM_CHUNK.payload.content`
- OpenAI `[DONE]` → `STREAM_END.payload.reason="stop"`
- Anthropic `message_stop` → `STREAM_END.payload.reason="end_turn"`
- 两类错误均转换为 `ERROR.payload.error_code="PROVIDER_ERROR"`

### 4.3 运行时切换

通过 `.env` 配置 `PROVIDER1_TYPE=openai_compatible` 或 `PROVIDER1_TYPE=anthropic_compatible` 切换调用路径，无需修改 Gateway 代码。
