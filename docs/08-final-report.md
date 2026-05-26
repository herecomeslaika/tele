# 08 — 最终实验报告

## 1. 需求与范围

### 1.1 项目目标
[填写：简述 A2A_min_v1 协议网关的核心目标，例如：实现一个具备协议校验、状态机控制、多 Provider 路由和追踪能力的 Agent-to-Agent 通信网关。]

### 1.2 协议定义
- 协议名称：A2A_min_v1
- 消息类型：INVOKE, STREAM_CHUNK, STREAM_END, ERROR, CANCEL, HEARTBEAT
- 统一信封字段：version, type, session_id, corr_id, seq, timestamp, payload

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
- 校验：`field_validator` 拦截非法 `type`，空字符串校验

### 2.2 错误码体系 (ErrorCode)
| 错误码 | 含义 |
|--------|------|
| INVALID_MESSAGE_TYPE | 消息类型不在六类核心消息中 |
| MISSING_CORRELATION_FIELDS | 缺少 session_id 或 corr_id |
| OUT_OF_ORDER_STREAM | STREAM_CHUNK seq 跳号/回退/重复 |
| PROVIDER_TIMEOUT | 提供商整体超时 |
| FIRST_TOKEN_TIMEOUT | 首 Token 超时 |
| TOKEN_INTERVAL_TIMEOUT | Token 间隔超时 |
| MESSAGE_AFTER_TERMINAL | 终态后到达的迟到消息 |
| ILLEGAL_STATE_TRANSITION | 非法状态流转 |
| SESSION_NOT_FOUND | 会话不存在 |

### 2.3 序号校验器 (SeqChecker)
- 按 `corr_id` 隔离，严格单调递增校验
- 检测跳号、回退、重复，返回 `SeqResult` 结构化结果

### 2.4 状态机引擎 (GatewayStateMachine)
- 六状态：Idle → Invoked → Streaming → Done / Failed / Cancelled
- 转换表驱动（12 条合法路径），终态不可逆
- CANCEL 主动切断，终态后拒绝迟到 STREAM_CHUNK

### 2.5 心跳与超时 (TimeoutChecker)
- 三类超时：首 Token / Token 间隔 / 提供商整体
- HEARTBEAT 更新 `last_seen`，超时生成结构化 ERROR 信封

---

## 3. 测试与异常处理验证

### 3.1 测试矩阵
| 模块 | 测试文件 | 用例数 | 覆盖要点 |
|------|----------|--------|----------|
| ErrorCode | test_errors.py | 4 | 错误码完整性、ERROR 信封生成 |
| SeqChecker | test_seq_checker.py | 11 | 顺序、跳号、回退、隔离 |
| StateMachine | test_state_machine.py | 27 | 正常流转、终态拒绝、CANCEL、TIMEOUT |
| TimeoutChecker | test_timeout.py | 9 | 三类超时、心跳更新 |
| 集成测试 | test_integration.py | 14 | 正常/超时/错误三场景 + Logger 验证 |
| ProviderRouter | test_router.py | 10 | 优先级/哈希/轮询路由、Failover |
| TraceContext | test_tracing.py | 10 | 链路传播、Span 链、收集器隔离 |

### 3.2 边界场景验证
- [填写：列出关键的边界测试结果，如"终态后迟到 STREAM_CHUNK 被拒绝并记录 warning 日志"]

---

## 4. 运行证据分析

### 4.1 测试执行结果
[填写：粘贴 `pytest tests/ -v` 的关键输出，或引用 evidence/ 目录下的日志文件]

### 4.2 扩展目标证据
[填写：粘贴 `scripts/collect_evidence.py` 的输出，或引用 evidence/extension-goals/ 下的文件]

### 4.3 性能数据
[填写：如有 latency_ms 日志数据，在此分析]

---

## 5. 扩展目标成果展示

### 5.1 扩展目标 1：多 Provider 路由隔离
- 实现内容：`ProviderRouter` 支持三种路由策略（priority/hash/round_robin）+ 自动 Failover
- 代码位置：`app/adapters/router.py`
- 测试覆盖：10 用例，含 Failover 熔断与 Provider 状态隔离验证

### 5.2 扩展目标 2：OpenTelemetry 简易追踪链路
- 实现内容：`TraceContext` + `TraceCollector`，支持 trace_id/span_id 传播与 span 链重建
- 代码位置：`app/core/tracing.py`
- 测试覆盖：10 用例，含多级 span 链、trace 隔离、payload 注入/提取
