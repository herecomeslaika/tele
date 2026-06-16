# A2A_min_v1 Protocol Gateway

Agent-to-Agent 通信网关，实现 A2A_min_v1 协议，支持多 Provider 路由、状态机控制、流式传输、安全校验和可观测性。

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

```bash
cp config/.env.example config/.env
# 编辑 config/.env，填入 Provider API Key
```

### 一键运行测试

```bash
python -m pytest tests/test_comprehensive.py -v
# 预期：141 passed
```

### 启动网关

```bash
python -m app.main
```

网关默认监听 `http://0.0.0.0:8000`。

### CLI Agent

```bash
# 流式调用
python -m app.cli_agent invoke "你好" --model deepseek-chat

# 交互模式
python -m app.cli_agent chat
```

### Mock LLM Server

```bash
python -m app.mock_server --port 9000
```

## 项目结构

```
app/
  main.py                 # FastAPI 入口 + GatewayApp
  cli_agent.py            # CLI Agent (#30)
  mock_server.py          # Mock LLM Server (#21)
  core/                   # 核心模块
    state_machine.py      # 状态机引擎 (#7)
    seq_checker.py        # 序号校验 (#5)
    errors.py             # 28 错误码注册表 (#2)
    idempotency.py        # 幂等性管理 (#4)
    retry.py              # 指数退避重试 (#3)
    timeout.py            # 四类超时 (#11)
    flow_control.py       # 流控与背压 (#10)
    logger.py             # 结构化日志 (#16)
    tracing.py            # OpenTelemetry 追踪 (#19)
    metrics.py            # 指标采集 (#17)
    audit.py              # 持久化审计 (#27)
    security.py           # 安全边界 (#28)
    policy_filter.py      # 输入输出过滤 (#29)
    config.py             # 配置加载 (#15)
    multi_agent.py        # Multi-Agent (#37)
  adapters/               # Provider 适配器 (#12)
    provider.py           # 统一接口基类
    openai_provider.py    # OpenAI-compatible (#13)
    anthropic_provider.py # Anthropic-compatible (#13)
    ollama_provider.py    # Ollama 本地 (#14)
    mock_provider.py      # Mock 适配器 (#21, #22)
    router.py             # 路由 (#25, #26)
  models/                 # 数据模型
    envelope.py           # 统一信封 (#1, #32, #33)
    state.py              # 会话状态枚举 (#7)
config/
  .env.example            # 环境变量模板
tests/
  test_comprehensive.py   # 141 测试用例 (#20)
docs/
  01-design.md            # 设计说明 (#34)
  02-api.md               # API 示例 (#34)
  03-deploy.md            # 部署说明 (#34)
  04-testing.md           # 测试说明 (#34)
  05-issues.md            # 问题记录 (#34)
  06-protocol.md          # 协议说明 (#34)
  07-ai-coding-reflection.md  # AI 编程反思 (#35)
  08-final-report.md      # 期末报告 (#34)
  submission-checklist.md # 提交检查清单
evidence/
  audit/                  # JSONL 审计日志 (#27)
  test-results/           # 测试结果 (#20)
  provider-call/          # Provider 调用证据 (#14, #36)
  extension-goals/        # 扩展目标证据
  performance/            # 性能基线 (#23)
  local-model-deployment.md  # 本地模型部署证据 (#14)
  deepseek-e2e-validation.md # DeepSeek 端到端证据 (#36)
scripts/
  collect_evidence.py     # 证据收集 (#31)
  perf_baseline.py        # 性能基线 (#23)
  generate_report.py      # 自动报告 (#31)
```

## 扩展目标覆盖

| 档位 | 目标编号 |
|------|----------|
| 必做 | 1, 2, 5, 6, 7, 8, 9, 11, 14, 16, 18, 20, 21, 30, 34, 35, 36 |
| 增强 | 3, 4, 10, 12, 15, 17, 19, 22, 23, 24, 31, 32, 33 |
| 终极 | 13, 25, 26, 27, 28, 29, 37 |

共 37/37 目标已完成，141 测试用例 100% 通过。

## 真实 Provider 调用证据

| Provider | 模型 | 首 Token 延迟 | 总耗时 | Chunks | 证据文件 |
|----------|------|---------------|--------|--------|----------|
| DeepSeek | deepseek-chat | 1.117s | 1.261s | 7 | evidence/deepseek-e2e-validation.json |
| Ollama | qwen2.5:0.5b | 1.426s | 1.702s | 32 | evidence/provider-call/ollama-gateway-e2e.json |

## 官方 A2A HTTP+JSON 兼容层（二次迭代）

项目在保留课程版 `A2A_min_v1` Envelope 接口的基础上，新增官方 A2A 兼容入口。兼容层只负责协议边界转换，内部仍复用原来的状态机、Provider 路由、安全边界、审计日志和流式执行链路。

新增核心文件：

- `app/models/a2a.py`：官方 A2A 数据模型，包括 `AgentCard`、`Message`、`Part`、`Task`、`Artifact`、`TaskState` 和标准错误。
- `app/core/a2a_compat.py`：官方 A2A 与 `A2A_min_v1` Envelope 的转换、Task 快照、SSE 事件和错误映射。
- `tests/test_a2a_compat.py`：官方兼容层测试。
- `docs/09-a2a-official-compat-plan.md`：第二次迭代计划。
- `docs/10-a2a-official-compat-progress.md`：第二次迭代进度追踪。

新增 HTTP+JSON 端点：

| 端点 | 方法 | 说明 |
| ---- | ---- | ---- |
| `/.well-known/agent-card.json` | GET | Agent Card 能力发现 |
| `/extendedAgentCard` | GET | 扩展 Agent Card；未配置时返回标准错误 |
| `/message:send` | POST | 非流式发送消息，返回最终 `Task` |
| `/message:stream` | POST | SSE 流式发送消息，返回 `StreamResponse` |
| `/tasks/{task_id}` | GET | 查询单个标准 `Task` |
| `/tasks` | GET | 查询当前内存任务快照 |
| `/tasks/{task_id}:cancel` | POST | 取消任务；终态任务返回标准错误 |
| `/tasks/{task_id}:subscribe` | POST | 订阅非终态任务状态 |

开发测试依赖：

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest -q
python -m pytest tests/test_comprehensive.py -q
```
