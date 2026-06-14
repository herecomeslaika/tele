# 01 — 系统设计说明

## 1. 系统概述

A2A_min_v1 Protocol Gateway 是一个 Agent-to-Agent 通信网关，作为 Agent 与 LLM Provider 之间的中间层。Gateway 接收 Agent 发来的 A2A_min_v1 协议消息，经过校验、状态机控制和路由选择后，将请求转发至对应的 LLM Provider，再将 Provider 返回的流式结果封装为 A2A_min_v1 信封返回给 Agent。

### 1.1 设计目标

| 目标 | 说明 | 对应扩展目标 |
|------|------|-------------|
| 统一协议 | 所有 Agent 通过同一信封格式通信，屏蔽 Provider 差异 | #1, #32, #33 |
| 严格校验 | Schema + Seq + 状态机三重校验，拒绝非法消息 | #1, #5, #7 |
| 多 Provider 路由 | 7 种路由策略 + 自动 Failover，适配异构 LLM 服务 | #12, #25, #26 |
| 流式传输 | AsyncIterator 流式接口，逐 token 转发 | #36 |
| 超时与重试 | 4 类超时分类 + 指数退避重试 | #3, #11 |
| 安全边界 | API Key 认证、Agent 身份、请求来源限制 | #28, #29 |
| 可观测性 | 结构化日志、追踪、指标、持久化审计 | #16, #17, #18, #19, #27 |

### 1.2 技术栈

| 组件 | 技术选择 | 选择理由 |
|------|----------|----------|
| Web 框架 | FastAPI + Uvicorn | 原生 async/await、SSE 支持、自动 OpenAPI 文档 |
| 数据校验 | Pydantic v2 | 严格模式 + field_validator + model_validator |
| 异步运行时 | asyncio + pytest-asyncio | 与 FastAPI 一致的异步模型 |
| 追踪 | OpenTelemetry (简易) | TraceContext + TraceCollector 模拟 Span |
| 日志 | Python logging (结构化 JSON) | 8 字段规范，支持完整调用链复查 |
| 测试 | pytest | 141 用例，覆盖正常路径和边界场景 |

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────┐
│            REST / WebSocket / SSE                       │  ← 接入层
│  POST /invoke  POST /stream  WS /ws  POST /cancel      │
├─────────────────────────────────────────────────────────┤
│            GatewayApp                                   │  ← 网关编排层
│  handle_envelope → handle_invoke/handle_cancel/...     │
│  SessionStore (状态机/队列/计时器/幂等性/序号校验)       │
├──────────┬──────────┬──────────┬────────────────────────┤
│  状态机   │  校验层   │  安全层   │  可观测性层           │  ← 核心层
│  StateM  │  SeqChk  │  Security│  Log/Trace/Audit      │
│  Timeout │  Idempot │  Policy  │  Metrics              │
├──────────┴──────────┴──────────┴────────────────────────┤
│         ProviderRouter + Adapters                       │  ← Provider 适配层
│  (OpenAI / Anthropic / Ollama / Mock)                  │
│  Router: priority/hash/round_robin/model/task/cap/rt   │
└─────────────────────────────────────────────────────────┘
```

数据流方向：

```
Agent → [REST/WS/SSE] → GatewayApp.handle_envelope()
  → Envelope Schema 校验 (Pydantic)
  → 安全检查 (API Key + Agent ID + 策略过滤)
  → 幂等性检查 (corr_id)
  → 限流检查 (RateLimiter)
  → 状态机转换 (GatewayStateMachine)
  → 路由选择 (ProviderRouter)
  → Provider 调用 (ProviderAdapter.invoke)
  → 流式转发 (STREAM_CHUNK × N → STREAM_END)
  → 审计/指标/追踪记录
