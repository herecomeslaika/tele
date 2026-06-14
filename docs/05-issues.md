# 05 — 问题记录

## 1. 已修复问题

### 1.1 log_event 参数名冲突
- **文件**: `app/main.py:473` (修复前)
- **问题**: `log_event(logger, "gateway.receive", ..., msg_type=...)` 中 `msg_type` 与 `log_event` 的 `**extra` 参数传递正确，但最初 AI 将参数名写成 `event=f"msg_type=..."` 导致 `event` 参数被错误覆盖
- **修复**: 将参数改为使用 `msg_type=envelope.type.value` 作为 extra kwarg
- **原因**: AI 生成的参数名假设与实际函数签名不一致，未注意到 `log_event` 第一个位置参数就是 `event`
- **发现方式**: 运行时 TypeError

### 1.2 priority 路由排序方向错误
- **文件**: `app/adapters/router.py:61` (修复前)
- **问题**: `sort(key=lambda r: r.priority)` 默认升序，导致优先级低的 Provider 被优先选择
- **修复**: 添加 `reverse=True` 使高优先级排前
- **原因**: AI 假设 priority 数值越大优先级越高，但排序方向未匹配——应该降序排列
- **发现方式**: 代码审查发现路由选择行为不符合预期

### 1.3 CANCEL 幂等性遗漏
- **文件**: `app/main.py:387-408` (修复前)
- **问题**: handle_cancel 成功取消后未注册幂等性，导致重复 CANCEL 返回 MSG_AFTER_TERMINAL 而非 ALREADY_CANCELLED
- **修复**: 添加 `self.session_store.idempotency.register(corr_id, "CANCEL", sm.state)`
- **原因**: AI 实现了正常路径但遗漏了异常路径的幂等性注册——CANCEL 成功后需要在幂等性缓存中标记
- **发现方式**: 测试发现重复 CANCEL 返回了错误的错误码

### 1.4 Mock Server 场景 fallthrough
- **文件**: `app/mock_server.py:90-169` (修复前)
- **问题**: DUPLICATE_TOKEN/OUT_OF_ORDER 场景缺少 `continue`，LONG_RESPONSE 缺少 `if i==0` 限制，导致 fallthrough bug——执行完特定场景后继续进入 normal 逻辑
- **修复**: 添加 `continue` 和条件限制
- **原因**: AI 生成的分支逻辑缺少显式跳转——if/elif 分支末尾需要 `continue` 防止 fallthrough 到 normal 逻辑
- **发现方式**: 测试发现 DUPLICATE_TOKEN 场景下 token 数量不符合预期

### 1.5 ALREADY_CANCELLED 错误码重复注册
- **文件**: `app/core/errors.py` (修复前)
- **问题**: `ALREADY_CANCELLED` 被注册了两次，导致 `_ERROR_REGISTRY` 中后一个覆盖前一个
- **修复**: 删除重复注册
- **原因**: 初始实现遗漏了该错误码的注册，后来添加时未删除旧代码
- **发现方式**: 代码审查

### 1.6 MultiAgent handle_delegate 调用错误方法
- **文件**: `app/core/multi_agent.py` (修复前)
- **问题**: handle_delegate 调用 `provider_adapter.stream()`，但 ProviderAdapter 接口方法为 `invoke()`
- **修复**: 改为 `provider_adapter.invoke()` 并正确处理 StreamEvent
- **原因**: AI 假设了不存在的接口方法——未检查 ProviderAdapter 的实际接口定义
- **发现方式**: 运行时 AttributeError

---

## 2. 已知限制

### 2.1 Anthropic 适配器
- 未做真实 API 调用验证（需要有效的 Anthropic API Key）
- 适配器代码基于 Anthropic Messages API 文档编写，但未端到端测试
- 流式解析基于 `event.type == "content_block_delta"` 和 `event.type == "message_stop"`，未经真实流验证

### 2.2 Ollama 本地模型
- 需要用户自行部署 Ollama 服务和模型
- 未包含自动化部署脚本
- 网络超时设置可能需要根据本地硬件调整
- Ollama 的 `/api/abort` 端点可用于上游取消，但当前未集成

### 2.3 性能基线
- 当前性能基线使用 Mock Provider 测量
- 真实 Provider 延迟受网络和负载影响，实际数据可能有较大差异
- 并发测试使用 asyncio 模拟，非真实多进程并发

### 2.4 MultiAgent 协调模式
- fan-out（一对多并发委派）已实现：`handle_fan_out` + `/delegate/fan-out` 端点 + 5 测试用例
- fan-in / pipeline 协调模式尚未实现
- DelegationRecord 中 pattern 字段已预留，但未实现 fan-in/pipeline 分发逻辑
- Agent 间通信通过 Gateway 中转，未实现 Agent-to-Agent 直连

### 2.5 本地取消 vs 上游取消
- 当前 CANCEL 仅实现本地取消（Gateway 停止转发 token）
- Provider 侧继续生成直到自然结束，无法释放计算资源
- Ollama 支持上游取消（`/api/abort`），但当前未集成

---

## 3. 改进方向

1. **Anthropic 真实调用验证** — 获取 API Key 后完成端到端测试
2. **Ollama 自动部署** — 添加部署脚本 + 健康检查 + 模型拉取自动化
3. **上游取消** — 在 OllamaProviderAdapter 中实现 `abort()` 方法
4. **性能基线完善** — 增加真实 Provider 压测数据，使用 locust 或 wrk
5. **MultiAgent 协调** — 增加 fan-in / pipeline 协调模式
6. **WebSocket 认证** — 在 WebSocket 握手阶段验证 API Key
7. **配置热重载** — 监听 .env 文件变化，无需重启即可更新配置
8. **Provider 健康检查** — 定期 ping Provider 端点，自动摘除不可用 Provider
9. **OpenTelemetry 完整接入** — 替换简易 TraceCollector 为 OTel SDK
10. **流控优化** — 当前 BoundedQueue 满时丢弃最旧项，可改为背压等待
