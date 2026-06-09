# 05 — 问题记录

## 1. 已修复问题

### 1.1 log_event 参数名冲突
- **文件**: `app/main.py:473`
- **问题**: `log_event(logger, "gateway.receive", ..., msg_type=...)` 中 `msg_type` 与 `log_event` 的参数名冲突，导致 TypeError
- **修复**: 将 `msg_type=envelope.type.value` 改为使用正确参数名
- **原因**: AI 生成的参数名假设与实际函数签名不一致

### 1.2 priority 路由排序方向错误
- **文件**: `app/adapters/router.py:61`
- **问题**: `sort(key=lambda r: r.priority)` 默认升序，导致优先级低的 Provider 被优先选择
- **修复**: 添加 `reverse=True` 使高优先级排前
- **原因**: AI 假设 priority 数值越大优先级越高，但排序方向未匹配

### 1.3 CANCEL 幂等性遗漏
- **文件**: `app/main.py:387-408`
- **问题**: handle_cancel 成功取消后未注册幂等性，导致重复 CANCEL 返回 MSG_AFTER_TERMINAL 而非 ALREADY_CANCELLED
- **修复**: 添加 `self.session_store.idempotency.register(corr_id, "CANCEL", sm.state)`
- **原因**: AI 实现了正常路径但遗漏了异常路径的幂等性注册

### 1.4 Mock Server 场景 fallthrough
- **文件**: `app/mock_server.py:90-169`
- **问题**: DUPLICATE_TOKEN/OUT_OF_ORDER 场景缺少 `continue`，LONG_RESPONSE 缺少 `if i==0` 限制，导致 fallthrough bug
- **修复**: 添加 `continue` 和条件限制
- **原因**: AI 生成的分支逻辑缺少显式跳转

### 1.5 ALREADY_CANCELLED 错误码缺失
- **文件**: `app/core/errors.py`
- **问题**: handle_cancel 使用硬编码字符串而非注册的错误码
- **修复**: 添加 ALREADY_CANCELLED 错误码定义到错误码注册表
- **原因**: 初始实现遗漏了该错误码的注册

### 1.6 MultiAgent handle_delegate 调用错误方法
- **文件**: `app/core/multi_agent.py`
- **问题**: handle_delegate 调用 `provider_adapter.stream()`，但 ProviderAdapter 接口方法为 `invoke()`
- **修复**: 改为 `provider_adapter.invoke()` 并正确处理 StreamEvent
- **原因**: AI 假设了不存在的接口方法

---

## 2. 已知限制

### 2.1 Anthropic 适配器
- 未做真实 API 调用验证（需要有效的 Anthropic API Key）
- 适配器代码基于 Anthropic Messages API 文档编写，但未端到端测试

### 2.2 Ollama 本地模型
- 需要用户自行部署 Ollama 服务和模型
- 未包含自动化部署脚本
- 网络超时设置可能需要根据本地硬件调整

### 2.3 性能基线
- 当前性能基线使用 Mock Provider 测量
- 真实 Provider 延迟受网络和负载影响，实际数据可能有较大差异

### 2.4 MultiAgent 协调模式
- fan-out（一对多并发委派）已实现：`handle_fan_out` + `/delegate/fan-out` 端点 + 5 测试用例
- fan-in / pipeline 协调模式尚未实现
- DelegationRecord 中 pattern 字段已预留，但未实现 fan-in/pipeline 分发逻辑

---

## 3. 改进方向

1. 添加 Anthropic Claude API 真实调用验证
2. 添加 Ollama 自动部署 + 健康检查脚本
3. 完善性能基线：增加真实 Provider 压测数据
4. MultiAgent 增加 fan-out/fan-in/pipeline 协调模式
5. 添加 WebSocket 连接认证
6. 添加配置热重载
7. 添加 Provider 健康检查和自动摘除
