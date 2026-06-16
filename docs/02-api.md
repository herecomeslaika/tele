# 02 — API 接口说明

## 1. REST 端点

### 1.1 POST /invoke — 同步调用

发送 INVOKE 消息，等待完整响应返回（非流式）。

**请求头**：

| 头部 | 必需 | 说明 |
|------|------|------|
| Content-Type | 是 | application/json |
| X-API-Key | 安全开启时 | API 认证密钥 |
| X-Agent-ID | 安全开启时 | Agent 身份标识 |

**请求体**（A2A_min_v1 统一信封）：

```json
{
  "version": "v1",
  "type": "INVOKE",
  "session_id": "sess-001",
  "corr_id": "corr-001",
  "payload": {
    "prompt": "你好，请介绍一下自己",
    "model": "deepseek-chat",
    "temperature": 0.7,
    "max_tokens": 2048,
    "stream": false,
    "task_type": "chat"
  }
}
```

**INVOKE Payload 字段**：

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| prompt | string | 与 messages 二选一 | — | 文本提示 |
| messages | array | 与 prompt 二选一 | — | 对话历史 `[{role, content}]` |
| model | string | 是 | — | 目标模型名称 |
| temperature | float | 否 | 0.7 | 采样温度 |
| max_tokens | int | 否 | 2048 | 最大输出 token 数 |
| stream | bool | 否 | true | 是否流式（/invoke 端点忽略此字段） |
| task_type | string | 否 | — | 任务类型，用于能力路由 |

**响应**：包含完整 chunks 数组的 JSON。

成功时返回所有 STREAM_CHUNK + STREAM_END 的集合：

```json
{
  "chunks": [
    {"version": "v1", "type": "STREAM_CHUNK", "session_id": "sess-001", "corr_id": "corr-001", "seq": 1, "payload": {"content": "你"}},
    {"version": "v1", "type": "STREAM_CHUNK", "session_id": "sess-001", "corr_id": "corr-001", "seq": 2, "payload": {"content": "好"}},
    {"version": "v1", "type": "STREAM_END", "session_id": "sess-001", "corr_id": "corr-001", "seq": 2, "payload": {"reason": "stop", "total_tokens": 2}}
  ]
}
```

错误时返回 ERROR 信封：

```json
{
  "version": "v1",
  "type": "ERROR",
  "session_id": "sess-001",
  "corr_id": "corr-001",
  "payload": {
    "error_code": "AUTH_FAILED",
    "message": "认证失败",
    "recoverable": false,
    "retry_recommended": false,
    "source": "gateway"
  }
}
```

---

### 1.2 POST /stream — SSE 流式调用

发送 INVOKE 消息，以 Server-Sent Events 流式返回 STREAM_CHUNK。

**请求**：

```bash
curl -X POST http://localhost:8000/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "version": "v1",
    "type": "INVOKE",
    "session_id": "sess-002",
    "corr_id": "corr-002",
    "payload": {
      "prompt": "写一首诗",
      "model": "deepseek-chat"
    }
  }'
```

**响应**：SSE 流，每个事件格式为 `data: {json}\n\n`：

```
data: {"version":"v1","type":"STREAM_CHUNK","session_id":"sess-002","corr_id":"corr-002","seq":1,"payload":{"content":"春"}}

data: {"version":"v1","type":"STREAM_CHUNK","session_id":"sess-002","corr_id":"corr-002","seq":2,"payload":{"content":"风"}}

data: {"version":"v1","type":"STREAM_END","session_id":"sess-002","corr_id":"corr-002","seq":2,"payload":{"reason":"stop","total_tokens":2}}
```

---

### 1.3 WebSocket /ws — 双向通信

WebSocket 端点，支持双向 A2A 消息收发。

