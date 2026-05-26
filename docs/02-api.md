# 02 — API 接口说明

## 1. REST 端点

### 1.1 POST /invoke — 同步调用

发送 INVOKE 消息，等待完整响应返回。

**请求**：
```bash
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -H "X-Agent-ID: your-agent-id" \
  -d '{
    "version": "v1",
    "type": "INVOKE",
    "session_id": "sess-001",
    "corr_id": "corr-001",
    "payload": {
      "prompt": "你好，请介绍一下自己",
      "model": "deepseek-chat"
    }
  }'
```

**响应**：包含完整 chunks 数组的 JSON。

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

**响应**：SSE 流，每个事件格式为 `data: {json}\n\n`。

### 1.3 WebSocket /ws — 双向通信

WebSocket 端点，支持双向 A2A 消息收发。

```python
import websockets, json

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
            print(data["payload"].get("content", ""), end="")
```

### 1.4 POST /cancel — 取消任务

```bash
curl -X POST http://localhost:8000/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "version": "v1", "type": "CANCEL",
    "session_id": "sess-001", "corr_id": "corr-001",
    "payload": {"reason": "user requested"}
  }'
```

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

### 1.6 GET /health — 健康检查

```bash
curl http://localhost:8000/health
# {"status": "ok", "providers": 3}
```

### 1.7 GET /metrics — 指标查询

```bash
curl http://localhost:8000/metrics
```

### 1.8 GET /error-codes — 错误码列表

```bash
curl http://localhost:8000/error-codes
```

### 1.9 GET /audit/{corr_id} — 审计查询

```bash
curl http://localhost:8000/audit/corr-001
```

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

### 2.4 GET /delegations — 列出所有委派记录

```bash
curl http://localhost:8000/delegations
```

---

## 3. Agent 委派消息

### 3.1 AGENT_DELEGATE

通过 WebSocket 或 /invoke 端点发送：

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
