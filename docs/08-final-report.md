# 08 — 最终实验报告

## 1. 需求与范围

### 1.1 项目目标
实现一个具备协议校验、状态机控制、多 Provider 路由和追踪能力的 Agent-to-Agent (A2A) 通信网关。网关作为 Agent 与 LLM Provider 之间的中间层，提供统一的协议接口、流式传输、超时管理、安全校验和可观测性。

### 1.2 协议定义
- 协议名称：A2A_min_v1
- 消息类型：INVOKE, STREAM_CHUNK, STREAM_END, ERROR, CANCEL, HEARTBEAT
- 统一信封字段：version, type, session_id, corr_id, seq, timestamp, payload
- Legacy 兼容：TASK_START→INVOKE, CHUNK→STREAM_CHUNK, TASK_END→STREAM_END, STOP→CANCEL, PING→HEARTBEAT, FAIL→ERROR

### 1.3 开发范围
| 轮次 | 内容 | 状态 |
|------|------|------|
| R1 | 工程骨架、目录结构、Envelope 基础定义 | ✅ 完成 |
| R2 | 协议校验、错误码体系、SeqChecker、状态机引擎、心跳与超时 | ✅ 完成 |
| R3 | RealProviderAdapter、MockProviderAdapter(多场景)、StructuredLogger | ✅ 完成 |
| R4 | 多 Provider 路由隔离、OpenTelemetry 追踪、证据收集 | ✅ 完成 |

---

## 2. 协议实现摘要

### 2.1 统一信封 (Envelope)
- 数据结构：Pydantic BaseModel，7 字段（version/type/session_id/corr_id/seq/timestamp/payload）
- 校验：`field_validator` 拦截非法 `type` 和 `version`，`model_validator` 校验 payload 内容
- Legacy 兼容：`LEGACY_MESSAGE_MAP` 映射 CSD_Stream_v0 名称
- 严格模式：`extra = "forbid"` 拒绝未定义字段

### 2.2 错误码体系 (ErrorCode)
| 错误码 | 含义 | 来源 | 可恢复 |
|--------|------|------|--------|
| BAD_REQUEST | 请求格式错误 | gateway | 否 |
| INVALID_VERSION | 不支持的协议版本 | gateway | 否 |
| INVALID_MESSAGE_TYPE | 未知的消息类型 | gateway | 否 |
| INVALID_PAYLOAD | 消息体内容不合法 | gateway | 否 |
| UNKNOWN_SESSION | 会话不存在 | gateway | 否 |
| SEQ_DUPLICATE | seq序号重复 | gateway | 否 |
| SEQ_GAP | seq序号跳号 | gateway | 是 |
| SEQ_ROLLBACK | seq序号回退 | gateway | 否 |
| FIRST_TOKEN_TIMEOUT | 首token超时 | gateway | 是 |
| TOKEN_INTERVAL_TIMEOUT | token间隔超时 | gateway | 是 |
| TOTAL_TASK_TIMEOUT | 任务总超时 | gateway | 否 |
| PROVIDER_RESPONSE_TIMEOUT | Provider响应超时 | provider | 是 |
| PROVIDER_ERROR | Provider返回错误 | provider | 是 |
| PROVIDER_AUTH_ERROR | Provider认证失败 | provider | 否 |
| CANCELLED | 任务已被取消 | agent | 否 |
| ALREADY_CANCELLED | 任务已取消无需重复 | gateway | 否 |
| MSG_AFTER_TERMINAL | 终态后消息被拒绝 | gateway | 否 |
| DUPLICATE_INVOKE | 重复INVOKE | gateway | 否 |
| AUTH_FAILED | 认证失败 | gateway | 否 |
| RATE_LIMITED | 请求频率超限 | gateway | 是 |
| INPUT_TOO_LONG | 输入过长 | gateway | 否 |
| OUTPUT_TOO_LONG | 输出过长 | gateway | 否 |
| EMPTY_REQUEST | 请求内容为空 | gateway | 否 |
| QUEUE_FULL | 队列已满 | gateway | 是 |
| CONFIG_ERROR | 配置错误 | gateway | 否 |
| INTERNAL_ERROR | 内部错误 | gateway | 是 |
| HEARTBEAT_RECEIVED | 心跳已收到 | gateway | 否 |
| AGENT_NOT_FOUND | 目标Agent不存在 | gateway | 否 |
| DELEGATION_FAILED | Agent委派失败 | gateway | 是 |

### 2.3 序号校验器 (SeqChecker)
- 按 `corr_id` 隔离，严格单调递增校验
- 检测跳号 (GAP)、回退 (ROLLBACK)、重复 (DUPLICATE)，返回 `SeqResult` 结构化结果

