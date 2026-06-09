# #14 — 本地模型部署证据

## 1. 模型信息

| 项目 | 值 |
|------|------|
| 模型名称 | qwen2.5:0.5b |
| 模型系列 | qwen2 |
| 参数量 | 494.03M |
| 量化级别 | Q4_K_M |
| 格式 | GGUF |
| 上下文长度 | 32768 |
| 启动方式 | `ollama serve` |
| 监听地址 | `http://localhost:11434` |
| OpenAI 兼容端点 | `http://localhost:11434/v1` |
| 拉取命令 | `ollama pull qwen2.5:0.5b` |

---

## 2. 一次直接调用记录

### 2.1 非流式调用

```bash
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:0.5b",
    "messages": [{"role": "user", "content": "Say exactly: Hello from Ollama local model!"}],
    "max_tokens": 64,
    "stream": false
  }'
```

**返回结果**：

```json
{
  "id": "chatcmpl-390",
  "object": "chat.completion",
  "created": 1780996122,
  "model": "qwen2.5:0.5b",
  "system_fingerprint": "fp_ollama",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Hello! I am Qwen created by AI Lab Alibaba Group Corporation and my purpose is to assist and provide information on various topics like business strategy, market analysis, technology updates, etc.\nLet me know if you have any questions or need further assistance."
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 40,
    "completion_tokens": 51,
    "total_tokens": 91
  }
}
```

**验证**：HTTP 200，`finish_reason: "stop"`，`usage.total_tokens: 91`。

### 2.2 流式调用

```bash
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:0.5b",
    "messages": [{"role": "user", "content": "Say exactly: Hello from Ollama local model!"}],
    "max_tokens": 64,
    "stream": true
  }'
```

**返回结果**（SSE 流，节选首尾）：

```
data: {"id":"chatcmpl-352","object":"chat.completion.chunk","model":"qwen2.5:0.5b","system_fingerprint":"fp_ollama","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-352","object":"chat.completion.chunk","model":"qwen2.5:0.5b","system_fingerprint":"fp_ollama","choices":[{"index":0,"delta":{"role":"assistant","content":" from"},"finish_reason":null}]}

...（中间 chunk 省略）...

data: {"id":"chatcmpl-352","object":"chat.completion.chunk","model":"qwen2.5:0.5b","system_fingerprint":"fp_ollama","choices":[{"index":0,"delta":{"role":"assistant","content":"?"},"finish_reason":null}]}

data: {"id":"chatcmpl-352","object":"chat.completion.chunk","model":"qwen2.5:0.5b","system_fingerprint":"fp_ollama","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":"stop"}]}

data: [DONE]
```

**完整响应文本**：`"Hello from Ollama Local Model! How can I assist you today?"`
**总耗时**：908ms

**验证**：SSE 格式正确，`finish_reason: "stop"`，`data: [DONE]` 结束标记。

---

## 3. 一次经 Gateway 调用记录

### 3.1 Gateway 配置

```env
PROVIDER3_TYPE=ollama
PROVIDER3_NAME=qwen-local
PROVIDER3_ENDPOINT=http://localhost:11434/v1
PROVIDER3_API_KEY=unused
PROVIDER3_MODEL=qwen2.5:0.5b
PROVIDER3_TIMEOUT=120
PROVIDER3_MAX_TOKENS=64
```

### 3.2 调用过程

通过 `OllamaProviderAdapter`（继承 `OpenAIProviderAdapter`）发起流式调用：

```
Provider: qwen-local
Model: qwen2.5:0.5b
Endpoint: http://localhost:11434/v1
Prompt: "Say exactly: Hello from Ollama local model!"
```

### 3.3 Gateway 日志（节选）

```
[chunk #1]  content="Hello"        latency=1426ms
[chunk #2]  content=" from"        latency=1454ms
[chunk #3]  content=" O"           latency=1492ms
[chunk #4]  content="ll"           latency=1524ms
[chunk #5]  content="ama"          latency=1564ms
[chunk #6]  content=" local"       latency=1595ms
[chunk #7]  content=" model"       latency=1599ms
[chunk #8]  content="!"            latency=1603ms
...（中间 chunk 省略）...
[chunk #31] content=" today"       latency=1694ms
[chunk #32] content="?"            latency=1698ms
```

### 3.4 STREAM_END 结果

```
finish_reason: stop
total_tokens: 32
first_token_latency: 1426ms
total_duration: 1702ms
full_response: "Hello from Ollama local model! I'm here to help answer your questions and provide insights about the world of AI. How can I assist you today?"
```

### 3.5 JSON 证据文件

参见 `evidence/provider-call/ollama-gateway-e2e.json`，包含完整的机器可读结果：

```json
{
  "test": "ollama-gateway-e2e",
  "timestamp": "2026-06-09T17:11:21",
  "provider": "ollama",
  "model": "qwen2.5:0.5b",
  "endpoint": "http://localhost:11434/v1",
  "results": {
    "first_token_latency_ms": 1425.92,
    "total_duration_ms": 1702.04,
    "stream_end_reason": "stop",
    "stream_end_tokens": 32,
    "chunk_count": 32,
    "stream_end_received": true,
    "error": null,
    "full_response": "Hello from Ollama local model! I'm here to help answer your questions and provide insights about the world of AI. How can I assist you today?"
  },
  "overall_passed": true
}
```

**验证**：Gateway → Ollama Provider → STREAM_CHUNK × 32 → STREAM_END(reason="stop")，首 Token 延迟 1.4s，总耗时 1.7s。

---

## 4. Ollama 适配器实现

**文件**: `app/adapters/ollama_provider.py`

OllamaProviderAdapter 继承 OpenAIProviderAdapter，复用 OpenAI 兼容协议：
- 无需 API Key（设为 `"unused"`）
- 基础 URL 为 `http://localhost:11434/v1`
- 模型名为本地标签（如 `qwen2.5:0.5b`、`llama3.2`）
- 支持流式和非流式调用

---

## 5. 路由集成

GatewayConfig.strategy 支持 `model_name`、`task_type`、`capability` 路由策略，
可将特定模型名或任务类型路由到 Ollama 提供商：

```python
PROVIDER3_CAPABILITIES=local,chat,code
PROVIDER3_TASK_TYPES=chat,code
```

---

## 6. 测试验证

- `TestProviderAdapter.test_mock_provider_normal` — 验证 mock 适配器流式输出
- `TestProviderAdapter.test_mock_provider_mid_stream_error` — 验证流中断处理
- `TestIntegration.test_full_invoke_pipeline` — 验证完整 INVOKE → STREAM_CHUNK → STREAM_END 管道
- 本文档 §2 — 直接调用 Ollama 验证（非流式 + 流式）
- 本文档 §3 — 经 Gateway 调用 Ollama 验证（32 chunks, FTL 1426ms）
