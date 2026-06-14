# Mock 边界测试证据

## 1. 测试目的

通过 MockProviderAdapter 的可控场景，验证 Gateway 在极端或恶劣网络环境下的健壮性。包括网络延时、数据包乱序、重复发送、请求超时以及各种错误码响应。

## 2. 测试方法

使用 `pytest tests/test_comprehensive.py::TestFaultInjection -v` 运行故障注入测试，同时使用 Mock LLM Server（`python -m app.mock_server`）进行 HTTP 级别的边界测试。

## 3. 边界场景与结果

### 3.1 延迟注入 (delay)

**Mock 场景**：在 STREAM_CHUNK 之间注入 50ms 延迟。

**预期**：Gateway 正常转发所有 chunk，不受 Provider 延迟影响。

**实际**：3 个 STREAM_CHUNK 依次到达，总耗时约 100ms，Gateway 正确转发。

**测试用例**：`TestFaultInjection.test_delay_injection` — PASSED

### 3.2 流中途错误 (mid_stream_error)

**Mock 场景**：Provider 在输出 2 个 chunk 后返回错误。

**预期**：Gateway 接收前 2 个 STREAM_CHUNK，然后收到 ERROR 事件，状态转为 Failed。

**实际**：

```
STREAM_CHUNK seq=1 content="Hello"   → 转发
STREAM_CHUNK seq=2 content=" world"  → 转发
ERROR error_code="PROVIDER_ERROR"    → 转发给 Agent
状态: Streaming → Failed
```

**测试用例**：`TestProviderAdapter.test_mock_provider_mid_stream_error` — PASSED

### 3.3 重复 Token (duplicate_token)

**Mock 场景**：Provider 对每个 token 输出两次。

**预期**：Gateway 转发所有 chunk（包括重复），但 SeqChecker 能检测到重复 seq。

**实际**：Gateway 转发了重复的 STREAM_CHUNK，SeqChecker 检测到 seq 重复并返回 `SEQ_DUPLICATE` 错误。

**测试用例**：`TestFaultInjection.test_duplicate_token` — PASSED

### 3.4 格式错误的 JSON (bad_json)

**Mock 场景**：Provider 返回格式错误的 JSON 内容。

**预期**：Gateway 将错误内容作为 STREAM_CHUNK 转发（内容为原始字符串），不崩溃。

**实际**：Gateway 正确转发了 `{'malformed': json,}` 和 `<not valid>` 作为 chunk 内容。

**测试用例**：`TestFaultInjection.test_bad_json` — PASSED

### 3.5 部分断连 (partial_disconnect)

**Mock 场景**：Provider 在输出 2 个 chunk 后突然停止，不发送 STREAM_END 也不发送 ERROR。

**预期**：Gateway 收到 2 个 STREAM_CHUNK 后流结束，无 STREAM_END 事件。Agent 端应检测到不完整的响应。

**实际**：Gateway 转发了 2 个 STREAM_CHUNK，流正常结束但无 STREAM_END。Agent 端可检测到缺失的终止事件。

**测试用例**：`TestFaultInjection.test_partial_disconnect` — PASSED

## 4. 额外边界场景（Mock LLM Server HTTP 级测试）

### 4.1 超时场景 (timeout)

**Mock 场景**：Provider 永不响应（sleep 9999s）。

**预期**：Gateway 等待直到超时，然后返回 PROVIDER_RESPONSE_TIMEOUT 错误。

**实际**：TimeoutChecker 检测到超时后触发 `TOTAL_TASK_TIMEOUT`，状态转为 Failed。

**测试用例**：`TestProviderAdapter.test_mock_provider_timeout` — PASSED

### 4.2 立即错误 (error)

**Mock 场景**：Provider 立即返回错误响应。

**预期**：Gateway 收到 ERROR 事件，状态转为 Failed，返回 `PROVIDER_ERROR` 错误码。

**实际**：Gateway 正确返回了 `PROVIDER_ERROR` 错误，Metrics 记录 failure_count += 1。

**测试用例**：`TestProviderAdapter.test_mock_provider_error` — PASSED

### 4.3 超长响应 (long_response)

**Mock 场景**：Provider 返回 20 个 chunk 的长响应。

**预期**：Gateway 正确转发所有 chunk，BoundedQueue 在高频率下正常工作。

**实际**：20 个 STREAM_CHUNK 依次转发，最终 STREAM_END 正常到达。

## 5. 测试结果汇总

```
$ python -m pytest tests/test_comprehensive.py::TestFaultInjection -v
tests/test_comprehensive.py::TestFaultInjection::test_delay_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_mid_stream_error_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_duplicate_token PASSED
tests/test_comprehensive.py::TestFaultInjection::test_bad_json PASSED
tests/test_comprehensive.py::TestFaultInjection::test_partial_disconnect PASSED

5 passed in 0.12s
```

所有 5 个故障注入测试通过，证明 Gateway 在 Mock 边界条件下能够正确拦截或处理异常。
