# #14 — 本地模型部署证据

## 1. 配置方式

Gateway 通过 `.env` 文件配置 Ollama 本地模型提供商：

```env
PROVIDER3_TYPE=ollama
PROVIDER3_NAME=qwen-local
PROVIDER3_ENDPOINT=http://localhost:11434/v1
PROVIDER3_API_KEY=unused
PROVIDER3_MODEL=qwen2.5:0.5b
PROVIDER3_TIMEOUT=120
PROVIDER3_MAX_TOKENS=2048
```

## 2. Ollama 适配器实现

**文件**: `app/adapters/ollama_provider.py`

OllamaProviderAdapter 继承 OpenAIProviderAdapter，复用 OpenAI 兼容协议：
- 无需 API Key（设为 `"unused"`）
- 基础 URL 为 `http://localhost:11434/v1`
- 模型名为本地标签（如 `qwen2.5:0.5b`、`llama3.2`）
- 支持流式和非流式调用

## 3. Mock Server 模拟验证

`app/mock_server.py` 提供了一个独立的 HTTP 服务器，模拟 Ollama/OpenAI 兼容 API：
- 端点: `POST /v1/chat/completions`
- 支持场景: normal, delay, error, timeout, mid_stream_error, duplicate_token, out_of_order, partial_disconnect, long_response
- 运行: `python -m app.mock_server --port 9000`

Gateway 配置指向 mock_server 可验证完整流式管道：

```env
PROVIDER1_TYPE=openai_compatible
PROVIDER1_NAME=mock-server
PROVIDER1_ENDPOINT=http://localhost:9000/v1
PROVIDER1_API_KEY=unused
PROVIDER1_MODEL=mock-model
```

## 4. 路由集成

GatewayConfig.strategy 支持 `model_name`、`task_type`、`capability` 路由策略，
可将特定模型名或任务类型路由到 Ollama 提供商：

```python
PROVIDER3_CAPABILITIES=local,chat,code
PROVIDER3_TASK_TYPES=chat,code
```

## 5. 测试验证

- `TestProviderAdapter.test_mock_provider_normal` — 验证 mock 适配器流式输出
- `TestProviderAdapter.test_mock_provider_mid_stream_error` — 验证流中断处理
- `TestIntegration.test_full_invoke_pipeline` — 验证完整 INVOKE → STREAM_CHUNK → STREAM_END 管道