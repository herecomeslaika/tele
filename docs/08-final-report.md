# 08 — 最终实验报告

## 1. 需求与范围

### 1.1 项目目标
实现一个具备协议校验、状态机控制、多 Provider 路由和追踪能力的 Agent-to-Agent (A2A) 通信网关。网关作为 Agent 与 LLM Provider 之间的中间层，提供统一的协议接口、流式传输、超时管理、安全校验和可观测性。

### 1.2 协议定义
- 协议名称：A2A_min_v1
- 消息类型：INVOKE, STREAM_CHUNK, STREAM_END, ERROR, CANCEL, HEARTBEAT, AGENT_DELEGATE, AGENT_RESPONSE
- 统一信封字段：version, type, session_id, corr_id, seq, timestamp, payload
- Legacy 兼容：TASK_START→INVOKE, CHUNK→STREAM_CHUNK, TASK_END→STREAM_END, STOP→CANCEL, PING→HEARTBEAT, FAIL→ERROR

### 1.3 开发范围

| 轮次 | 内容 | 主要 Prompt 约束 | 状态 |
|------|------|-----------------|------|
| R1 | 工程骨架、目录结构、Envelope 基础定义 | 只写骨架和 docstring | 完成 |
| R2 | 协议校验、错误码体系、SeqChecker、状态机引擎、心跳与超时 | 不实现具体大模型调用 | 完成 |
| R3 | ProviderAdapter 层、StructuredLogger、TraceContext、AuditLogger | 只适配，不修改核心逻辑 | 完成 |
| R4 | ProviderRouter、OTel 追踪、证据收集、扩展目标收尾 | 新增文件不修改核心 | 完成 |

---

## 2. 协议实现摘要

### 2.1 统一信封 (Envelope) (#1)