```python
import websockets, json, asyncio

async def ws_client():
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        # 发送 INVOKE
        await ws.send(json.dumps({
            "version": "v1", "type": "INVOKE",
            "session_id": "sess-003", "corr_id": "corr-003",
            "payload": {"prompt": "hello", "model": "mock-model"}
        }))

        # 接收 STREAM_CHUNK + STREAM_END
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if data["type"] == "STREAM_END":
                break
            if data["type"] == "STREAM_CHUNK":
                print(data["payload"].get("content", ""), end="")

        # 发送 CANCEL（另起一个 corr_id）
        await ws.send(json.dumps({
            "version": "v1", "type": "CANCEL",
            "session_id": "sess-003", "corr_id": "corr-004",
            "payload": {"reason": "user requested"}
        }))
        resp = json.loads(await ws.recv())
        print(f"Cancel response: {resp}")
```

**WebSocket 消息流示例**：

```
Client → Server:  {"type": "INVOKE", ...}
Server → Client:  {"type": "STREAM_CHUNK", "seq": 1, ...}
Server → Client:  {"type": "STREAM_CHUNK", "seq": 2, ...}
Server → Client:  {"type": "STREAM_END", ...}
Client → Server:  {"type": "HEARTBEAT", ...}
Server → Client:  {"type": "HEARTBEAT", ...}
```

---

### 1.4 POST /cancel — 取消任务

```bash
curl -X POST http://localhost:8000/cancel \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "version": "v1", "type": "CANCEL",
    "session_id": "sess-001", "corr_id": "corr-001",
    "payload": {"reason": "user requested"}
  }'
```

**CANCEL Payload 字段**：

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| reason | string | 否 | 取消原因 |

**响应**：

成功取消：
```json
{"version":"v1","type":"ERROR","session_id":"sess-001","corr_id":"corr-001","payload":{"error_code":"CANCELLED","message":"任务已取消","source":"gateway"}}
```

重复取消：
```json
{"version":"v1","type":"ERROR","session_id":"sess-001","corr_id":"corr-001","payload":{"error_code":"ALREADY_CANCELLED","message":"任务已取消，无需重复取消"}}
```

终态后取消：
```json
{"version":"v1","type":"ERROR","session_id":"sess-001","corr_id":"corr-001","payload":{"error_code":"MSG_AFTER_TERMINAL","message":"event 'CANCEL' rejected: session in terminal state 'Done'"}}
```

---

### 1.5 POST /heartbeat — 心跳

```bash
curl -X POST http://localhost:8000/heartbeat \
  -H "Content-Type: application/json" \
  -d '{
    "version": "v1", "type": "HEARTBEAT",
    "session_id": "sess-001", "corr_id": "corr-001",
    "payload": {}
  }'
```

**响应**：

```json
{"version":"v1","type":"HEARTBEAT","session_id":"sess-001","corr_id":"corr-001","payload":{"status":"alive","last_seen":1716712345.678}}
```

心跳会更新 `last_seen` 字段，超时检查器据此判断会话是否存活。

---

### 1.6 GET /health — 健康检查

```bash
curl http://localhost:8000/health
# {"status": "ok", "providers": 3}
```

---

### 1.7 GET /metrics — 指标查询

```bash
curl http://localhost:8000/metrics
```

返回字段：

| 字段 | 说明 |
|------|------|
| request_count | 总请求数 |
| success_count | 成功数 |
| failure_count | 失败数 |
| cancel_count | 取消数 |
| timeout_count | 超时数 |
| active_sessions | 活跃会话数 |
| avg_first_token_latency_ms | 平均首 Token 延迟 |
| avg_total_duration_ms | 平均总耗时 |
| p95_first_token_latency_ms | P95 首 Token 延迟 |

---

### 1.8 GET /error-codes — 错误码列表

```bash
curl http://localhost:8000/error-codes
```

返回 31 个注册错误码的完整定义，包含 `code`、`source`、`trigger`、`recoverable`、`retry_recommended`、`description`。

---

### 1.9 GET /audit/{corr_id} — 审计查询

```bash
curl http://localhost:8000/audit/corr-001
```

