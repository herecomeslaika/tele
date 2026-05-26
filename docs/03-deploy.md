# 03 — 部署说明

## 1. 环境要求

- Python 3.10+
- pip

## 2. 安装

```bash
# 克隆项目
git clone https://github.com/herecomeslaika/tele.git
cd tele

# 安装依赖
pip install -r requirements.txt
```

## 3. 配置

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

### 3.1 Provider 配置

支持最多 9 个 Provider（PROVIDER1 ~ PROVIDER9），每个 Provider 配置项：

| 变量 | 说明 | 示例 |
|------|------|------|
| `PROVIDER{i}_TYPE` | 类型：openai_compatible / anthropic_compatible / ollama / mock | `openai_compatible` |
| `PROVIDER{i}_NAME` | 名称 | `deepseek` |
| `PROVIDER{i}_ENDPOINT` | API 端点 | `https://api.deepseek.com/v1` |
| `PROVIDER{i}_API_KEY` | API Key | `sk-xxx` |
| `PROVIDER{i}_MODEL` | 模型名 | `deepseek-chat` |
| `PROVIDER{i}_TIMEOUT` | 超时（秒） | `60` |
| `PROVIDER{i}_MAX_TOKENS` | 最大 Token 数 | `2048` |
| `PROVIDER{i}_TEMPERATURE` | 温度 | `0.7` |
| `PROVIDER{i}_CAPABILITIES` | 能力标签（逗号分隔） | `nlp,translation` |
| `PROVIDER{i}_TASK_TYPES` | 任务类型（逗号分隔） | `chat,qa` |

### 3.2 路由策略

| 策略 | 说明 |
|------|------|
| `priority` | 按 Provider 注册顺序，优先级高的优先 |
| `hash` | 按 session_id 哈希分配，同会话固定 Provider |
| `round_robin` | 轮询分配 |
| `model_name` | 按 payload.model 匹配 Provider 支持的模型 |
| `task_type` | 按 payload.task_type 匹配 |
| `capability` | 按 CapabilityRegistry 交集匹配 |
| `runtime` | 按 Provider runtime 类型匹配 |

---

## 4. 启动

### 4.1 网关服务

```bash
python -m app.main
```

默认监听 `http://0.0.0.0:8000`，可通过 `GATEWAY_HOST` 和 `GATEWAY_PORT` 配置。

### 4.2 Mock LLM Server

```bash
python -m app.mock_server --port 9000
```

独立 HTTP 服务器，模拟 LLM Provider 的 9 种场景（normal / timeout / error / mid_stream_error / empty / long_response / duplicate_token / out_of_order / partial_disconnect）。

### 4.3 CLI Agent

```bash
# 单次调用
python -m app.cli_agent invoke "你好" --model deepseek-chat

# 交互模式
python -m app.cli_agent chat

# 取消
python -m app.cli_agent cancel --session-id sess-001 --corr-id corr-001

# 心跳
python -m app.cli_agent heartbeat --session-id sess-001

# 健康检查
python -m app.cli_agent health

# 指标
python -m app.cli_agent metrics
```

---

## 5. Ollama 本地模型部署

```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 拉取模型
ollama pull qwen2.5:0.5b

# 启动 Ollama 服务
ollama serve

# 配置 .env
# PROVIDER3_TYPE=ollama
# PROVIDER3_ENDPOINT=http://localhost:11434/v1
# PROVIDER3_MODEL=qwen2.5:0.5b
```

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
```

### 6.2 反向代理
使用 Nginx 反向代理：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

### 6.3 审计日志持久化
审计日志默认写入 `evidence/audit/` 目录，JSONL 格式。建议配置日志轮转和归档策略。