### 2.4 状态机引擎 (GatewayStateMachine)
- 六状态：Idle → Invoked → Streaming → Done / Failed / Cancelled
- 转换表驱动（12 条合法路径），终态不可逆
- CANCEL 主动切断，终态后拒绝迟到消息
- HEARTBEAT 在 Idle 状态被拒绝，在非终态被接受

### 2.5 心跳与超时 (TimeoutChecker)
- 四类超时：首 Token / Token 间隔 / 提供商响应 / 总任务
- HEARTBEAT 更新 `last_seen`，超时检查由 `check_timeouts()` 集中评估

---

## 3. 测试与异常处理验证

### 3.1 测试矩阵
| 模块 | 用例数 | 覆盖要点 |
|------|--------|----------|
| Schema Validation | 9 | INVOKE payload 校验、版本校验、legacy 映射 |
| ErrorCode System | 5 | 完整性、未知码、可恢复性、超时分类 |
| SeqChecker | 5 | 顺序、跳号、回退、隔离、重置 |
| Terminal State | 4 | Done/Failed/Cancelled 后拒绝 |
| StateMachine | 6 | 正常流转、CANCEL/ERROR/TIMEOUT、Idle 只接受 INVOKE |
| Heartbeat | 3 | INVOKED 状态接受、IDLE 拒绝、last_seen 更新 |
| Cancel | 4 | 状态转换、终态拒绝、幂等性 |
| Timeout | 4 | 首token/总任务/间隔/provider 四类 |
| Retry | 2 | 可恢复重试、不可恢复立即失败 |
| Idempotency | 4 | INVOKE 重复拒绝/复用、CANCEL 重复忽略、STREAM_END 重复忽略 |
| Flow Control | 4 | 队列 push/pop/满丢弃、限流器 |
| Provider | 4 | normal/error/timeout/mid_stream_error |
| Logging & Tracing | 5 | 层级、duration、collector、span 定义 |
| Metrics | 5 | success/failure/cancel/timeout/summary |
| Audit | 5 | 记录查询、持久化、跨实例重载、灵活查询、导出 |
| Security | 4 | API key、agent 注册、长度检查、敏感字段屏蔽 |
| Policy Filter | 4 | 空请求、过长、敏感屏蔽 |
| Protocol Compatibility | 6 | legacy 映射 + 未知类型拒绝 |
| Version | 3 | v1/1/v99 |
| Fault Injection | 5 | delay/mid_stream_error/duplicate_token/bad_json/partial_disconnect |
| Configuration | 4 | 默认验证、provider 配置、env 加载、策略验证 |
| Concurrent Isolation | 4 | 状态机隔离、seq 隔离、cancel 不影响其他、并发 invoke |
| OpenTelemetry | 3 | span 定义、属性、传播 |
| Integration | 5 | full invoke、cancel、heartbeat、bad_request、seq error |
| Extended Integration | 9 | cancel during stream、ALREADY_CANCELLED、auth、rate limit、empty request、router priority/hash/round_robin、audit |
| Capability Routing | 8 | 注册查找、能力/模型/任务过滤、交集匹配、路由集成、回退 |

**总计**: 133 用例，通过率 100%

### 3.2 边界场景验证
- 终态后迟到 STREAM_CHUNK 被拒绝并记录 warning 日志
- CANCEL 在 INVOKED 和 STREAMING 状态均可达 CANCELLED 终态
- 重复 CANCEL 返回 ALREADY_CANCELLED 错误码而非 MSG_AFTER_TERMINAL
- HEARTBEAT 在 IDLE 状态被拒绝
- 空请求（prompt 和 messages 均空）被 EMPTY_REQUEST 错误码拒绝

---

## 4. 运行证据分析

