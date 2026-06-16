# 06 — 协议说明

## 1. A2A_min_v1 协议定义

### 1.1 协议名称
A2A_min_v1 — Agent-to-Agent 最小可行协议第一版

### 1.2 设计原则
- **最小化**: 仅定义 Agent 通信所需的最小消息集合（8 种类型）
- **严格校验**: 信封 Schema 严格，拒绝未定义字段（`extra="forbid"`）
- **向后兼容**: 支持 CSD_Stream_v0 旧名称自动映射 (#32)
- **流式优先**: 原生支持流式传输，非流式为流式的特例
- **版本协商**: 仅接受 v1，拒绝未知版本 (#33)

---

## 2. 消息类型

### 2.1 INVOKE — 任务发起

Agent 向 Gateway 发起任务请求。

**Payload 必需字段**:
- `prompt` (str) 或 `messages` (list) — 至少提供其一
- `model` (str) — 目标模型名称

**Payload 可选字段**:
- `temperature` (float) — 采样温度（默认 0.7）
- `max_tokens` (int) — 最大输出 token 数（默认 2048）
- `stream` (bool) — 是否流式（默认 true）
- `task_type` (str) — 任务类型（用于能力路由 #26）

**状态转换**: Idle → Invoked

**校验规则** (envelope.py:92-96):
```python
if t == MessageType.INVOKE:
    if "prompt" not in p and "messages" not in p:
        raise ValueError("INVOKE payload must contain 'prompt' or 'messages'")
    if "model" not in p:
        raise ValueError("INVOKE payload must contain 'model'")
```

### 2.2 STREAM_CHUNK — 流式片段

Gateway 向 Agent 逐 token 返回生成内容。

**Payload 必需字段**:
- `content` (str) — 本次 token 内容

**信封必需**:
- `seq` (int) — 严格递增序号，从 1 开始

**状态转换**: Invoked → Streaming（首次），Streaming → Streaming（后续）

**校验规则** (envelope.py:98-102):
```python
elif t == MessageType.STREAM_CHUNK:
    if "content" not in p:
        raise ValueError("STREAM_CHUNK payload must contain 'content'")
    if self.seq is None:
        raise ValueError("STREAM_CHUNK must have a seq field")
```

### 2.3 STREAM_END — 流式结束

Gateway 通知 Agent 生成完成。

**Payload 字段**:
- `reason` (str) — 结束原因（"completed" / "stop" / "end_turn"）
- `total_tokens` (int) — 总 token 数

**状态转换**: Invoked/Streaming → Done

**校验规则**: seq 字段必需

### 2.4 CANCEL — 取消请求

Agent 请求取消正在执行的任务。

**Payload 可选字段**:
- `reason` (str) — 取消原因

**状态转换**: Invoked/Streaming → Cancelled

**幂等性**: 重复 CANCEL 返回 ALREADY_CANCELLED 而非报错。

**本地取消 vs 上游取消**:

Gateway 实现的是**本地取消**（local cancel），而非上游取消（upstream cancel）。具体差异：

| 维度 | 本地取消（当前实现） | 上游取消（未实现） |
|------|---------------------|-------------------|
| 机制 | Gateway 停止读取 Provider 流，将 session 状态置为 Cancelled | Gateway 向 Provider 发送取消信号，Provider 中断生成 |
| Provider 行为 | Provider 继续生成 token 直到自然结束，但 Gateway 不再转发 | Provider 立即停止生成，释放计算资源 |
| 资源释放 | Provider 侧资源在自然结束后释放 | Provider 侧资源立即释放 |
| 适用场景 | OpenAI/Anthropic/Ollama 等 API 不支持请求级取消 | 仅当 Provider API 支持 cancel 端点时可行 |
| 实现复杂度 | 低（仅修改 Gateway 状态） | 高（需要 Provider 侧配合） |

当前实现中，`handle_cancel` 将 `corr_id` 对应的 session 状态置为 `Cancelled`，`handle_invoke` 的流式循环在每次 chunk 前检查 `sm.state == SessionState.CANCELLED`，若已取消则 `break` 退出循环。后续到达的 Provider token 被丢弃，不再转发给 Agent。

Ollama 本地模型支持通过 `/api/abort` 端点取消正在进行的生成，但当前 Gateway 未实现此上游取消路径。如需实现，可在 `OllamaProviderAdapter` 中添加 `abort()` 方法，在 `handle_cancel` 时调用。

### 2.5 HEARTBEAT — 心跳

Agent 或 Gateway 发送心跳保活。

**状态行为**:
- Idle 状态：拒绝（返回错误）
- Invoked/Streaming 状态：接受，更新 `last_seen`
- 终态：被终态守卫拒绝

**实现** (main.py:432-457):
- 接收到 HEARTBEAT 后更新 `session_store.last_seen[session_id]`
- 若 session 不存在，自动创建（注册到 TimeoutChecker）
- 调用 `TimeoutChecker.on_heartbeat(session_id)` 刷新计时

### 2.6 ERROR — 错误通知

Gateway 或 Provider 返回错误。

**Payload 必需字段**:
- `error_code` (str) — 错误码（来自 28 码注册表）

**Payload 可选字段**:
- `message` (str) — 错误描述
- `recoverable` (bool) — 是否可恢复
- `retry_recommended` (bool) — 是否建议重试
- `source` (str) — 错误来源（gateway / provider / agent）

### 2.7 AGENT_DELEGATE — Agent 委派

Agent 将任务委派给另一个 Agent。

**Payload 必需字段**:
- `target_agent` (str) — 目标 Agent ID（与 `target_agents` 二选一）
- `task` (str) — 委派任务描述

**Payload 可选字段**:
- `pattern` (str) — 协调模式（"single" / "fan-out"）
- `target_agents` (list[str]) — fan-out 模式下的多个目标 Agent ID（替代 `target_agent`）
- `source_agent` (str) — 源 Agent ID
- `context` (dict) — 上下文数据

**校验规则** (envelope.py:118-122):
```python
elif t == MessageType.AGENT_DELEGATE:
    if "target_agent" not in p and "target_agents" not in p:
        raise ValueError("AGENT_DELEGATE payload must contain 'target_agent' or 'target_agents'")
    if "task" not in p:
        raise ValueError("AGENT_DELEGATE payload must contain 'task'")
```

### 2.8 AGENT_RESPONSE — Agent 响应

被委派的 Agent 返回任务结果。

**Payload 必需字段**:
- `delegation_id` (str) — 委派 ID
- `result` (str) — 任务结果

**Payload 可选字段**:
- `status` (str) — 状态（"completed" / "failed"）
- `source_agent` (str) — 响应 Agent ID

---

## 3. 错误码体系 (#2)

31 个注册错误码，覆盖三源（gateway / provider / agent），每个错误码包含 6 个属性：

| 属性 | 说明 |
|------|------|
| `code` | 错误码标识符 |
| `source` | 错误来源（gateway / provider / agent） |
| `trigger` | 触发条件描述 |
| `recoverable` | 是否可恢复（决定是否重试） |
| `retry_recommended` | 是否建议重试 |
| `description` | 返回给 Agent 的错误说明 |

按族分类：

| 族 | 错误码 | 来源 | 可恢复 |
|----|--------|------|--------|
| BAD_REQUEST | BAD_REQUEST, INVALID_VERSION, INVALID_MESSAGE_TYPE, INVALID_PAYLOAD | gateway | 否 |
| SESSION | UNKNOWN_SESSION, UNKNOWN_CORR | gateway | 否 |
| SEQ | SEQ_DUPLICATE, SEQ_GAP, SEQ_ROLLBACK | gateway | GAP 可恢复 |
| TIMEOUT | FIRST_TOKEN_TIMEOUT, TOKEN_INTERVAL_TIMEOUT, TOTAL_TASK_TIMEOUT, PROVIDER_RESPONSE_TIMEOUT | gateway/provider | 首 Token/间隔/Provider 可恢复 |
| PROVIDER | PROVIDER_ERROR, PROVIDER_AUTH_ERROR | provider | ERROR 可恢复 |
| CANCEL | CANCELLED, ALREADY_CANCELLED | agent/gateway | 否 |
| TERMINAL | MSG_AFTER_TERMINAL | gateway | 否 |
| IDEMPOTENCY | DUPLICATE_INVOKE, DUPLICATE_STREAM_END | gateway | 否 |
| HEARTBEAT | HEARTBEAT_RECEIVED | gateway | 否 |
| SECURITY | AUTH_FAILED, RATE_LIMITED, INPUT_TOO_LONG, OUTPUT_TOO_LONG, EMPTY_REQUEST | gateway | RATE_LIMITED 可恢复 |
| FLOW | QUEUE_FULL | gateway | 可恢复 |
| CONFIG | CONFIG_ERROR | gateway | 否 |
| MULTI_AGENT | AGENT_NOT_FOUND, DELEGATION_FAILED | gateway | DELEGATION_FAILED 可恢复 |
| INTERNAL | INTERNAL_ERROR | gateway | 可恢复 |

**可恢复性设计**：
- 可恢复错误（如 SEQ_GAP、TIMEOUT 类、PROVIDER_ERROR、RATE_LIMITED、QUEUE_FULL）会被 RetryManager 自动重试
- 不可恢复错误（如 BAD_REQUEST、AUTH_FAILED）立即返回给 Agent
- 重试策略：指数退避，默认最多 3 次，基础延迟 1s，最大延迟 30s

---

## 4. 双协议兼容 (#13)

Gateway 通过统一 ProviderAdapter 接口兼容 OpenAI-compatible 与 Anthropic-compatible 两类协议。运行时通过 `provider_type` 配置切换调用路径。

### 4.1 两类协议差异对照表

| 维度 | OpenAI-compatible | Anthropic-compatible |
|------|-------------------|----------------------|
| 请求端点 | `POST /v1/chat/completions` | `POST /v1/messages` |
| 认证方式 | `Authorization: Bearer sk-xxx` | `x-api-key: sk-ant-xxx` |
| 请求结构 | `{"model": "...", "messages": [{"role": "user", "content": "..."}]}` | `{"model": "...", "messages": [{"role": "user", "content": "..."}], "max_tokens": 1024}` |
| 必需字段 | model, messages | model, messages, max_tokens |
| 流式请求 | `stream: true` | `stream: true` |
| 流式返回格式 | `data: {"choices": [{"delta": {"content": "..."}}]}` | `event: content_block_delta` + `data: {"delta": {"text": "..."}}` |
| 流式结束标记 | `data: [DONE]` | `event: message_stop` |
| 错误返回 | `{"error": {"message": "...", "type": "...", "code": "..."}}` | `{"type": "error", "error": {"type": "...", "message": "..."}}` |
| 停止条件 | `finish_reason: "stop"` | `stop_reason: "end_turn"` |
| Token 用量位置 | `usage.prompt_tokens` / `usage.completion_tokens` | `usage.input_tokens` / `usage.output_tokens` |

### 4.2 Gateway 内部统一处理

两类协议在 Gateway 层统一为 A2A_min_v1 信封：

| Provider 返回 | A2A_min_v1 信封 | 实现位置 |
|---------------|----------------|----------|
| OpenAI `delta.content` | `STREAM_CHUNK.payload.content` | openai_provider.py:54-61 |
| Anthropic `delta.text` | `STREAM_CHUNK.payload.content` | anthropic_provider.py:65-75 |
| OpenAI `finish_reason: "stop"` | `STREAM_END.payload.reason="stop"` | openai_provider.py:63-69 |
| Anthropic `message_stop` | `STREAM_END.payload.reason="end_turn"` | anthropic_provider.py:77-82 |
| OpenAI 错误 | `ERROR.payload.error_code="PROVIDER_ERROR"` | openai_provider.py:79-84 |
| Anthropic 错误 | `ERROR.payload.error_code="PROVIDER_ERROR"` | anthropic_provider.py:84-97 |
| OpenAI 超时 | `ERROR.payload.error_code="PROVIDER_RESPONSE_TIMEOUT"` | openai_provider.py:72-77 |
| Anthropic 超时 | `ERROR.payload.error_code="PROVIDER_RESPONSE_TIMEOUT"` | anthropic_provider.py:88-92 |

### 4.3 运行时切换

通过 `.env` 配置切换调用路径，无需修改 Gateway 代码：

```env
# 使用 OpenAI-compatible Provider
PROVIDER1_TYPE=openai_compatible
PROVIDER1_ENDPOINT=https://api.deepseek.com/v1
PROVIDER1_API_KEY=sk-xxx
PROVIDER1_MODEL=deepseek-chat

# 使用 Anthropic-compatible Provider
PROVIDER2_TYPE=anthropic_compatible
PROVIDER2_ENDPOINT=https://api.anthropic.com
PROVIDER2_API_KEY=sk-ant-xxx
PROVIDER2_MODEL=claude-sonnet-4-6-20250514

# 使用 Ollama 本地 Provider (OpenAI-compatible 子集)
PROVIDER3_TYPE=ollama
PROVIDER3_ENDPOINT=http://localhost:11434/v1
PROVIDER3_MODEL=qwen2.5:0.5b
```

---

## 5. Legacy 协议兼容 (#32)

### 5.1 兼容规则

Gateway 在 `field_validator("type")` 阶段自动将 CSD_Stream_v0 旧名称映射为 A2A_min_v1 新名称：

| 旧名称 (CSD_Stream_v0) | 新名称 (A2A_min_v1) | 映射时机 |
|------------------------|---------------------|----------|
| TASK_START | INVOKE | field_validator 阶段 |
| CHUNK | STREAM_CHUNK | field_validator 阶段 |
| TASK_END | STREAM_END | field_validator 阶段 |
| STOP | CANCEL | field_validator 阶段 |
| PING | HEARTBEAT | field_validator 阶段 |
| FAIL | ERROR | field_validator 阶段 |

映射后，Gateway 内部只使用新名称处理，旧名称不再出现在任何后续逻辑中。未在映射表中的类型触发 `INVALID_MESSAGE_TYPE` 错误。

### 5.2 实现位置

- 映射表定义：`app/models/envelope.py:35-42` (`LEGACY_MESSAGE_MAP`)
- 映射逻辑：`app/models/envelope.py:69-84` (`normalize_type` validator)

---

## 6. 版本协商 (#33)

### 6.1 版本处理规则

| 输入 | 处理 | 返回 |
|------|------|------|
| `"v1"` | 接受 | 正常处理 |
| `"1"` | 归一化为 `"v1"` 后接受 | 正常处理 |
| `"v0"` | 拒绝 | `INVALID_VERSION` 错误 |
| `"v99"` | 拒绝 | `INVALID_VERSION` 错误 |

### 6.2 实现位置

- 版本归一化：`app/models/envelope.py:59-67` (`normalize_version` validator)

### 6.3 v0 → v1 转换规则

当前不支持 v0 版本。若需支持，转换规则如下：
- v0 信封字段名与新版本一致，但 type 使用 CSD_Stream_v0 旧名称
- 转换方式：将 type 字段通过 `LEGACY_MESSAGE_MAP` 映射即可
- 注意：v0 可能缺少 version 字段，需在 validator 中设置默认值

---

## 7. 官方 A2A 兼容层

### 7.1 定位

`A2A_min_v1` 是本课程项目内部执行协议，强调统一 Envelope、状态机、错误码、幂等和流式 token 管理。官方 A2A 兼容层是新增的 HTTP 边界适配层，目标是让外部客户端可以使用 Agent Card、`/message:send`、标准 `Task` 状态和 `application/a2a+json` 与本项目交互。

兼容层不重写核心执行逻辑，而是做以下映射：

| 官方 A2A 对象 | 内部对象 | 说明 |
| ------------- | -------- | ---- |
| `Message.parts[].text` | `Envelope.payload.prompt` | 目前主要支持文本 Part |
| `Message.contextId` | `Envelope.session_id` | 未提供时自动生成 |
| `Message.taskId` | `Envelope.corr_id` | 未提供时自动生成 |
| `metadata.model` | `Envelope.payload.model` | 未提供时使用网关默认模型 |
| `metadata.task_type` | `Envelope.payload.task_type` | 供 CapabilityRouter 使用 |
| `STREAM_CHUNK` | `TaskArtifactUpdateEvent` | 流式片段映射为 artifact 增量 |
| `STREAM_END` | `Task.status=COMPLETED` | 最终结果合并为 artifact |
| `ERROR` | 标准 A2A 错误或失败 Task | 根据错误类型决定 HTTP 错误或 Task 终态 |

### 7.2 Task 状态映射

| 内部状态 | 官方 `TaskState` |
| -------- | ---------------- |
| `Idle` | `SUBMITTED` |
| `Invoked` | `WORKING` |
| `Streaming` | `WORKING` |
| `Done` | `COMPLETED` |
| `Failed` | `FAILED` |
| `Cancelled` | `CANCELED` |

### 7.3 标准错误

兼容层返回 `application/a2a+json` 的标准错误对象，结构接近 `google.rpc.Status`：

- `code`：稳定错误码，如 `TASK_NOT_FOUND`、`UNSUPPORTED_OPERATION`。
- `message`：面向调用方的错误说明。
- `status`：HTTP/gRPC 风格状态，如 `NOT_FOUND`、`FAILED_PRECONDITION`。
- `details[].@type`：`type.googleapis.com/google.rpc.ErrorInfo`。
- `details[].metadata`：保留 task_id、source、recoverable、retry_recommended 等调试信息。

### 7.4 当前边界

- 当前 `TaskStore` 为进程内内存存储，服务重启后任务快照会丢失。
- `Part` 模型已经包含 text、raw、url、data，但执行链路目前主要支持文本输入输出。
- `/tasks/{id}:cancel` 对已完成任务返回 `UNSUPPORTED_OPERATION`；真正的上游 Provider 中断仍属于后续扩展。
- `pushNotifications` 暂未实现，Agent Card 中明确声明为 `false`。

---

## 8. MultiAgent 增强协议

### 8.1 协作模式

`AGENT_DELEGATE.payload.pattern` 支持以下值：

| pattern | 说明 |
| ------- | ---- |
| `single` | 单 Agent 委派，兼容原实现 |
| `fan-out` | 同一任务并发发给多个 Agent，返回子结果列表 |
| `fan-in` | 多个 Agent 并发执行后聚合为一个最终结果 |
| `pipeline` | 按步骤顺序执行，前一步结果作为后一步上下文 |
| `planner-worker-reviewer` / `pwr` | 内置规划-执行-审查协作流 |

### 8.2 AgentProfile.endpoint

`AgentProfile` 新增 `endpoint` 语义：当目标 Agent 存在 endpoint 时，Gateway 通过 HTTP POST 调用远端 Agent；否则使用本地 ProviderRouter。

HTTP 调用默认发送课程版 `INVOKE` Envelope：

```json
{
  "version": "v1",
  "type": "INVOKE",
  "session_id": "s1",
  "corr_id": "sub-xxxx",
  "payload": {
    "prompt": "sub task",
    "model": "mock-model",
    "task_type": "multi_agent"
  }
}
```

远端可返回：

- `{ "result": "..." }`
- 单个 Envelope
- `{ "chunks": [STREAM_CHUNK, STREAM_END] }`
- 官方 A2A `{ "task": ... }`

### 8.3 聚合策略

| aggregation | 说明 |
| ----------- | ---- |
| `json` | 原样返回子任务结果数组 |
| `concat` | 按 Agent 拼接成功结果 |
| `summary` | 返回成功/失败摘要；配置 `aggregator_agent` 时委托聚合 Agent 生成摘要 |

### 8.4 失败策略

| failure_policy | 行为 |
| -------------- | ---- |
| `partial` | 保留失败子任务，父任务状态为 `partial` |
| `fail_fast` | pipeline 等顺序流程遇到失败即停止 |
| `compensate` | 失败后尝试调用 `compensation_agent` 或使用 `fallback_result` |

补偿不会回滚已经完成的外部副作用，只会记录补偿结果并将被补偿子任务标记为 `compensated`。