- **数据结构**：Pydantic BaseModel，7 字段（version/type/session_id/corr_id/seq/timestamp/payload）
- **严格校验**：`extra = "forbid"` 拒绝未定义字段，`field_validator` 拦截非法 type 和 version，`model_validator` 校验 payload 内容
- **Legacy 兼容** (#32)：`LEGACY_MESSAGE_MAP` 映射 CSD_Stream_v0 名称，在 field_validator 阶段自动转换
- **版本协商** (#33)：`normalize_version` 将 `"1"` 归一化为 `"v1"`，拒绝未知版本

**校验链**：

```
raw JSON → Envelope.__init__
  1. field_validator("version")  → normalize_version → 拒绝未知版本
  2. field_validator("type")     → normalize_type    → Legacy 映射 + 拒绝未知类型
  3. model_validator("after")    → check_payload_for_type → 按 type 校验 payload
  4. extra="forbid"              → 拒绝未定义字段
```

### 2.2 错误码体系 (#2)

31 个注册错误码，每个包含 6 个属性：

```python
@dataclass(frozen=True)
class ErrorCodeDef:
    code: str
    source: str          # "gateway" | "agent" | "provider"
    trigger: str         # 触发条件
    recoverable: bool
    retry_recommended: bool
    description: str     # 返回给 Agent 的说明
```

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

### 2.3 序号校验器 (SeqChecker) (#5)

按 `corr_id` 隔离，严格单调递增校验：

```python
def check(self, corr_id: str, seq: int, start: int = 1) -> SeqResult:
    expected = self._last_seq.get(corr_id, start - 1) + 1
    if seq == expected: → OK
    if seq == last:     → DUPLICATE (不可恢复)
    if seq < last:      → ROLLBACK (不可恢复)
    if seq > expected:  → GAP (可恢复)
```

### 2.4 状态机引擎 (GatewayStateMachine) (#7)

六状态 + 12 条合法路径 + 终态不可逆：

```
Idle ───INVOKE───→ Invoked
Invoked ─CHUNK──→ Streaming
Invoked ─END─────→ Done
Invoked ─ERROR──→ Failed
Invoked ─CANCEL─→ Cancelled
Invoked ─TIMEOUT→ Failed
Streaming ─CHUNK→ Streaming (自环)
Streaming ─END──→ Done
Streaming ─ERROR→ Failed
Streaming ─CANCEL→ Cancelled
Streaming ─TIMEOUT→ Failed
非Idle非终态 ─HEARTBEAT→ (自环，更新 last_seen)
```

与 Lab02 模型和 D5 状态路径的对应：

| A2A_min_v1 | Lab02 模型 | D5 路径 |
|------------|-----------|---------|
| Idle | Init | 等待请求 |
| Invoked | Pending | 等待 Provider |
| Streaming | Active | 接收 token |
| Done | Completed | 正常完成 |
| Failed | Error | 异常终止 |
| Cancelled | Cancelled | 主动取消 |

### 2.5 心跳与超时 (TimeoutChecker) (#8, #11)

四类超时维度：

| 类型 | 错误码 | 默认值 | 可恢复 | 触发条件 |
|------|--------|--------|--------|----------|
| 首 Token | FIRST_TOKEN_TIMEOUT | 30s | 是 | INVOKE 后无首个 STREAM_CHUNK |
| Token 间隔 | TOKEN_INTERVAL_TIMEOUT | 15s | 是 | 两个 STREAM_CHUNK 间隔超限 |
| 总任务 | TOTAL_TASK_TIMEOUT | 120s | 否 | 从 INVOKE 到结束总时间超限 |
| Provider | PROVIDER_RESPONSE_TIMEOUT | 60s | 是 | Provider 未响应 |

HEARTBEAT 接收后更新 `last_seen`，超时检查由 `check_timeouts()` 集中评估。

### 2.6 幂等性管理 (#4)

基于 `corr_id` 的消息去重，4 种策略：

| 场景 | 策略 | 理由 |
|------|------|------|
| 重复 INVOKE（活跃） | REJECT | 不能同时执行两个相同 corr_id 任务 |
| 重复 INVOKE（终态） | REUSE | 返回缓存结果 |
| 重复 CANCEL | IGNORE | 幂等取消 |
| 重复 STREAM_END | IGNORE | 终态已确定 |

### 2.7 可恢复重试 (#3)

仅对标记为 `recoverable=True` 的错误执行重试，指数退避策略：

```python
@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0     # seconds
    max_delay: float = 30.0
    backoff_factor: float = 2.0

delay = base_delay * backoff_factor^(attempt-1)
delay = min(delay, max_delay)
```

不可恢复错误立即返回失败。

### 2.8 终止后消息处理 (#6)

任务到达终态（Done/Failed/Cancelled）后，后续消息被终态守卫拒绝。Gateway 在日志中记录 `terminal-state-reject` warning，证明拒绝行为可追溯。

### 2.9 流控与背压 (#10)

- **BoundedQueue**：有界缓冲队列，满时丢弃最旧项（每 session 一个队列）
- **RateLimiter**：令牌桶限流器，控制发送速率

### 2.10 安全边界 (#28)

SecurityManager 实现 4 类安全策略：

| 策略 | 说明 | 实现 |
|------|------|------|
| API Key 认证 | 请求必须携带有效 API Key | `validate_api_key()` |
| Agent 身份 | 请求必须携带已注册的 Agent ID | `validate_agent_id()` |
| 来源限制 | 可配置允许的请求来源 | `validate_origin()` |
| 敏感字段屏蔽 | 返回数据中敏感字段自动脱敏 | `mask_sensitive_fields()` |

### 2.11 输入输出策略过滤 (#29)

PolicyFilter 实现三层过滤：

| 层 | 策略 | 示例 |
|----|------|------|
| 协议层 | 空请求拒绝 | prompt 和 messages 均为空 → EMPTY_REQUEST |
| Gateway 层 | 输入/输出长度限制 | 输入超过 10000 字符 → INPUT_TOO_LONG |
| 应用层 | 敏感字段脱敏 | api_key 字段自动屏蔽为 `sk****xx` |

### 2.12 Provider Adapter 层 (#12)

统一 ProviderAdapter 抽象基类：

```python
class ProviderAdapter(abc.ABC):
    async def invoke(self, prompt, **kwargs) -> AsyncIterator[StreamEvent]
    async def invoke_sync(self, prompt, **kwargs) -> str
    async def close(self) -> None
```

4 种实现：

| Adapter | 继承 | 协议 | API Key |
|---------|------|------|---------|
| OpenAIProviderAdapter | ProviderAdapter | POST /v1/chat/completions | Bearer token |
| AnthropicProviderAdapter | ProviderAdapter | POST /v1/messages | x-api-key |
| OllamaProviderAdapter | OpenAIProviderAdapter | POST /v1/chat/completions | unused |
| MockProviderAdapter | ProviderAdapter | 内部模拟 | — |

### 2.13 双协议兼容实现 (#13)

详见 `docs/06-protocol.md` §4。核心实现：
- OpenAI `delta.content` → `STREAM_CHUNK.payload.content` (openai_provider.py:54-61)
- Anthropic `delta.text` → `STREAM_CHUNK.payload.content` (anthropic_provider.py:65-75)
- OpenAI `finish_reason: "stop"` → `STREAM_END.payload.reason="stop"` (openai_provider.py:63-69)
- Anthropic `message_stop` → `STREAM_END.payload.reason="end_turn"` (anthropic_provider.py:77-82)

### 2.14 本地模型部署 (#14)

模型：qwen2.5:0.5b (Ollama)
证据：`evidence/local-model-deployment.md`
- 直接调用：非流式 91 tokens / 流式 5 chunks
- 经 Gateway 调用：32 chunks, FTL 1426ms, 总耗时 1702ms
- JSON 证据：`evidence/provider-call/ollama-gateway-e2e.json`

### 2.15 配置化 Gateway (#15)

GatewayConfig 支持 30+ 个配置项，通过 .env 文件或环境变量配置。配置校验逻辑在 `validate_config()` 中实现，缺失或非法配置返回明确错误信息。

### 2.16 结构化日志 (#16)

8 字段规范：

```json
{
  "timestamp": "2026-05-26T19:15:00.123",
  "session_id": "sess-001",
  "corr_id": "corr-001",
  "seq": 1,
  "state": "Streaming",
  "event": "gateway.stream",
  "latency_ms": 145.2,
  "error_code": null
}
```

所有日志输出为单行 JSON，可通过 `jq` 管道过滤重建完整调用链。

### 2.17 指标采集 (#17)

Metrics 类采集 7 个指标：

| 指标 | 说明 |
|------|------|
| request_count | 总请求数 |
| success_count | 成功数 |
| failure_count | 失败数 |
| cancel_count | 取消数 |
| timeout_count | 超时数 |
| avg_first_token_latency_ms | 平均首 Token 延迟 |
| p95_first_token_latency_ms | P95 首 Token 延迟 |

### 2.18 简易追踪 (#18)

基于 `session_id` 和 `corr_id` 关联请求：

```
Agent 日志: [corr_id=c001] INVOKE sent
Gateway 日志: [corr_id=c001] gateway.receive → gateway.route → provider.call
Provider 日志: [corr_id=c001] stream.chunk × 7 → stream.end
Gateway 日志: [corr_id=c001] gateway.stream × 7 → STREAM_END
Agent 日志: [corr_id=c001] STREAM_END received
```

使用 `grep corr_id=c001 evidence/audit/*.jsonl` 可重建完整交互链。

### 2.19 OpenTelemetry 前置 (#19)

定义 10 个关键 Span 和属性：

| Span | 属性 |
|------|------|
| agent.invoke | session_id, corr_id, model, prompt_length, stream |
| gateway.receive | session_id, corr_id, msg_type, version, seq |
| gateway.validate | session_id, corr_id, validation_result, error_code |
| gateway.route | session_id, corr_id, provider_name, strategy, route_result |
| provider.call | session_id, corr_id, provider_name, model, latency_ms |
| provider.stream.chunk | session_id, corr_id, seq, token_length, latency_ms |
| gateway.stream | session_id, corr_id, seq, forwarded_to |
| gateway.cancel | session_id, corr_id, cancel_reason |
| gateway.heartbeat | session_id, corr_id, last_seen_delta_ms |
| gateway.error | session_id, corr_id, error_code, error_source, recoverable |

TraceContext 支持 `trace_id`/`span_id`/`parent_span_id` 传播，`inject_into_payload` 可将追踪信息注入信封。

### 2.20 Mock LLM Server (#21)

独立 HTTP 服务器，10 种可控场景。运行时可通过 `/scenario` 端点切换场景，用于边界测试。

### 2.21 故障注入 (#22)

5 类故障：delay / mid_stream_error / duplicate_token / bad_json / partial_disconnect。每个故障在测试中有明确的预期响应和实际响应验证。

### 2.22 性能基线 (#23)

参见 `evidence/performance/baseline_20260526_190502.json`：

| 并发数 | 首 Token 延迟 (Mock) | 总耗时 (Mock) |
|--------|---------------------|---------------|
| 1 | ~0ms | ~300ms |
| 3 | ~0ms | ~900ms |
| 5 | ~0ms | ~1500ms |
| 10 | ~0ms | ~3000ms |

真实 Provider 数据见 DeepSeek 和 Ollama 证据文件。

### 2.23 并发会话隔离 (#24)

4 项验证：
- 状态机隔离：不同 session 的状态机互不影响
- Seq 隔离：不同 corr_id 的序号独立计数
- Cancel 不误伤：取消一个 session 不影响其他
- 并发 INVOKE：多个 INVOKE 并发执行不串流

### 2.24 多 Runtime 路由 (#25)

ProviderRouter 支持 runtime 策略，按 ProviderRoute.runtime 标签匹配。若运行时标签未匹配则尝试能力标签回退，最后回退到首个 Provider。

### 2.25 模型能力路由 (#26)

CapabilityRegistry + CapabilityProfile 声明式能力注册。best_match 方法通过交集计算同时满足 model、task_type、capabilities 三重过滤的最佳 Provider。

### 2.26 持久化审计 (#27)

AuditLogger 写入 JSONL 文件，每条记录一行。跨实例重启时，__post_init__ 自动回放所有 JSONL 文件重建内存索引。支持按 session_id/corr_id/event/时间范围组合查询，支持导出为 JSON 文件。

### 2.27 CLI Agent 入口 (#30)

CLIAgent 支持 invoke / cancel / heartbeat / health / metrics / chat 6 个子命令。交互模式下输入 cancel/heartbeat/metrics/quit 切换功能。所有操作展示 corr_id。

### 2.28 实验报告自动生成 (#31)

`scripts/generate_report.py` 自动运行测试、收集错误码、指标、性能数据、DeepSeek e2e 结果，并生成 Markdown 报告到 `evidence/reports/`。

### 2.29 MultiAgent 协调 (#37)

AgentProfile + AgentRegistry + DelegationRecord + MultiAgentManager。
- single 模式：单对单委派
- fan-out 模式：一对多并发委派 + asyncio.gather 聚合结果
- REST 端点：/agents, /agents/{id}, /agents/register, /delegations, /delegate/fan-out

---

## 3. 测试与异常处理验证

### 3.1 测试矩阵

| 模块 | 用例数 | 覆盖要点 | 对应目标 |
|------|--------|----------|----------|
| Schema Validation | 9 | payload 校验、版本校验、legacy 映射 | #1, #32, #33 |
| ErrorCode System | 5 | 完整性、未知码、可恢复性、超时分类 | #2 |
| SeqChecker | 5 | 顺序、跳号、回退、隔离、重置 | #5 |
| Terminal State | 4 | Done/Failed/Cancelled 后拒绝 | #6 |
| StateMachine | 6 | 正常流转、CANCEL/ERROR/TIMEOUT | #7 |
| Heartbeat | 3 | INVOKED 接受、IDLE 拒绝、last_seen | #8 |
| Cancel | 4 | 转换、终态拒绝、幂等 | #9 |
| Timeout | 4 | 首token/总任务/间隔/provider | #11 |
| Retry | 2 | 可恢复重试、不可恢复立即失败 | #3 |
| Idempotency | 4 | REJECT/REUSE/IGNORE | #4 |
| Flow Control | 4 | 队列满、限流 | #10 |
| Provider | 4 | normal/error/timeout/mid_stream | #12, #21 |
| Logging & Tracing | 5 | 层级、duration | #16, #19 |
| Metrics | 5 | 成功/失败/取消/超时/汇总 | #17 |
| Audit | 5 | 持久化、跨实例、查询、导出 | #27 |
| Security | 4 | API key、注册、脱敏 | #28 |
| Policy Filter | 4 | 空/长/脱敏 | #29 |
| Protocol Compat | 6 | legacy + 未知拒绝 | #32 |
| Version | 3 | v1/1/v99 | #33 |
| Fault Injection | 5 | 5 类故障 | #22 |
| Configuration | 4 | 加载校验 | #15 |
| Concurrent Isolation | 4 | 隔离 | #24 |
| OpenTelemetry | 3 | span/属性 | #19 |
| Integration | 5 | 完整管道 | #20 |
| Extended Integration | 9 | 边界场景 | #20 |
| Capability Routing | 8 | 注册/匹配/回退 | #26 |
| Runtime Routing | 3 | runtime/回退 | #25 |
| MultiAgent | 8 | 注册/委派/响应 | #37 |
| FanOut | 5 | 空/缺失/offline/成功/降级 | #37 |

**总计**: 141 用例，通过率 100%

---

## 4. 运行证据分析

### 4.1 测试执行结果
```bash
python -m pytest tests/test_comprehensive.py -v
# 141 passed in 1.90s
```

### 4.2 扩展目标证据
```bash
python scripts/collect_evidence.py
# evidence/extension-goals/ 下生成 JSON + TXT 证据文件
```

### 4.3 性能数据
```bash
python scripts/perf_baseline.py
# 在 concurrency=1/3/5/10 下测量 FTL 和 total duration
```

### 4.4 真实 Provider 调用证据

| Provider | 模型 | 首 Token 延迟 | 总耗时 | Chunks | 证据文件 |
|----------|------|---------------|--------|--------|----------|
| DeepSeek | deepseek-chat | 1.117s | 1.261s | 7 | evidence/deepseek-e2e-validation.json |
| Ollama | qwen2.5:0.5b | 1.426s | 1.702s | 32 | evidence/provider-call/ollama-gateway-e2e.json |

---

## 5. 扩展目标覆盖对照

### 5.1 必做档 (17 项)

| 编号 | 目标 | 实现摘要 | 代码位置 | 测试覆盖 |
|------|------|----------|----------|----------|
| 1 | 协议 Schema 校验 | Envelope Pydantic + extra="forbid" + model_validator | envelope.py:48-132 | TestSchemaValidation (9) |
| 2 | 错误码体系 | 28 注册码，6 属性/码 | errors.py | TestErrorCodeSystem (5) |
| 3 | 可恢复重试 | RetryManager 指数退避 | retry.py | TestRetry (2) |
| 4 | 幂等语义 | IdempotencyManager 4 策略 | idempotency.py | TestIdempotency (4) |
| 5 | Seq 顺序校验 | SeqChecker 按 corr_id 递增 | seq_checker.py | TestSeqChecker (5) |
| 6 | 终止后消息处理 | 终态守卫 + 日志 | state_machine.py:81-91 | TestTerminalState (4) |
| 7 | Gateway 状态机 | 6 状态 12 路径 | state_machine.py | TestStateMachine (6) |
| 8 | HEARTBEAT 处理 | last_seen 更新 + 校验 | main.py:432-457 | TestHeartbeat (3) |
| 9 | CANCEL 传播 | 本地取消 + 幂等 | main.py:390-430 | TestCancel (4) |
| 11 | 超时分类 | 4 类超时检查 | timeout.py | TestTimeout (4) |
| 14 | 本地模型部署 | Ollama + qwen2.5:0.5b | ollama_provider.py | evidence/local-model-deployment.md |
| 16 | 结构化日志 | 8 字段 JSON | logger.py | TestLoggingTracing (5) |
| 18 | 简易追踪 | corr_id 关联 | logger.py + tracing.py | TestLoggingTracing (5) |
| 20 | 自动化测试 | pytest 141 用例 | test_comprehensive.py | 全部 |
| 21 | Mock LLM Server | 10 场景可控 | mock_server.py | TestProvider (4) + TestFaultInjection (5) |
| 30 | Agent 入口 | CLI Agent 6 子命令 | cli_agent.py | 手动验证 |
| 34 | 文档质量 | 8 篇 Markdown | docs/ | — |
| 35 | AI 编程反思 | 4 轮 Prompt + 6 修改 | 07-ai-coding-reflection.md | — |
| 36 | 单 Provider LLM 调用 | DeepSeek + Ollama | openai_provider.py + ollama_provider.py | evidence/deepseek-e2e-validation.md |

### 5.2 增强扩展档 (13 项)

| 编号 | 目标 | 实现摘要 | 代码位置 | 测试覆盖 |
|------|------|----------|----------|----------|
| 3 | 可恢复重试 | 已覆盖（必做档） | retry.py | TestRetry (2) |
| 4 | 幂等语义 | 已覆盖（必做档） | idempotency.py | TestIdempotency (4) |
| 10 | 流控与背压 | BoundedQueue + RateLimiter | flow_control.py | TestFlowControl (4) |
| 12 | Provider Adapter | 4 种 Adapter + 统一接口 | adapters/ | TestProvider (4) |
| 15 | 配置化 Gateway | GatewayConfig 30+ 项 | config.py | TestConfiguration (4) |
| 17 | 指标采集 | 7 项指标 + P95 | metrics.py | TestMetrics (5) |
| 19 | OTel 前置 | 10 Span + 属性 | tracing.py | TestOpenTelemetry (3) |
| 22 | 故障注入 | 5 类故障 | mock_provider.py | TestFaultInjection (5) |
| 23 | 性能基线 | 4 并发级别 | perf_baseline.py | evidence/performance/ |
| 24 | 并发隔离 | 4 项验证 | test_comprehensive.py | TestConcurrentIsolation (4) |
| 31 | 自动报告 | generate_report.py | scripts/ | 手动验证 |
| 32 | 协议兼容性 | LEGACY_MESSAGE_MAP | envelope.py:35-42 | TestProtocolCompatibility (6) |
| 33 | 版本协商 | normalize_version | envelope.py:59-67 | TestVersion (3) |

### 5.3 终极扩展档 (7 项)

| 编号 | 目标 | 实现摘要 | 代码位置 | 测试覆盖 |
|------|------|----------|----------|----------|
| 13 | 双协议兼容 | OpenAI + Anthropic 适配器 + 差异表 | anthropic_provider.py | TestProvider (4) |
| 25 | 多 Runtime 路由 | runtime 策略 + 回退 | router.py:247-268 | TestRuntimeRouting (3) |
| 26 | 模型能力路由 | CapabilityRegistry + best_match | router.py:33-99 | TestCapabilityRouting (8) |
| 27 | 持久化审计 | JSONL + 跨实例重载 + 查询 + 导出 | audit.py | TestAudit (5) |
| 28 | 安全边界 | 4 类策略 | security.py | TestSecurity (4) |
| 29 | 策略化过滤 | 三层过滤 | policy_filter.py | TestPolicyFilter (4) |
| 37 | MultiAgent | AgentRegistry + fan-out | multi_agent.py | TestMultiAgent (8) + TestFanOut (5) |

---

## 6. 评分维度对照

### 6.1 需求分析 (10 分)
- 明确定义了 A2A_min_v1 协议的 8 种消息类型和统一信封结构
- 覆盖了流式传输、超时管理、安全边界、可观测性等非功能性需求
- 开发范围分 4 轮迭代，每轮聚焦单一主题
- 证据：docs/01-design.md, docs/06-protocol.md

### 6.2 协议设计 (20 分)
- 统一信封: 7 字段 + Pydantic 严格校验 + `extra="forbid"`
- 8 种消息类型 + payload 校验规则
- 6 状态状态机 + 12 条合法转换 + 终态不可逆
- 31 错误码体系 + 可恢复性 + 重试建议标记
- Legacy 兼容: CSD_Stream_v0 → A2A_min_v1 6 种映射 (#32)
- 双协议兼容: OpenAI-compatible vs Anthropic-compatible 差异对照表 + Gateway 统一映射 (#13)
- 版本协商: v1 接受 + 未知版本拒绝 (#33)
- 证据：docs/06-protocol.md §1-6

### 6.3 原型实现 (25 分)
- FastAPI 网关服务 + 3 种接入方式（REST / SSE / WebSocket）
- 4 种 Provider 适配器（OpenAI / Anthropic / Ollama / Mock）
- 7 种路由策略（priority / hash / round_robin / model_name / task_type / capability / runtime）
- 流式传输：AsyncIterator[StreamEvent] 逐 event 消费 → STREAM_CHUNK 信封
- Multi-Agent: AgentProfile + AgentRegistry + DelegationRecord + MultiAgentManager
- 代码位置：app/main.py, app/core/*, app/adapters/*, app/models/*

### 6.4 测试验证 (15 分)
- 141 测试用例，29 个测试类，100% 通过率
- 覆盖正常路径 + 边界场景（终态拒绝、幂等性、并发隔离、故障注入）
- 测试命令：`python -m pytest tests/test_comprehensive.py -v`
- DeepSeek 真实 Provider 端到端验证（FTL 1.117s, 7 chunks）
- Ollama 本地模型端到端验证（FTL 1.426s, 32 chunks）
- 证据：docs/04-testing.md, evidence/test-results/, evidence/provider-call/

### 6.5 运行证据 (20 分)
- 测试运行证据：evidence/test-results/
- Provider 调用证据：evidence/provider-call/
- 性能基线：evidence/performance/
- 审计日志：evidence/audit/（JSONL 持久化）
- 本地模型部署证据：evidence/local-model-deployment.md
- 扩展目标证据：evidence/extension-goals/
- 证据收集脚本：scripts/collect_evidence.py, scripts/perf_baseline.py
- 自动报告生成：scripts/generate_report.py

### 6.6 文档表达 (10 分)
- docs/01-design.md — 系统设计说明（架构、模块职责、协议设计、设计决策）
- docs/02-api.md — API 接口说明（REST/WebSocket/Multi-Agent 端点、请求示例、错误格式）
- docs/03-deploy.md — 部署说明（安装、配置、启动、Ollama、生产建议、故障排除）
- docs/04-testing.md — 测试说明（141 用例矩阵、关键场景、证据收集、复现指南）
- docs/05-issues.md — 问题记录（6 个已修复问题、4 个已知限制、10 个改进方向）
- docs/06-protocol.md — 协议说明（8 种消息类型、错误码体系、双协议兼容、版本协商）
- docs/07-ai-coding-reflection.md — AI 编程反思（4 轮 Prompt、6 个人工修改、经验总结）
- docs/08-final-report.md — 最终实验报告（含评分维度对照）
- docs/submission-checklist.md — 提交检查清单

---

## 7. 二次迭代补充：官方 A2A 兼容层

在原课程版 `A2A_min_v1` 网关已经完成后，项目新增官方 A2A HTTP+JSON 兼容层，使系统不只满足课程自定义协议要求，也能以更接近公开 A2A 协议的方式被外部 Agent 客户端发现和调用。

### 7.1 新增范围

- 新增 `/.well-known/agent-card.json`，提供 Agent Card 能力发现。
- 新增 `/message:send`，接收官方 A2A `Message`，返回标准 `Task`。
- 新增 `/message:stream`，以 SSE 返回 `StreamResponse`、状态更新和 artifact 增量。
- 新增 `/tasks/{task_id}`、`/tasks`、`/tasks/{task_id}:cancel`、`/tasks/{task_id}:subscribe`。
- 新增 `application/a2a+json` 响应类型与 `A2A-Version` 响应头。
- 新增官方 `TaskState`、`Message`、`Part`、`Artifact`、`AgentCard` 和标准错误模型。

### 7.2 实现策略

兼容层采用“边界适配”方式实现，而不是另起一套执行引擎。官方 A2A 请求进入网关后，会被转换为内部 `A2A_min_v1` Envelope，再交给既有状态机、ProviderRouter、Adapter、审计和流控模块处理。这样可以保持原项目核心能力一致，也避免两套协议实现之间出现行为分叉。

### 7.3 验收结果

- 新增 `tests/test_a2a_compat.py` 覆盖 Agent Card、消息发送、任务查询、任务列表、流式响应、标准错误和终态取消。
- 修复拆分测试中对旧 API 的引用，包括旧错误导入、旧状态机事件名、旧 Router 参数和旧 tracing 方法。
- 完整测试命令：`python -m pytest -q`。
- 综合验收命令：`python -m pytest tests/test_comprehensive.py -q`。

### 7.4 后续工作量建议

如果继续增加有工作量的扩展，优先选择持久化 Task Store、Push Notification、Extended Agent Card 鉴权增强、上游 Provider Cancel、多 Agent 官方 Skill 暴露。这些扩展都能在现有架构上继续迭代，并且有明确的代码、测试和文档产出。

---

## 8. 三次迭代补充：MultiAgent 协作增强

在官方 A2A 兼容层之后，项目继续增强 MultiAgent。原实现只支持 single delegation 和 fan-out，并且 Agent 间主要依赖 Gateway 内部 Provider 调用。本次迭代将 MultiAgent 扩展为可组合的协作编排层。

### 8.1 新增范围

- 新增 fan-in：多个 Agent 并发执行后聚合成一个最终结果。
- 新增 pipeline：按步骤顺序执行 Agent 链，前一步输出进入后一步上下文。
- 新增 planner-worker-reviewer：内置“规划-执行-审查”协作流。
- 新增跨 HTTP Agent 调用：`AgentProfile.endpoint` 存在时优先调用远端 Agent。
- 新增结果聚合策略：`json`、`concat`、`summary`。
- 新增失败策略：`partial`、`fail_fast`、`compensate`。

### 8.2 实现策略

核心实现集中在 `app/core/multi_agent.py`。通过统一的 `_execute_agent_task` 把本地 Provider 调用、远端 HTTP Agent 调用、子任务记录、并发计数和错误处理收敛到一个执行入口。上层的 fan-in、pipeline、planner-worker-reviewer 只负责编排顺序和组合结果。

### 8.3 验收结果

- 新增 `tests/test_multi_agent_enhanced.py` 覆盖 fan-in、pipeline、planner-worker-reviewer、HTTP Agent 调用和失败补偿。
- 原 `tests/test_comprehensive.py` 中 MultiAgent 与 fan-out 行为继续通过。
- 新增文档：`docs/11-multi-agent-enhancement-plan.md`、`docs/12-multi-agent-enhancement-progress.md`。

---

## 9. 四次迭代补充：工程可靠性与可观测性

本轮迭代面向工程运行质量，重点补齐取消、健康检查、故障摘除、背压和可视化证据。

### 9.1 新增范围

- 上游取消：`CANCEL` 成功进入取消状态后调用当前 Provider 的 cancel hook。
- Provider 健康检查：新增 `/providers/health` 与 `/providers/health/check`。
- 自动摘除故障 Provider：连续失败达到阈值后熔断冷却，路由跳过故障 Provider。
- 真实背压：队列满时等待空间，超时后返回 `QUEUE_FULL`，不再默认丢弃旧项。
- 可观测：新增 `/metrics/prometheus`、`/dashboard/reliability-data`、OTel Collector、Prometheus、Grafana 配置和静态 HTML dashboard。

### 9.2 验收结果

- 新增 `tests/test_reliability.py`，覆盖上游取消、熔断摘除、健康恢复、背压等待/超时、可靠性 metrics 和可观测端点。
- `tests/test_reliability.py` 与 `tests/test_comprehensive.py` 合计 148 个测试通过。
- 新增文档：`docs/13-engineering-reliability-plan.md`、`docs/14-engineering-reliability-progress.md`。
- 新增可视化证据：`evidence/visualization/reliability-dashboard.html`。