Agent ← [REST/WS/SSE] ← STREAM_CHUNK / STREAM_END / ERROR
```

### 2.2 模块职责

| 模块 | 文件 | 职责 | 对应目标 |
|------|------|------|----------|
| GatewayApp | `app/main.py` | FastAPI 入口、会话编排、REST/WebSocket 端点 | #36 |
| Envelope | `app/models/envelope.py` | 统一信封定义、Pydantic 校验、Legacy 映射 | #1, #32 |
| SessionState | `app/models/state.py` | 会话状态枚举（六状态） | #7 |
| GatewayStateMachine | `app/core/state_machine.py` | 状态机引擎、转换表驱动、终态守卫 | #7 |
| SeqChecker | `app/core/seq_checker.py` | 序号单调递增校验，检测跳号/回退/重复 | #5 |
| ErrorCodeDef | `app/core/errors.py` | 31 错误码注册表，含来源/可恢复/重试标记 | #2 |
| TimeoutChecker | `app/core/timeout.py` | 四类超时检查 | #11 |
| IdempotencyManager | `app/core/idempotency.py` | corr_id 幂等性管理，4 种策略 | #4 |
| RetryManager | `app/core/retry.py` | 指数退避重试，仅重试可恢复错误 | #3 |
| BoundedQueue / RateLimiter | `app/core/flow_control.py` | 有界队列 + 令牌桶限流 | #10 |
| StructuredLogger | `app/core/logger.py` | 8 字段结构化 JSON 日志 | #16 |
| TraceContext / TraceCollector | `app/core/tracing.py` | OpenTelemetry 简易追踪 | #19 |
| Metrics | `app/core/metrics.py` | 请求计数 + 延迟统计 | #17 |
| AuditLogger | `app/core/audit.py` | JSONL 持久化审计，跨实例重载 | #27 |
| SecurityManager | `app/core/security.py` | API Key + Agent 注册 + 来源限制 + 脱敏 | #28 |
| PolicyFilter | `app/core/policy_filter.py` | 三层策略过滤（协议/网关/应用） | #29 |
| GatewayConfig | `app/core/config.py` | 配置加载与校验 | #15 |
| MultiAgentManager | `app/core/multi_agent.py` | Agent 注册、委派、fan-out 协调 | #37 |
| ProviderRouter | `app/adapters/router.py` | 7 种路由策略 + 能力注册 | #25, #26 |
| ProviderAdapter | `app/adapters/provider.py` | 统一 Provider 接口基类 | #12 |
| OpenAIProviderAdapter | `app/adapters/openai_provider.py` | OpenAI-compatible 适配器 | #12, #13 |
| AnthropicProviderAdapter | `app/adapters/anthropic_provider.py` | Anthropic-compatible 适配器 | #13 |
| OllamaProviderAdapter | `app/adapters/ollama_provider.py` | Ollama 本地适配器 | #14 |
| MockProviderAdapter | `app/adapters/mock_provider.py` | Mock 适配器（10 场景） | #21, #22 |
| CLI Agent | `app/cli_agent.py` | 命令行 Agent 入口 | #30 |
| Mock LLM Server | `app/mock_server.py` | 独立 HTTP Mock 服务器 | #21 |

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

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `version` | `ProtocolVersion` | 仅 `v1`（`"1"` 自动归一化） | 协议版本，拒绝未知版本 |
| `type` | `MessageType` | 8 种枚举值 | 消息类型，Legacy 名称自动映射 |
| `session_id` | `str` | 1–128 字符 | 会话标识，同一 Agent 的多次请求可共享 |
| `corr_id` | `str` | 1–128 字符 | 请求关联标识，用于幂等性和 seq 校验 |
| `seq` | `Optional[int]` | ≥ 0 | 序号，STREAM_CHUNK/STREAM_END 必需，从 1 递增 |
| `timestamp` | `str` | ISO 8601 | 自动生成，消息创建时间 |
| `payload` | `dict` | 按 type 不同校验 | 消息体，`extra="forbid"` 拒绝未定义字段 |

**Pydantic 校验链**：
1. `field_validator("version")` — 归一化 `"1"` → `"v1"`，拒绝未知版本
2. `field_validator("type")` — Legacy 名称映射 + 拒绝未知类型
3. `model_validator("after")` — 按 type 校验 payload 内容（如 INVOKE 必须含 prompt/messages + model）
4. `model_config = {"extra": "forbid"}` — 拒绝信封级别的未定义字段

### 3.2 Legacy 兼容 (#32)

CSD_Stream_v0 旧名称在 `field_validator("type")` 阶段自动映射为新名称，映射在 `LEGACY_MESSAGE_MAP` 字典中定义：

| 旧名称 (CSD_Stream_v0) | 新名称 (A2A_min_v1) | 映射时机 |
|------------------------|---------------------|----------|
| TASK_START | INVOKE | field_validator 阶段 |
| CHUNK | STREAM_CHUNK | field_validator 阶段 |
| TASK_END | STREAM_END | field_validator 阶段 |
| STOP | CANCEL | field_validator 阶段 |
| PING | HEARTBEAT | field_validator 阶段 |
| FAIL | ERROR | field_validator 阶段 |

映射后，Gateway 内部只使用新名称处理，旧名称不再出现。未在映射表中的类型触发 `INVALID_MESSAGE_TYPE` 错误。

### 3.3 状态机 (#7)

六状态：`Idle → Invoked → Streaming → Done / Failed / Cancelled`

转换表（12 条合法路径）：

| 当前状态 | 事件 | 目标状态 | 说明 |
|----------|------|----------|------|
| Idle | INVOKE | Invoked | Agent 发起请求 |
| Invoked | STREAM_CHUNK | Streaming | 首个 token 到达 |
| Invoked | STREAM_END | Done | Provider 立即完成（无流式输出） |
| Invoked | ERROR | Failed | Provider 返回错误 |
| Invoked | CANCEL | Cancelled | Agent 在首 token 前取消 |
| Invoked | TIMEOUT | Failed | 首 token/Provider 超时 |
| Streaming | STREAM_CHUNK | Streaming | 后续 token（自环） |
| Streaming | STREAM_END | Done | 生成完成 |
| Streaming | ERROR | Failed | 流中错误 |
| Streaming | CANCEL | Cancelled | Agent 在流中取消 |
| Streaming | TIMEOUT | Failed | token 间隔/总任务超时 |
| 非 Idle 非终态 | HEARTBEAT | (不变) | 心跳确认，更新 last_seen |

**终态守卫**：Done / Failed / Cancelled 不可逆，所有后续事件被拒绝并返回 `MSG_AFTER_TERMINAL`。

**与 Lab02 / D5 模型对应关系**：

| A2A_min_v1 状态 | Lab02 模型 | D5 状态路径 |
|-----------------|-----------|-------------|
| Idle | Init | 等待请求 |
| Invoked | Pending | 请求已接收，等待 Provider 响应 |
| Streaming | Active | 正在接收 token |
| Done | Completed | 正常完成 |
| Failed | Error | 异常终止 |
| Cancelled | Cancelled | 主动取消 |

### 3.4 错误码体系 (#2)

31 个注册错误码，每个包含 `error_code`、`source`（来源）、`trigger`（触发条件）、`recoverable`（是否可恢复）、`retry_recommended`（是否建议重试）、`description`（返回给 Agent 的说明）。

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

---

## 4. 关键设计决策

### 4.1 Pydantic 严格模式

**决策**：信封使用 `extra = "forbid"` 拒绝未定义字段。

**理由**：防止协议外字段渗入，确保所有通信严格遵守 A2A_min_v1 规范。若允许额外字段，Agent 可能依赖未定义的行为，导致前后向兼容性问题。

**权衡**：牺牲了灵活性，但增强了协议的确定性和可验证性。

### 4.2 转换表驱动状态机

**决策**：状态转换由 `_TRANSITIONS` 字典驱动，而非 if/elif 链。

**理由**：新增转换只需添加一行映射，无需修改逻辑代码。转换表可枚举、可验证，确保状态机完整性。

**权衡**：HEARTBEAT 的特殊处理（非 Idle 非终态自环）不在转换表中，需单独判断。

### 4.3 AsyncIterator 流式接口

**决策**：Provider 适配器统一返回 `AsyncIterator[StreamEvent]`，网关逐 event 消费并生成 STREAM_CHUNK 信封。

**理由**：
- 与 FastAPI 的 StreamingResponse 天然兼容
- 取消时可直接 `break` 退出循环，无需额外取消信号
- 流控和背压可在消费端控制

**权衡**：Provider 返回的 StreamEvent 是内部类型，需手动转换为 A2A 信封。

### 4.4 JSONL 持久化审计

**决策**：审计日志采用 JSONL 格式写入文件，每条记录一行 JSON。

**理由**：
- 追加写入，不会因进程崩溃丢失已写入的记录
- 每行独立 JSON，无需解析整个文件
- 跨实例重载：新实例启动时回放所有 JSONL 文件重建内存索引

**权衡**：文件无压缩，长期运行可能文件较大；查询性能取决于内存索引。

### 4.5 声明式能力路由

**决策**：Provider 通过 `CapabilityProfile` 声明能力标签，路由器按交集匹配选择最佳 Provider。

**理由**：声明式比命令式更容易维护——新增 Provider 只需声明能力，无需修改路由逻辑。交集匹配确保选出的 Provider 满足所有要求。

**权衡**：当多个 Provider 满足同一能力集时，当前按名称排序取第一个，可能不够精确。

### 4.6 幂等性策略选择

**决策**：不同消息类型采用不同幂等策略（ACCEPT/REUSE/IGNORE/REJECT）。

| 场景 | 策略 | 理由 |
|------|------|------|
| 重复 INVOKE（任务活跃中） | REJECT | 不能同时执行两个相同 corr_id 的任务 |
| 重复 INVOKE（任务终态） | REUSE | 返回缓存结果，避免重复调用 Provider |
| 重复 CANCEL | IGNORE | 幂等取消，不返回错误 |
| 重复 STREAM_END | IGNORE | 终态已确定，忽略重复通知 |

### 4.7 本地取消 vs 上游取消

**决策**：当前实现本地取消（Gateway 停止转发 token），未实现上游取消（向 Provider 发送取消信号）。

**理由**：OpenAI/Anthropic API 不支持请求级取消。Ollama 虽支持 `/api/abort`，但当前未集成。

**权衡**：Provider 继续生成 token 直到自然结束，浪费计算资源。后续可扩展 `OllamaProviderAdapter.abort()` 方法。
