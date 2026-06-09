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
  cli_agent.py            # CLI Agent
  mock_server.py          # Mock LLM Server
  core/                   # 核心模块 (状态机/校验/重试/安全/审计/...)
  adapters/                # Provider 适配器 (OpenAI/Anthropic/Ollama/Mock)
  models/                  # 数据模型 (Envelope/SessionState)
config/
  .env.example            # 环境变量模板
tests/
  test_comprehensive.py   # 141 测试用例
docs/
  01-design.md            # 设计说明
  02-api.md               # API 示例
  03-deploy.md            # 部署说明
  04-testing.md           # 测试说明
  05-issues.md            # 问题记录
  06-protocol.md          # 协议说明
  07-ai-coding-reflection.md  # AI 编程反思
  08-final-report.md      # 期末报告
evidence/
  logs/                   # 运行日志
  screenshots/             # 截图
  test-results/            # 测试结果
  provider-call/           # Provider 调用证据
  extension-goals/        # 扩展目标证据
  audit/                   # 审计日志
  performance/             # 性能基线
scripts/
  collect_evidence.py      # 证据收集
  perf_baseline.py         # 性能基线
  generate_report.py       # 自动报告生成
```

## 扩展目标覆盖

| 档位 | 目标编号 |
|------|----------|
| 必做 | 1,2,3,4,5,6,7,8,9,11,14,16,18,20,21,30,34,35,36 |
| 增强 | 10,12,15,17,19,22,23,24,31,32,33 |
| 终极 | 13,25,26,27,28,29,37 |

共 37/37 目标已完成，141 测试用例 100% 通过。