返回指定 corr_id 的所有审计记录，包含 `session_id`、`corr_id`、`event`、`timestamp`、`model`、`provider`、`duration_ms`、`error_code`、`trace_id` 等字段。

---

## 2. Multi-Agent 端点

### 2.1 GET /agents — 列出所有 Agent

```bash
curl http://localhost:8000/agents
```

**响应**：
```json
[
  {
    "agent_id": "agent-001",
    "name": "translator",
    "roles": ["worker"],
    "capabilities": ["translation", "nlp"],
    "status": "online",
    "current_tasks": 0,
    "max_concurrent_tasks": 5
  }
]
```

### 2.2 GET /agents/{agent_id} — 查询单个 Agent

```bash
curl http://localhost:8000/agents/agent-001
```

### 2.3 POST /agents/register — 注册 Agent

```bash
curl -X POST http://localhost:8000/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent-002",
    "name": "coder",
    "roles": ["worker"],
    "capabilities": ["code-generation", "python"]
  }'
```

注册时 SecurityManager 自动为 Agent 生成 API Key。

### 2.4 POST /delegate/fan-out — 并发委派多个 Agent

```bash
curl -X POST http://localhost:8000/delegate/fan-out \
  -H "Content-Type: application/json" \
  -d '{
    "target_agents": ["agent-001", "agent-002"],
    "task": "翻译以下文本为英文：你好世界",
    "source_agent": "agent-000",
    "model": "mock-model"
  }'
```

**响应**：包含 `sub_count` 和聚合 `result` 的 AGENT_RESPONSE。

### 2.5 GET /delegations — 列出所有委派记录

```bash
curl http://localhost:8000/delegations
```

---

## 3. Agent 委派消息

### 3.1 AGENT_DELEGATE

通过 WebSocket 或 /invoke 端点发送：

**单对单委派**：

```json
{
  "version": "v1",
  "type": "AGENT_DELEGATE",
  "session_id": "sess-010",
  "corr_id": "corr-010",
  "payload": {
    "target_agent": "agent-001",
    "task": "翻译以下文本为英文：你好世界",
    "pattern": "single",
    "source_agent": "agent-000"
  }
}
```

**AGENT_DELEGATE Payload 字段**：

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| target_agent | string | 与 target_agents 二选一 | 目标 Agent ID |
| target_agents | list[str] | 与 target_agent 二选一 | fan-out 模式多目标 |
| task | string | 是 | 委派任务描述 |
| pattern | string | 否 | 协调模式（"single" / "fan-out"） |
| source_agent | string | 否 | 源 Agent ID |
| context | dict | 否 | 上下文数据 |

**Fan-out 并发委派**：

```json
{
  "version": "v1",
  "type": "AGENT_DELEGATE",
  "session_id": "sess-011",
  "corr_id": "corr-011",
  "payload": {
    "target_agents": ["agent-001", "agent-002"],
    "task": "审查以下代码的安全漏洞",
    "pattern": "fan-out",
    "source_agent": "agent-000"
  }
}
```

### 3.2 AGENT_RESPONSE

```json
{
  "version": "v1",
  "type": "AGENT_RESPONSE",
  "session_id": "sess-010",
  "corr_id": "corr-010",
  "payload": {
    "delegation_id": "del-abc123",
    "result": "Hello World",
    "status": "completed",
    "source_agent": "agent-001"
  }
}
```

**AGENT_RESPONSE Payload 字段**：

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| delegation_id | string | 是 | 委派 ID |
| result | string | 是 | 任务结果 |
| status | string | 否 | 状态（"completed" / "failed"） |
| source_agent | string | 否 | 响应 Agent ID |

---

## 4. 错误响应格式

所有错误以 `type: ERROR` 信封返回：