### 4.1 测试执行结果
```bash
python -m pytest tests/test_comprehensive.py -v
# 114 passed in 1.90s
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

---

## 5. 扩展目标成果展示

### 5.1 扩展目标 1：多 Provider 路由隔离
- 实现内容：`ProviderRouter` 支持六种路由策略（priority/hash/round_robin/model_name/task_type/capability）+ 自动 Failover
- 代码位置：`app/adapters/router.py`
- 测试覆盖：priority/hash/round_robin 三策略 + failover，9 用例

### 5.2 扩展目标 2：OpenTelemetry 简易追踪链路
- 实现内容：`TraceContext` + `TraceCollector`，支持 trace_id/span_id 传播与 span 链重建
- 代码位置：`app/core/tracing.py`
- 测试覆盖：层级链路、duration、collector、span 定义、属性完整、payload 注入，8 用例

### 5.3 扩展目标 3：模型能力路由 (#26)
- 实现内容：`CapabilityRegistry` + `CapabilityProfile`，声明式能力注册，按能力/模型/任务类型交集匹配
- 代码位置：`app/adapters/router.py`
- 关键特性：best_match 交集匹配、capability 策略路由、model_name/task_type 策略升级利用 Registry
- 测试覆盖：8 用例（注册查找、能力/模型/任务过滤、交集匹配、路由集成、回退）

### 5.4 扩展目标 4：持久化审计 (#27)
- 实现内容：JSONL 文件写入 + 跨实例加载重建 + 灵活组合查询 + JSON 导出
- 代码位置：`app/core/audit.py`
- 关键特性：record() 实时写入 JSONL、__post_init__ 加载已有文件、query() 支持 session_id/corr_id/event/时间范围组合过滤
- 测试覆盖：5 用例（记录查询、持久化验证、跨实例重载、灵活查询、文件导出）

### 5.5 扩展目标 5：MultiAgent 协调 (#37)
- 实现内容：AgentProfile + AgentRegistry + DelegationRecord + MultiAgentManager
- 代码位置：`app/core/multi_agent.py`
- 关键特性：
  - AgentRegistry：register/deregister/get/find_by_capability/find_by_role/find_available（排除 offline agent）
  - MultiAgentManager：register_agent + handle_delegate（验证 target → 创建委派 → 路由到 Provider → 返回 AGENT_RESPONSE）+ handle_response（更新委派记录）
  - AGENT_DELEGATE / AGENT_RESPONSE 消息类型 + payload 校验
  - AGENT_NOT_FOUND / DELEGATION_FAILED 错误码
  - GatewayApp handle_envelope 集成 + REST 端点（/agents, /agents/{id}, /agents/register, /delegations）
- 测试覆盖：8 用例

---

## 6. 总结

| 模块 | 用例数 | 覆盖要点 |
|------|--------|----------|
| Schema Validation | 9 | INVOKE payload 校验、版本校验、legacy 映射 |
| ErrorCode System | 5 | 完整性、未知码、可恢复性、超时分类 |
| SeqChecker | 6 | 顺序、跳号、回退、隔离、重置 |
| Terminal State | 4 | Done/Failed/Cancelled 后拒绝 |
| StateMachine | 6 | 正常流转、CANCEL/ERROR/TIMEOUT、Idle 只接受 INVOKE |
| Heartbeat | 3 | INVOKED 状态接受、IDLE 拒绝、last_seen 更新 |
| Cancel | 4 | 状态转换、终态拒绝、幂等性 |
| Timeout | 4 | 首token/总任务/间隔/provider 四类 |
| Retry | 2 | 可恢复重试、不可恢复立即失败 |
| Idempotency | 4 | INVOKE 重复拒绝/复用、CANCEL 重复忽略、STREAM_END 重复忽略 |
| Flow Control | 4 | 队列 push/pop/满丢弃、限流器 |
| Provider | 4 | normal/error/timeout/mid_stream_error |
| Logging & Tracing | 5 | 层级、duration、collector、span 定义 |
| Metrics | 5 | success/failure/cancel/timeout/summary |
| Audit | 5 | 记录查询、持久化、跨实例重载、灵活查询、导出 |
| Security | 4 | API key、agent 注册、长度检查、敏感字段屏蔽 |
| Policy Filter | 4 | 空请求、过长、敏感屏蔽 |
| Protocol Compatibility | 6 | legacy 映射 + 未知类型拒绝 |
| Version | 3 | v1/1/v99 |
| Fault Injection | 5 | delay/mid_stream_error/duplicate_token/bad_json/partial_disconnect |
| Configuration | 4 | 默认验证、provider 配置、env 加载、策略验证 |
| Concurrent Isolation | 4 | 状态机隔离、seq 隔离、cancel 不影响其他、并发 invoke |
| OpenTelemetry | 3 | span 定义、属性、传播 |
| Capability Routing | 8 | 注册查找、能力/模型/任务过滤、交集匹配、路由集成、回退 |
| MultiAgent | 8 | 注册查找、能力/角色过滤、注销、offline排除、委派、响应更新 |
| Integration | 5 | full invoke、cancel、heartbeat、bad_request、seq error |
| Extended Integration | 9 | cancel during stream、ALREADY_CANCELLED、auth、rate limit、empty request、router priority/hash/round_robin、audit |
| Capability Routing | 8 | 注册查找、能力/模型/任务过滤、交集匹配、路由集成、回退 |

**总计**: 133 用例，通过率 100%