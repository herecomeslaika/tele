# 04 — 测试说明

## 1. 测试框架

- **框架**: pytest + pytest-asyncio
- **测试文件**: `tests/test_comprehensive.py`
- **总用例数**: 136
- **通过率**: 100%

## 2. 运行测试

```bash
# 运行全部测试
python -m pytest tests/test_comprehensive.py -v

# 运行特定测试类
python -m pytest tests/test_comprehensive.py::TestStateMachine -v

# 运行特定测试方法
python -m pytest tests/test_comprehensive.py::TestStateMachine::test_normal_flow -v
```

---

## 3. 测试矩阵

| 测试类 | 用例数 | 覆盖要点 |
|--------|--------|----------|
| TestSchemaValidation | 9 | INVOKE payload 校验、版本校验、legacy 映射 |
| TestErrorCodeSystem | 5 | 完整性、未知码、可恢复性、超时分类 |
| TestSeqChecker | 5 | 顺序、跳号、回退、隔离、重置 |
| TestTerminalState | 4 | Done/Failed/Cancelled 后拒绝 |
| TestStateMachine | 6 | 正常流转、CANCEL/ERROR/TIMEOUT、Idle 只接受 INVOKE |
| TestHeartbeat | 3 | INVOKED 状态接受、IDLE 拒绝、last_seen 更新 |
| TestCancel | 4 | 状态转换、终态拒绝、幂等性 |
| TestTimeout | 4 | 首token/总任务/间隔/provider 四类 |
| TestRetry | 2 | 可恢复重试、不可恢复立即失败 |
| TestIdempotency | 4 | INVOKE 重复拒绝/复用、CANCEL 重复忽略、STREAM_END 重复忽略 |
| TestFlowControl | 4 | 队列 push/pop/满丢弃、限流器 |
| TestProvider | 4 | normal/error/timeout/mid_stream_error |
| TestLoggingTracing | 5 | 层级、duration、collector、span 定义 |
| TestMetrics | 5 | success/failure/cancel/timeout/summary |
| TestAudit | 5 | 记录查询、持久化、跨实例重载、灵活查询、导出 |
| TestSecurity | 4 | API key、agent 注册、长度检查、敏感字段屏蔽 |
| TestPolicyFilter | 4 | 空请求、过长、敏感屏蔽 |
| TestProtocolCompatibility | 6 | legacy 映射 + 未知类型拒绝 |
| TestVersion | 3 | v1/1/v99 |
| TestFaultInjection | 5 | delay/mid_stream_error/duplicate_token/bad_json/partial_disconnect |
| TestConfiguration | 4 | 默认验证、provider 配置、env 加载、策略验证 |
| TestConcurrentIsolation | 4 | 状态机隔离、seq 隔离、cancel 不影响其他、并发 invoke |
| TestOpenTelemetry | 3 | span 定义、属性、传播 |
| TestIntegration | 5 | full invoke、cancel、heartbeat、bad_request、seq error |
| TestExtendedIntegration | 9 | cancel during stream、ALREADY_CANCELLED、auth、rate limit、empty request、router priority/hash/round_robin、audit |
| TestCapabilityRouting | 8 | 注册查找、能力/模型/任务过滤、交集匹配、路由集成、回退 |
| TestRuntimeRouting | 3 | runtime 路由选择、回退、能力回退 |
| TestMultiAgent | 8 | 注册查找、能力/角色过滤、注销、offline 排除、委派、响应更新 |

---

## 4. 关键测试场景

### 4.1 正常流式调用流程
1. 发送 INVOKE → 状态 Invoked
2. 收到 STREAM_CHUNK → 状态 Streaming
3. 收到多个 STREAM_CHUNK → 状态保持 Streaming
4. 收到 STREAM_END → 状态 Done

### 4.2 取消传播
1. 发送 INVOKE → 状态 Invoked
2. 发送 CANCEL → 状态 Cancelled
3. 重复 CANCEL → 返回 ALREADY_CANCELLED

### 4.3 终态后消息拒绝
1. 会话到达 Done/Failed/Cancelled 终态
2. 后续任何消息被拒绝，返回 MSG_AFTER_TERMINAL

### 4.4 超时分类
- FIRST_TOKEN_TIMEOUT: INVOKE 后首 token 未到达
- TOKEN_INTERVAL_TIMEOUT: 两个 token 间隔过长
- TOTAL_TASK_TIMEOUT: 总任务时间超限
- PROVIDER_RESPONSE_TIMEOUT: Provider 未响应

### 4.5 Multi-Agent 委派
1. 注册 Agent 到 Registry
2. 发送 AGENT_DELEGATE 指定 target_agent + task
3. MultiAgentManager 验证 target 存在 → 创建 DelegationRecord → 路由到 Provider
4. 返回 AGENT_RESPONSE 包含 delegation_id + result

---

## 5. 证据收集

```bash
# 运行测试并收集证据
python scripts/collect_evidence.py

# 性能基线
python scripts/perf_baseline.py

# 自动生成实验报告
python scripts/generate_report.py
```

证据输出位置：
- `evidence/extension-goals/` — 扩展目标证据
- `evidence/performance/` — 性能基线数据
- `evidence/audit/` — 审计日志
- `evidence/test-results/` — 测试结果
- `evidence/provider-call/` — Provider 调用证据
