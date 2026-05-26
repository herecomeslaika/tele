# A2A_min_v1 — Submission Checklist

## 核心功能

- [x] 统一信封 (Envelope) 定义与 Schema 校验
- [x] 六类核心消息类型 (INVOKE, STREAM_CHUNK, STREAM_END, ERROR, CANCEL, HEARTBEAT)
- [x] 错误码体系 (ErrorCode) 与结构化 ERROR 工厂
- [x] 序号校验器 (SeqChecker) — corr_id 隔离、跳号/回退/重复拦截
- [x] 状态机引擎 (GatewayStateMachine) — 六状态、转换表驱动、终态不可逆
- [x] CANCEL 主动切断机制
- [x] 心跳 (HEARTBEAT) 与 last_seen 时间戳更新
- [x] 超时分类器 (TimeoutChecker) — 首 Token / Token 间隔 / 提供商整体

## Provider 适配层

- [x] ProviderAdapter 抽象接口 (invoke/stream/cancel)
- [x] RealProviderAdapter — DeepSeek/OpenAI 兼容 API 流式调用
- [x] MockProviderAdapter — 多场景注入 (normal/delay/error/timeout)

## 可观测性

- [x] StructuredLogger — JSON 格式、8 个强制字段
- [x] 统一 ERROR 信封输出（非堆栈打印）

## 扩展目标 1：多 Provider 路由隔离

- [x] ProviderRouter — 三种路由策略 (priority/hash/round_robin)
- [x] 自动 Failover — 主 Provider 出错时切换到备用
- [x] Provider 状态隔离 — 不同路由之间无共享状态泄露
- [x] 测试覆盖 (10 用例)

## 扩展目标 2：OpenTelemetry 简易追踪链路

- [x] TraceContext — trace_id/span_id/parent_span_id 传播
- [x] TraceCollector — Span 链记录与重建
- [x] Envelope payload 注入/提取 trace 字段
- [x] 测试覆盖 (10 用例)

## 测试与证据

- [x] 单元测试 — SeqChecker, StateMachine, ErrorCode, TimeoutChecker
- [x] 集成测试 — 正常调用 / 超时熔断 / 异常传递 三场景
- [x] 扩展目标测试 — Router, Tracing
- [x] 总用例数 ≥ 90，通过率 100%
- [x] 证据收集脚本 (scripts/collect_evidence.py)
- [x] evidence/extension-goals/ 输出目录

## 文档

- [x] 08-final-report.md — 最终报告骨架
- [x] 07-ai-coding-reflection.md — AI 编程反思模板
- [x] submission-checklist.md — 提交核对清单
- [x] config/.env.example — 环境配置模板

## 工程规范

- [x] 目录结构包含 docs, tests, config, app, evidence
- [x] .gitignore 排除 __pycache__, .env, 日志文件
- [x] requirements.txt 声明所有依赖
- [x] 未修改核心业务逻辑 (StateMachine/SeqChecker) 来适配扩展
