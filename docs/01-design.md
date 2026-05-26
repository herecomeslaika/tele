# 01 — 系统设计说明

## 1. 系统概述

A2A_min_v1 Protocol Gateway 是一个 Agent-to-Agent 通信网关，作为 Agent 与 LLM Provider 之间的中间层，提供统一的协议接口、流式传输、超时管理、安全校验和可观测性。

### 1.1 设计目标
- 统一 Agent 与多个 LLM Provider 之间的通信协议
- 提供完整的协议校验（Schema + Seq + 状态机）
- 支持多 Provider 路由与故障切换
- 实现流式传输与超时管理
- 提供安全边界与可观测性

### 1.2 技术栈
| 组件 | 技术选择 |
|------|----------|
| Web 框架 | FastAPI + Uvicorn |
| 数据校验 | Pydantic v2 |
| 异步运行时 | asyncio + pytest-asyncio |
| 追踪 | OpenTelemetry (简易) |
| 日志 | Python logging (结构化 JSON) |
| 测试 | pytest |

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────┐
│           REST / WebSocket / SSE        │  ← 接入层
├─────────────────────────────────────────┤
│            GatewayApp                   │  ← 网关编排层
│  (handle_envelope → handle_invoke/...)  │
├──────────┬──────────┬──────────────────┤
│  状态机   │  校验层   │  可观测性层      │  ← 核心层
│  StateM  │  SeqChk  │  Log/Trace/Audit │
│  Timeout │  Idempot │  Metrics/Security│
├──────────┴──────────┴──────────────────┤
│         ProviderRouter + Adapters       │  ← Provider 适配层
│  (OpenAI / Anthropic / Ollama / Mock)  │
└─────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 |
|------|------|
| `app/main.py` | FastAPI 入口、GatewayApp 编排、REST/WebSocket 端点 |
| `app/models/envelope.py` | 统一信封定义、Pydantic 校验、Legacy 映射 |
| `app/models/state.py` | 会话状态枚举（六状态） |
| `app/core/state_machine.py` | 状态机引擎、转换表驱动 |
| `app/core/seq_checker.py` | 序号单调递增校验 |
| `app/core/errors.py` | 29 错误码注册表 |
| `app/core/timeout.py` | 四类超时检查 |
| `app/core/idempotency.py` | 幂等性管理 |
| `app/core/retry.py` | 指数退避重试 |
| `app/core/flow_control.py` | 有界队列 + 限流器 |
| `app/core/logger.py` | 结构化 JSON 日志 |
| `app/core/tracing.py` | OpenTelemetry 简易追踪 |
| `app/core/metrics.py` | 指标采集 |
| `app/core/audit.py` | 持久化审计（JSONL + 跨实例重载） |
| `app/core/security.py` | API Key 认证 + Agent 注册 + 敏感字段屏蔽 |
| `app/core/policy_filter.py` | 输入/输出内容过滤 |
| `app/core/config.py` | 配置加载与校验 |
| `app/core/multi_agent.py` | Multi-Agent 注册、委派、协调 |
| `app/adapters/router.py` | 多 Provider 路由（7 策略 + 能力注册） |
| `app/adapters/provider.py` | ProviderAdapter 基类 |
| `app/adapters/openai_provider.py` | OpenAI 兼容适配器 |
| `app/adapters/anthropic_provider.py` | Anthropic 适配器 |
| `app/adapters/ollama_provider.py` | Ollama 本地适配器 |
| `app/adapters/mock_provider.py` | Mock 适配器（9 场景） |

---

## 3. 协议设计

### 3.1 统一信封 (Envelope)

```json
{
  "version": "v1",
  "type": "INVOKE",
  "session_id": "sess-xxx",
  "corr_id": "corr-xxx",
  "seq": null,
  "timestamp": "2025-01-01T00:00:00+00:00",
  "payload": { ... }
}
```

- `version`: 协议版本，当前仅 `v1`
- `type`: 消息类型，8 种（INVOKE / STREAM_CHUNK / STREAM_END / CANCEL / HEARTBEAT / ERROR / AGENT_DELEGATE / AGENT_RESPONSE）
- `session_id`: 会话标识
- `corr_id`: 请求关联标识（用于幂等性和 seq 校验）
- `seq`: 序号（STREAM_CHUNK 必需，从 1 开始严格递增）
- `timestamp`: ISO 8601 时间戳
- `payload`: 消息体，按 type 有不同校验规则

### 3.2 Legacy 兼容

CSD_Stream_v0 旧名称自动映射：

| 旧名称 | 新名称 |
|--------|--------|
| TASK_START | INVOKE |
| CHUNK | STREAM_CHUNK |
| TASK_END | STREAM_END |
| STOP | CANCEL |
| PING | HEARTBEAT |
| FAIL | ERROR |

### 3.3 状态机

六状态：Idle → Invoked → Streaming → Done / Failed / Cancelled

转换表（12 条合法路径）：
- `(Idle, INVOKE)` → Invoked
- `(Invoked, STREAM_CHUNK)` → Streaming
- `(Invoked, STREAM_END)` → Done
- `(Invoked, ERROR)` → Failed
- `(Invoked, CANCEL)` → Cancelled
- `(Invoked, TIMEOUT)` → Failed
- `(Streaming, STREAM_CHUNK)` → Streaming（自环）
- `(Streaming, STREAM_END)` → Done
- `(Streaming, ERROR)` → Failed
- `(Streaming, CANCEL)` → Cancelled
- `(Streaming, TIMEOUT)` → Failed
- HEARTBEAT 在非 Idle、非终态被接受（自环）

终态（Done / Failed / Cancelled）不可逆，拒绝所有后续事件。

---

## 4. 关键设计决策

### 4.1 Pydantic 严格模式
信封使用 `extra = "forbid"` 拒绝未定义字段，防止协议外字段渗入。

### 4.2 转换表驱动状态机
状态转换由 `_TRANSITIONS` 字典驱动，而非 if/elif 链。新增转换只需添加一行映射。

### 4.3 AsyncIterator 流式接口
Provider 适配器统一返回 `AsyncIterator[StreamEvent]`，网关逐 event 消费并生成 STREAM_CHUNK 信封。

### 4.4 JSONL 持久化审计
审计日志采用 JSONL（每行一个 JSON 对象）格式写入文件，支持跨实例重载和灵活查询。

### 4.5 声明式能力路由
Provider 通过 `CapabilityProfile` 声明能力标签，路由器按交集匹配选择最佳 Provider。