```json
{
  "version": "v1",
  "type": "ERROR",
  "session_id": "sess-001",
  "corr_id": "corr-001",
  "payload": {
    "error_code": "PROVIDER_ERROR",
    "message": "Provider returned an error",
    "recoverable": true,
    "retry_recommended": true,
    "source": "provider"
  }
}
```

**ERROR Payload 字段**：

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| error_code | string | 是 | 错误码（来自 28 码注册表） |
| message | string | 否 | 错误描述 |
| recoverable | bool | 否 | 是否可恢复 |
| retry_recommended | bool | 否 | 是否建议重试 |
| source | string | 否 | 错误来源（gateway / provider / agent） |

---

## 5. Legacy 协议兼容请求

Gateway 同时接受 CSD_Stream_v0 旧名称，自动映射为 A2A_min_v1 新名称：

```bash
# 使用旧名称 TASK_START 等价于 INVOKE
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "version": "v1", "type": "TASK_START",
    "session_id": "sess-001", "corr_id": "corr-001",
    "payload": {"prompt": "hello", "model": "deepseek-chat"}
  }'
```

映射表：TASK_START→INVOKE, CHUNK→STREAM_CHUNK, TASK_END→STREAM_END, STOP→CANCEL, PING→HEARTBEAT, FAIL→ERROR。

未知类型返回 `INVALID_MESSAGE_TYPE` 错误。

---

## 6. 官方 A2A HTTP+JSON 兼容端点

这一组端点用于对接官方 A2A HTTP+JSON 风格客户端。它们不会替代课程版 `A2A_min_v1` 接口，而是在 HTTP 边界把官方 `Message` / `Task` / `Part` / `Artifact` 转换为内部 Envelope，再复用原网关执行链路。

所有 JSON 响应使用 `application/a2a+json`，并返回 `A2A-Version: 1.0`。

| 端点 | 方法 | 响应模型 | 说明 |
| ---- | ---- | -------- | ---- |
| `/.well-known/agent-card.json` | GET | `AgentCard` | 公开能力发现 |
| `/extendedAgentCard` | GET | `AgentCard` 或标准错误 | 扩展能力卡；未配置时返回标准错误 |
| `/message:send` | POST | `Task` | 同步执行，返回最终任务快照 |
| `/message:stream` | POST | SSE `StreamResponse` | 流式执行，返回状态和 artifact 增量 |
| `/tasks/{task_id}` | GET | `Task` | 查询单个任务 |
| `/tasks` | GET | `Task[]` | 查询当前内存任务列表 |
| `/tasks/{task_id}:cancel` | POST | `Task` 或标准错误 | 取消任务 |
| `/tasks/{task_id}:subscribe` | POST | SSE `StreamResponse` | 订阅非终态任务 |

### 6.1 Agent Card

```bash
curl http://localhost:8000/.well-known/agent-card.json
```

关键字段：

- `protocolVersion`: `1.0`
- `preferredTransport`: `HTTP+JSON`
- `url`: 网关基地址
- `capabilities.streaming`: `true`
- `defaultInputModes` / `defaultOutputModes`: `text/plain`
- `skills`: 至少包含 `chat` 和 `multi_agent_delegate`

### 6.2 POST /message:send

```bash
curl -X POST http://localhost:8000/message:send \
  -H "Content-Type: application/a2a+json" \
  -d '{
    "message": {
      "messageId": "msg-001",
      "role": "ROLE_USER",
      "parts": [
        {"text": "你好，请用一句话介绍这个网关"}
      ]
    },
    "configuration": {
      "acceptedOutputModes": ["text/plain"]
    },
    "metadata": {
      "model": "mock-model",
      "task_type": "chat"
    }
  }'
```

响应为标准 `Task`。其中 `id` 对应内部 `corr_id`，`contextId` 对应内部 `session_id`，完成后的文本结果放入 `artifacts[].parts[].text`。

### 6.3 POST /message:stream

