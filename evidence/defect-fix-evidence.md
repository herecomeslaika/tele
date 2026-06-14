# 缺陷发现与修复证据

## 缺陷 #1: handle_cancel 幂等性遗漏

### 发现过程

在编写 `TestCancel.test_cancel_idempotency` 测试用例时，发现重复发送 CANCEL 消息后，Gateway 返回的错误码是 `MSG_AFTER_TERMINAL` 而非预期的 `ALREADY_CANCELLED`。

**预期行为**：重复 CANCEL 应返回 `ALREADY_CANCELLED`，表示"任务已取消，无需重复取消"。
**实际行为**：返回 `MSG_AFTER_TERMINAL`，表示"终态后消息被拒绝"。

### 根因分析

`handle_cancel` 方法在成功取消后，未将 `corr_id` 注册到 `IdempotencyManager`。导致第二次 CANCEL 时，幂等性检查未命中"已取消"的缓存，而是走到状态机的终态守卫逻辑。

### 修复前代码

```python
# app/main.py (修复前)
async def handle_cancel(self, envelope: Envelope) -> dict:
    session_id = envelope.session_id
    corr_id = envelope.corr_id

    action, _ = self.session_store.idempotency.check_cancel(corr_id)
    if action == IdempotencyAction.IGNORE:
        return make_error_envelope(session_id, corr_id, ALREADY_CANCELLED.code, ...)

    sm = self.session_store.get(session_id)
    # ... (cancel logic)
    result = sm.on_event(EventType.CANCEL)
    # BUG: 缺少幂等性注册！
    get_metrics().record_cancel()
    return make_envelope(...)
```

### 修复后代码

```python
# app/main.py (修复后)
async def handle_cancel(self, envelope: Envelope) -> dict:
    session_id = envelope.session_id
    corr_id = envelope.corr_id

    action, _ = self.session_store.idempotency.check_cancel(corr_id)
    if action == IdempotencyAction.IGNORE:
        return make_error_envelope(session_id, corr_id, ALREADY_CANCELLED.code, ...)

    sm = self.session_store.get(session_id)
    # ... (cancel logic)
    result = sm.on_event(EventType.CANCEL)
    # FIX: 注册幂等性，使重复 CANCEL 被检测为 ALREADY_CANCELLED
    self.session_store.idempotency.register(corr_id, "CANCEL", sm.state)
    get_metrics().record_cancel()
    return make_envelope(...)
```

### 验证

修复后运行测试：

```
tests/test_comprehensive.py::TestCancel::test_cancel_idempotency PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_already_cancelled_returns_error PASSED
```

重复 CANCEL 现在正确返回 `ALREADY_CANCELLED` 而非 `MSG_AFTER_TERMINAL`。

---

## 缺陷 #2: Mock Server 场景 fallthrough

### 发现过程

在运行 Mock Server 的 DUPLICATE_TOKEN 场景测试时，发现输出 token 数量是预期的两倍以上，而非仅重复一次。

### 根因分析

`mock_server.py` 中 DUPLICATE_TOKEN 和 OUT_OF_ORDER 场景的分支末尾缺少 `continue`，导致执行完特定场景逻辑后，控制流 fallthrough 到了 normal 场景的代码，额外输出了重复 token。

### 修复前代码

```python
# app/mock_server.py (修复前)
if scenario == MockScenario.DUPLICATE_TOKEN:
    for _ in range(2):
        chunk = {...}
        yield f"data: {json.dumps(chunk)}\n\n"
    # BUG: 缺少 continue，fallthrough 到 normal 逻辑！

# Normal scenario (fallthrough 到这里)
chunk = {...}
yield f"data: {json.dumps(chunk)}\n\n"
```

### 修复后代码

```python
# app/mock_server.py (修复后)
if scenario == MockScenario.DUPLICATE_TOKEN:
    for _ in range(2):
        chunk = {...}
        yield f"data: {json.dumps(chunk)}\n\n"
    continue  # FIX: 显式跳转到下一次循环迭代
```

### 验证

修复后运行故障注入测试：

```
tests/test_comprehensive.py::TestFaultInjection::test_duplicate_token PASSED
tests/test_comprehensive.py::TestFaultInjection::test_out_of_order PASSED
```

---

## 缺陷 #3: priority 路由排序方向错误

### 发现过程

在配置了多个 Provider 并使用 priority 策略路由时，发现请求总是被路由到优先级最低的 Provider。

### 根因分析

`router.py` 中 `add_route` 方法对 routes 列表按 priority 排序时，使用了默认升序（`sort(key=lambda r: r.priority)`），但业务语义是 priority 数值越大优先级越高，应使用降序。

### 修复

```python
# 修复前
self.routes.sort(key=lambda r: r.priority)

# 修复后
self.routes.sort(key=lambda r: r.priority, reverse=True)
```

### 验证

```
tests/test_comprehensive.py::TestExtendedIntegration::test_multi_provider_router_select PASSED
```
