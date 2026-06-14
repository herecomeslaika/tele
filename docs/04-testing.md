# 04 — 测试说明

## 1. 测试框架

| 项目 | 说明 |
|------|------|
| 框架 | pytest + pytest-asyncio |
| 测试文件 | `tests/test_comprehensive.py` |
| 总用例数 | 141 |
| 通过率 | 100% |

## 2. 运行测试

```bash
# 运行全部测试
python -m pytest tests/test_comprehensive.py -v

# 运行特定测试类
python -m pytest tests/test_comprehensive.py::TestStateMachine -v

# 运行特定测试方法
python -m pytest tests/test_comprehensive.py::TestStateMachine::test_normal_flow -v

# 显示详细输出
python -m pytest tests/test_comprehensive.py -v --tb=long

# 仅运行集成测试
python -m pytest tests/test_comprehensive.py::TestIntegration -v
```

---

## 3. 测试矩阵

| 测试类 | 用例数 | 覆盖要点 | 对应目标 |
|--------|--------|----------|----------|
| TestSchemaValidation | 9 | INVOKE payload 校验、版本校验、legacy 映射 | #1, #32, #33 |
| TestErrorCodeSystem | 5 | 完整性、未知码、可恢复性、超时分类 | #2 |
| TestSeqChecker | 5 | 顺序、跳号、回退、隔离、重置 | #5 |
| TestTerminalState | 4 | Done/Failed/Cancelled 后拒绝 | #6 |
| TestStateMachine | 6 | 正常流转、CANCEL/ERROR/TIMEOUT、Idle 只接受 INVOKE | #7 |
| TestHeartbeat | 3 | INVOKED 状态接受、IDLE 拒绝、last_seen 更新 | #8 |
| TestCancel | 4 | 状态转换、终态拒绝、幂等性 | #9 |
| TestTimeout | 4 | 首token/总任务/间隔/provider 四类 | #11 |
| TestRetry | 2 | 可恢复重试、不可恢复立即失败 | #3 |
| TestIdempotency | 4 | INVOKE 重复拒绝/复用、CANCEL 重复忽略、STREAM_END 重复忽略 | #4 |
| TestFlowControl | 4 | 队列 push/pop/满丢弃、限流器 | #10 |
| TestProvider | 4 | normal/error/timeout/mid_stream_error | #12, #21 |
| TestLoggingTracing | 5 | 层级、duration、collector、span 定义 | #16, #19 |
| TestMetrics | 5 | success/failure/cancel/timeout/summary | #17 |
| TestAudit | 5 | 记录查询、持久化、跨实例重载、灵活查询、导出 | #27 |
| TestSecurity | 4 | API key、agent 注册、长度检查、敏感字段屏蔽 | #28 |
| TestPolicyFilter | 4 | 空请求、过长、敏感屏蔽 | #29 |
| TestProtocolCompatibility | 6 | legacy 映射 + 未知类型拒绝 | #32 |
| TestVersion | 3 | v1/1/v99 | #33 |
| TestFaultInjection | 5 | delay/mid_stream_error/duplicate_token/bad_json/partial_disconnect | #22 |
| TestConfiguration | 4 | 默认验证、provider 配置、env 加载、策略验证 | #15 |
| TestConcurrentIsolation | 4 | 状态机隔离、seq 隔离、cancel 不影响其他、并发 invoke | #24 |
| TestOpenTelemetry | 3 | span 定义、属性、传播 | #19 |
| TestIntegration | 5 | full invoke、cancel、heartbeat、bad_request、seq error | #20 |
| TestExtendedIntegration | 9 | cancel during stream、ALREADY_CANCELLED、auth、rate limit、empty request、router priority/hash/round_robin、audit | #20 |
| TestCapabilityRouting | 8 | 注册查找、能力/模型/任务过滤、交集匹配、路由集成、回退 | #26 |
| TestRuntimeRouting | 3 | runtime 选择、回退、能力回退 | #25 |
| TestMultiAgent | 8 | 注册查找、能力/角色过滤、注销、offline排除、委派、响应更新 | #37 |
| TestFanOutDelegation | 5 | 空 targets、缺失 agent、offline agent、成功并发委派、无 router 降级 | #37 |

---

## 4. 关键测试场景详解

### 4.1 正常流式调用流程 (#36)

```
步骤:
  1. 发送 INVOKE → 状态 Invoked
  2. 收到 STREAM_CHUNK → 状态 Streaming
  3. 收到多个 STREAM_CHUNK → 状态保持 Streaming
  4. 收到 STREAM_END → 状态 Done

验证点:
  - 每个 STREAM_CHUNK 的 seq 从 1 严格递增
  - session_id 和 corr_id 在所有消息中一致
  - STREAM_END.payload.reason = "stop" 或 "completed"
  - Metrics 记录 success_count += 1, first_token_latency 和 total_duration
  - Audit 记录 INVOKE 和 STREAM_END 两个事件
```

测试用例：`TestIntegration.test_full_invoke_pipeline`

### 4.2 取消传播 (#9)

```
步骤:
  1. 发送 INVOKE → 状态 Invoked
  2. 发送 CANCEL → 状态 Cancelled
  3. 重复 CANCEL → 返回 ALREADY_CANCELLED (非 MSG_AFTER_TERMINAL)

验证点:
  - CANCEL 在 Invoked 和 Streaming 状态均可到达 Cancelled
  - 重复 CANCEL 返回 ALREADY_CANCELLED 错误码
  - 取消后后续 STREAM_CHUNK 被丢弃（Gateway 检查 sm.state == CANCELLED）
  - Metrics 记录 cancel_count += 1
  - Audit 记录 CANCEL 事件
```