```bash
curl -N -X POST http://localhost:8000/message:stream \
  -H "Content-Type: application/a2a+json" \
  -d '{
    "message": {
      "messageId": "msg-002",
      "role": "ROLE_USER",
      "parts": [{"text": "写三句话说明 A2A 兼容层"}]
    },
    "metadata": {"model": "mock-model"}
  }'
```

SSE 中每条 `data:` 都是 `StreamResponse`，可能包含：

- `statusUpdate`：任务状态变化，如 `SUBMITTED`、`WORKING`、`COMPLETED`。
- `artifactUpdate`：流式文本片段。
- `task`：最终任务快照。

### 6.4 标准错误

官方兼容层错误使用统一结构：

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task not found",
    "status": "NOT_FOUND",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": "TASK_NOT_FOUND",
        "domain": "a2a.tele-laika.local",
        "metadata": {
          "task_id": "missing-task"
        }
      }
    ]
  }
}
```

内部 `ERROR` Envelope 会映射到该标准错误形态；`CANCELLED` 类终态则映射为标准 `Task` 状态 `CANCELED`。

---

## 7. MultiAgent 增强端点

### 7.1 注册 HTTP Agent

`endpoint` 可选。填写后，MultiAgent 子任务会优先通过 HTTP POST 调用该 endpoint；未填写时继续走本地 ProviderRouter。

```bash
curl -X POST http://localhost:8000/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "remote-coder",
    "name": "Remote Coder",
    "roles": ["worker"],
    "capabilities": ["code"],
    "endpoint": "http://127.0.0.1:9001/invoke",
    "api_key": "remote-agent-key"
  }'
```

### 7.2 POST /delegate/fan-in

```bash
curl -X POST http://localhost:8000/delegate/fan-in \
  -H "Content-Type: application/json" \
  -d '{
    "target_agents": ["researcher", "coder", "tester"],
    "task": "分析 MultiAgent 增强方案",
    "aggregation": "summary",
    "failure_policy": "partial"
  }'
```

关键字段：

| 字段 | 说明 |
| ---- | ---- |
| `target_agents` | 并发执行的 Agent ID 列表 |
| `task` | 默认任务文本 |
| `tasks` | 可选；按 Agent ID 或数组位置指定不同任务 |
| `aggregation` | `json`、`concat`、`summary` |
| `failure_policy` | `partial`、`fail_fast`、`compensate` |
| `compensation_agent` | 失败补偿 Agent |

### 7.3 POST /delegate/pipeline

```bash
curl -X POST http://localhost:8000/delegate/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "task": "完成接口兼容层",
    "steps": [
      {"agent": "planner", "task": "制定计划：{input}"},
      {"agent": "worker", "task": "根据计划实现：{previous}"},
      {"agent": "reviewer", "task": "审查实现结果：{previous}"}
    ],
    "failure_policy": "fail_fast"
  }'
```

任务模板支持：

- `{input}` / `{task}`：原始任务。
- `{previous}` / `{result}`：上一步结果。
- `{step_index}`：当前步骤序号。
- `{agent_id}`：当前 Agent ID。

### 7.4 POST /delegate/planner-worker-reviewer

```bash
curl -X POST http://localhost:8000/delegate/planner-worker-reviewer \
  -H "Content-Type: application/json" \
  -d '{
    "task": "增强 MultiAgent 协作能力",
    "planner_agent": "planner",
    "worker_agents": ["worker-1", "worker-2"],
    "reviewer_agent": "reviewer",
    "aggregation": "summary",
    "failure_policy": "compensate",
    "compensation_agent": "fallback-worker"
  }'
```

如果未显式填写 `planner_agent`、`worker_agents`、`reviewer_agent`，Gateway 会按 Agent 的 `roles` 自动查找 `planner`、`worker`、`reviewer`。

响应仍使用课程版 `AGENT_RESPONSE` Envelope，payload 中新增：

- `pattern`：实际协作模式。
- `sub_results` / `steps` / `worker_results`：子任务结果。
- `aggregation`：聚合策略。
- `compensations`：失败补偿记录。
