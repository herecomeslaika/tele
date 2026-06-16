# 03 — 部署说明

## 1. 环境要求

| 项目 | 最低版本 | 推荐版本 |
|------|----------|----------|
| Python | 3.10 | 3.12+ |
| pip | 最新 | — |
| 内存 | 512 MB | 2 GB+ |
| 网络 | 可访问 LLM Provider API | — |

## 2. 安装

```bash
# 克隆项目
git clone https://github.com/herecomeslaika/tele.git
cd tele

# 安装依赖
pip install -r requirements.txt
```

**依赖清单**：

| 包 | 版本 | 用途 |
|----|------|------|
| fastapi | ≥0.110.0 | Web 框架 |
| uvicorn | ≥0.29.0 | ASGI 服务器 |
| pydantic | ≥2.7.0 | 数据校验 |
| openai | ≥1.30.0 | OpenAI 兼容 API 客户端 |
| httpx | ≥0.27.0 | 异步 HTTP 客户端（CLI Agent） |
| anthropic | ≥0.30.0 | Anthropic API 客户端（可选） |
| python-dotenv | ≥1.0.0 | 环境变量加载 |
| websockets | ≥12.0 | WebSocket 客户端 |
| pytest | — | 测试框架（开发依赖） |
| pytest-asyncio | — | 异步测试支持（开发依赖） |

## 3. 配置

### 3.1 创建配置文件

```bash
# 复制环境变量模板
cp config/.env.example config/.env

# 编辑配置
# 必须配置至少一个 Provider：
#   PROVIDER1_TYPE=openai_compatible
#   PROVIDER1_ENDPOINT=https://api.deepseek.com/v1
#   PROVIDER1_API_KEY=sk-xxx
#   PROVIDER1_MODEL=deepseek-chat
```

### 3.2 Provider 配置

支持最多 9 个 Provider（PROVIDER1 ~ PROVIDER9），每个 Provider 配置项：

| 变量 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `PROVIDER{i}_TYPE` | 是 | 类型：openai_compatible / anthropic_compatible / ollama / mock | `openai_compatible` |
| `PROVIDER{i}_NAME` | 否 | 名称（默认 provider_i） | `deepseek` |
| `PROVIDER{i}_ENDPOINT` | 是 | API 端点 | `https://api.deepseek.com/v1` |
| `PROVIDER{i}_API_KEY` | 视类型 | API Key（Ollama 设为 `unused`） | `sk-xxx` |
| `PROVIDER{i}_MODEL` | 是 | 模型名 | `deepseek-chat` |
| `PROVIDER{i}_TIMEOUT` | 否 | 超时秒数（默认 60） | `120` |
| `PROVIDER{i}_MAX_TOKENS` | 否 | 最大 Token 数（默认 2048） | `4096` |
| `PROVIDER{i}_TEMPERATURE` | 否 | 温度（默认 0.7） | `0.3` |
| `PROVIDER{i}_CAPABILITIES` | 否 | 能力标签（逗号分隔，用于 #26 能力路由） | `nlp,translation` |
| `PROVIDER{i}_TASK_TYPES` | 否 | 任务类型（逗号分隔，用于 #26 任务路由） | `chat,qa` |

**配置示例 — 三 Provider 组合**：

```env
# Provider 1: DeepSeek (OpenAI-compatible, 远程)
PROVIDER1_TYPE=openai_compatible
PROVIDER1_NAME=deepseek
PROVIDER1_ENDPOINT=https://api.deepseek.com/v1
PROVIDER1_API_KEY=sk-your-key
PROVIDER1_MODEL=deepseek-chat
PROVIDER1_TIMEOUT=60
PROVIDER1_CAPABILITIES=nlp,chat
PROVIDER1_TASK_TYPES=chat,qa

# Provider 2: Claude (Anthropic-compatible, 远程)
PROVIDER2_TYPE=anthropic_compatible
PROVIDER2_NAME=claude
PROVIDER2_ENDPOINT=https://api.anthropic.com
PROVIDER2_API_KEY=sk-ant-xxx
PROVIDER2_MODEL=claude-sonnet-4-6-20250514
PROVIDER2_TIMEOUT=60

# Provider 3: Ollama (本地)
PROVIDER3_TYPE=ollama
PROVIDER3_NAME=qwen-local
PROVIDER3_ENDPOINT=http://localhost:11434/v1
PROVIDER3_API_KEY=unused
PROVIDER3_MODEL=qwen2.5:0.5b
PROVIDER3_TIMEOUT=120
PROVIDER3_CAPABILITIES=local,chat,code
PROVIDER3_TASK_TYPES=chat,code
```