测试用例：`TestCancel.test_cancel_transitions`, `TestCancel.test_cancel_idempotency`

### 4.3 终态后消息拒绝 (#6)

```
步骤:
  1. 会话到达 Done/Failed/Cancelled 终态
  2. 发送后续 STREAM_CHUNK → 返回 MSG_AFTER_TERMINAL
  3. 发送后续 STREAM_END → 返回 MSG_AFTER_TERMINAL

验证点:
  - 状态机终态守卫生效（所有事件被拒绝）
  - Gateway 日志中记录 terminal-state-reject warning
  - 终态后消息不会改变状态机状态
```

测试用例：`TestTerminalState.test_done_rejects_all`, `TestTerminalState.test_failed_rejects_all`, `TestTerminalState.test_cancelled_rejects_all`

### 4.4 超时分类 (#11)

四类超时的测试覆盖：

| 超时类型 | 错误码 | 状态转换 | 可恢复 |
|----------|--------|----------|--------|
| 首 Token 超时 | FIRST_TOKEN_TIMEOUT | → Failed | 是 |
| token 间隔超时 | TOKEN_INTERVAL_TIMEOUT | → Failed | 是 |
| 总任务超时 | TOTAL_TASK_TIMEOUT | → Failed | 否 |
| Provider 响应超时 | PROVIDER_RESPONSE_TIMEOUT | → Failed | 是 |

测试用例：`TestTimeout.test_first_token_timeout`, `TestTimeout.test_token_interval_timeout`, `TestTimeout.test_total_task_timeout`, `TestTimeout.test_provider_response_timeout`

### 4.5 序号校验 (#5)

```
正常序列:  seq=1, seq=2, seq=3 → OK
跳号:      seq=1, seq=5 → SEQ_GAP (可恢复)
回退:      seq=3, seq=1 → SEQ_ROLLBACK (不可恢复)
重复:      seq=1, seq=1 → SEQ_DUPLICATE (不可恢复)
隔离:      不同 corr_id 的 seq 独立计数
```

测试用例：`TestSeqChecker.test_sequential_ok`, `TestSeqChecker.test_gap`, `TestSeqChecker.test_rollback`, `TestSeqChecker.test_duplicate`, `TestSeqChecker.test_isolation`

### 4.6 Multi-Agent 委派 (#37)

```
步骤:
  1. 注册 Agent 到 Registry (AgentProfile + 能力/角色)
  2. 发送 AGENT_DELEGATE 指定 target_agent + task
  3. MultiAgentManager 验证 target 存在
  4. 创建 DelegationRecord → 路由到 Provider
  5. 返回 AGENT_RESPONSE 包含 delegation_id + result

Fan-out:
  1. 发送 AGENT_DELEGATE (pattern="fan-out", target_agents=[...])
  2. 每个 target 独立委派 → asyncio.gather 并发执行
  3. 聚合所有结果 → 返回 AGENT_RESPONSE (sub_count=N)
```

测试用例：`TestMultiAgent.*`, `TestFanOutDelegation.*`

### 4.7 并发会话隔离 (#24)

```
验证点:
  - 不同 session_id 的状态机不互相影响
  - 不同 corr_id 的 SeqChecker 计数独立
  - Cancel 一个 session 不影响其他 session
  - 多个 INVOKE 并发执行不会串流 token
```

测试用例：`TestConcurrentIsolation.*`

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
- `evidence/extension-goals/` — 扩展目标证据（JSON + TXT）
- `evidence/performance/` — 性能基线数据（JSON）
- `evidence/audit/` — 审计日志（JSONL）
- `evidence/test-results/` — 测试结果文本
- `evidence/provider-call/` — Provider 调用证据
  - `deepseek-e2e-validation.json` — DeepSeek 端到端验证
  - `deepseek-e2e-validation.md` — 可读版本
  - `ollama-gateway-e2e.json` — Ollama Gateway 端到端验证

---

## 6. 复现指南

教师复现实验流程的完整步骤：

```bash
# Step 1: 安装依赖
pip install -r requirements.txt

# Step 2: 配置环境
cp config/.env.example config/.env
# 编辑 config/.env，填入至少一个 Provider API Key

# Step 3: 运行测试
python -m pytest tests/test_comprehensive.py -v
# 预期结果：141 passed

# Step 4: 启动网关
python -m app.main

# Step 5: CLI Agent 交互
python -m app.cli_agent chat

# Step 6: 启动 Mock Server
python -m app.mock_server --port 9000

# Step 7: 配置 Gateway 使用 Mock Server
# 编辑 .env：PROVIDER1_ENDPOINT=http://localhost:9000/v1

# Step 8: 收集证据
python scripts/collect_evidence.py

# Step 9: 性能基线
python scripts/perf_baseline.py

# Step 10: 生成实验报告
python scripts/generate_report.py
```

**本地模型部署（可选）**：

```bash
# 安装 Ollama
ollama serve

# 拉取模型
ollama pull qwen2.5:0.5b

# 验证
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"Hello"}],"max_tokens":64,"stream":false}'
```