### 3.3 路由策略配置

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| `priority` | 按注册顺序，高优先级优先 | 单 Provider 或简单 Failover |
| `hash` | 按 session_id 哈希固定到同一 Provider | 会话亲和 |
| `round_robin` | 轮询分配 | 均衡负载 |
| `model_name` | 按 payload.model 匹配 Provider 支持的模型 | 多模型环境 |
| `task_type` | 按 payload.task_type 匹配 | 任务类型路由 |
| `capability` | 按 CapabilityRegistry 交集匹配 | 能力路由 (#26) |
| `runtime` | 按 Provider runtime 标签匹配 | 多 Runtime 路由 (#25) |

### 3.4 超时与重试配置

```env
# 超时（秒）
FIRST_TOKEN_TIMEOUT=30       # INVOKE 后首 token 未到达
TOKEN_INTERVAL_TIMEOUT=15    # 两个 token 间隔过长
TOTAL_TASK_TIMEOUT=120       # 任务总时间超限
PROVIDER_RESPONSE_TIMEOUT=60 # Provider 未响应

# 重试
MAX_RETRIES=3                # 最大重试次数（仅可恢复错误）
RETRY_BASE_DELAY=1           # 基础延迟（秒）
RETRY_MAX_DELAY=30           # 最大延迟（秒）
RETRY_BACKOFF_FACTOR=2       # 指数退避因子
```

### 3.5 流控配置

```env
MAX_QUEUE_LENGTH=1000        # 每个 session 的缓冲队列上限
SEND_RATE_LIMIT=100          # 令牌桶限流（token/s）
```

### 3.6 安全配置

```env
SECURITY_ENABLED=true        # 是否启用安全检查
REQUIRE_AGENT_ID=true        # 是否要求 Agent 身份
MAX_INPUT_LENGTH=10000       # 输入最大字符数
MAX_OUTPUT_LENGTH=50000      # 输出最大字符数
```

### 3.7 配置校验

Gateway 启动时自动校验配置，缺失或非法配置会输出错误日志：

- 无 Provider 配置 → `No providers configured`
- Provider 缺少 endpoint → `Provider 'xxx' missing endpoint`
- Provider 缺少 model → `Provider 'xxx' missing model`
- 未知路由策略 → `Unknown routing strategy: xxx`
- MAX_RETRIES < 0 → `MAX_RETRIES must be >= 0`

---

## 4. 启动

### 4.1 网关服务

```bash
python -m app.main
```

默认监听 `http://0.0.0.0:8000`，可通过 `GATEWAY_HOST` 和 `GATEWAY_PORT` 配置。

启动日志示例：

```
{"event":"gateway.startup","state":"port=8000"}
{"event":"gateway.provider_registered","state":"deepseek"}
{"event":"gateway.provider_registered","state":"qwen-local"}
```

### 4.2 Mock LLM Server

```bash
python -m app.mock_server --port 9000
```

独立 HTTP 服务器，模拟 LLM Provider 的 9 种场景：

| 场景 | 说明 | 对应测试 |
|------|------|----------|
| normal | 正常流式输出 | TestProviderAdapter.test_mock_provider_normal |
| delay | 每块间延迟 | TestFaultInjection.test_delay_injection |
| error | 立即返回错误 | TestProviderAdapter.test_mock_provider_error |
| timeout | 永不响应 | TestProviderAdapter.test_mock_provider_timeout |
| mid_stream_error | 流中返回错误 | TestProviderAdapter.test_mock_provider_mid_stream_error |
| bad_json | 格式错误的 JSON | TestFaultInjection.test_bad_json |
| duplicate_token | 重复 token | TestFaultInjection.test_duplicate_token |
| out_of_order | 乱序 token | TestFaultInjection.test_out_of_order |
| partial_disconnect | 中途断连 | TestFaultInjection.test_partial_disconnect |
| long_response | 超长响应 | — |

运行时可通过 HTTP 切换场景：

```bash
curl -X POST http://localhost:9000/scenario -d '{"scenario": "mid_stream_error"}'
```

### 4.3 CLI Agent

```bash
# 单次流式调用
python -m app.cli_agent invoke "你好" --model deepseek-chat

# 非流式调用
python -m app.cli_agent invoke "写一首诗" --model deepseek-chat --no-stream

# 交互模式
python -m app.cli_agent chat

# 取消任务
python -m app.cli_agent cancel --session-id sess-001 --corr-id corr-001

# 心跳
python -m app.cli_agent heartbeat

# 健康检查
python -m app.cli_agent health

# 指标查看
python -m app.cli_agent metrics
```

**CLI Agent 功能** (#30)：
- 发送 INVOKE 请求并展示流式 token
- 触发 CANCEL（指定 session_id + corr_id）
- 发送 HEARTBEAT
- 显示错误信息（含 error_code 和 corr_id）
- 交互式 chat 模式（输入 cancel/heartbeat/metrics/quit 切换）

---

## 5. Ollama 本地模型部署

### 5.1 安装 Ollama

**Linux/macOS**：

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows**：

下载安装程序：https://ollama.com/download/windows

### 5.2 拉取模型

```bash
# 推荐 0.5B 小模型（内存友好）
ollama pull qwen2.5:0.5b

# 可选：1.5B / 3B 模型
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:3b
```

### 5.3 启动 Ollama 服务

```bash
ollama serve
```

默认监听 `http://localhost:11434`。OpenAI 兼容端点为 `http://localhost:11434/v1`。

### 5.4 验证 Ollama 运行

```bash
# 非流式调用
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:0.5b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 64,
    "stream": false
  }'

# 流式调用
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:0.5b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 64,
    "stream": true
  }'
```

### 5.5 配置 Gateway 使用 Ollama

在 `config/.env` 中添加：

```env
PROVIDER3_TYPE=ollama
PROVIDER3_NAME=qwen-local
PROVIDER3_ENDPOINT=http://localhost:11434/v1
PROVIDER3_API_KEY=unused
PROVIDER3_MODEL=qwen2.5:0.5b
PROVIDER3_TIMEOUT=120
PROVIDER3_MAX_TOKENS=2048
PROVIDER3_CAPABILITIES=local,chat,code
PROVIDER3_TASK_TYPES=chat,code
```

**部署证据**：参见 `evidence/local-model-deployment.md`，包含模型名称、启动方式、监听地址、直接调用记录和经 Gateway 调用记录。

### 5.6 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 连接被拒绝 | Ollama 未启动 | 运行 `ollama serve` |
| 模型不存在 | 未拉取模型 | 运行 `ollama pull qwen2.5:0.5b` |
| 首次响应极慢 | 模型加载中 | 等待加载完成（约 10–30 秒） |
| OOM 崩溃 | 模型太大 | 使用更小的模型（0.5B） |
| 超时 | 本地硬件性能不足 | 增大 `PROVIDER3_TIMEOUT` 至 180+ |

---

## 6. 生产部署建议

### 6.1 进程管理

推荐使用 systemd 或 supervisor 管理网关进程：

```ini
[program:a2a-gateway]
command=python -m app.main
directory=/path/to/tele
autostart=true
autorestart=true
stdout_logfile=/var/log/a2a-gateway/stdout.log
stderr_logfile=/var/log/a2a-gateway/stderr.log
environment=PROTOCOL_VERSION="v1"
```

### 6.2 反向代理

使用 Nginx 反向代理：

```nginx
location/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 300s;
}
```

注意 WebSocket 代理需要 `Upgrade` 和 `Connection` 头，且 `proxy_read_timeout` 应大于 `TOTAL_TASK_TIMEOUT`。

### 6.3 审计日志持久化

审计日志默认写入 `evidence/audit/` 目录，JSONL 格式。建议配置日志轮转和归档策略：

```bash
# 按天归档
0 0 * * * find /path/to/tele/evidence/audit -name "*.jsonl" -mtime +30 -exec gzip {} \;
```

### 6.4 安全加固

- 启用 `SECURITY_ENABLED=true`
- 配置强 API Key（至少 32 字符随机字符串）
- 通过反向代理限制来源 IP
- HTTPS 部署
- 定期轮换 API Key

---

## 7. 可靠性与可观测部署

### 7.1 关键配置

```bash
MAX_QUEUE_LENGTH=1000
BACKPRESSURE_TIMEOUT=1
BACKPRESSURE_DROP_OLDEST=false
PROVIDER_FAILURE_THRESHOLD=3
PROVIDER_CIRCUIT_BREAKER_COOLDOWN=30
```

- `BACKPRESSURE_TIMEOUT`：队列满时等待下游消费的最长时间。
- `BACKPRESSURE_DROP_OLDEST=false`：默认启用真实背压，不静默丢弃旧 chunk。
- `PROVIDER_FAILURE_THRESHOLD`：连续失败达到该值后打开熔断。
- `PROVIDER_CIRCUIT_BREAKER_COOLDOWN`：故障 Provider 被摘除后的冷却秒数。

### 7.2 OTel Collector + Prometheus + Grafana

配置文件位于 `deploy/observability/`：

```bash
cd deploy/observability
docker compose up -d
```

端口：

| 服务 | 端口 | 说明 |
| ---- | ---- | ---- |
| OTel Collector gRPC | 4317 | OTLP gRPC |
| OTel Collector HTTP | 4318 | OTLP HTTP |
| OTel Prometheus Exporter | 8889 | Collector 暴露的 Prometheus 指标 |
| Prometheus | 9090 | 指标查询 |
| Grafana | 3000 | 可视化面板 |

Gateway 自身提供 `GET /metrics/prometheus`，Prometheus 配置会抓取该文本指标端点。

### 7.3 本地可视化证据

`evidence/visualization/reliability-dashboard.html` 是无需 Docker 的静态面板，可用于课程报告截图。运行网关后也可以访问：

```bash
curl http://localhost:8000/dashboard/reliability-data
```

该接口返回 metrics、Provider 健康、活跃 session、活跃 Provider 映射和队列深度。
