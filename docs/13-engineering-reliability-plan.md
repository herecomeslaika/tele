# 13 - 工程可靠性迭代方案

## 1. 背景

项目已经具备 A2A 协议网关、官方 A2A 兼容层和增强 MultiAgent 编排能力。下一步重点不再是新增协议形态，而是提高工程可靠性：请求能取消、Provider 能健康检查并自动摘除、系统在压力下能真实背压、可观测数据能通过 OTel Collector 和 dashboard 展示。

## 2. 迭代目标

| 编号 | 目标 | 说明 |
| ---- | ---- | ---- |
| R1 | 上游取消 | Gateway 收到 CANCEL 后调用当前 Provider 的 `cancel(session_id, corr_id)` |
| R2 | Provider 健康检查 | ProviderAdapter 具备 `health_check()`，Router 维护健康状态 |
| R3 | 自动摘除故障 Provider | 连续失败达到阈值后进入熔断冷却，路由跳过故障 Provider |
| R4 | 真实背压 | 队列满时等待空间、超时或拒绝，不再静默丢弃旧项 |
| R5 | Metrics 扩展 | 记录 provider health、circuit breaker、backpressure、upstream cancel |
| R6 | OTel Collector | 提供 collector / Prometheus / Grafana docker-compose 配置 |
| R7 | Dashboard | 提供 Grafana dashboard JSON 与本地 HTML 可视化页面 |
| R8 | 测试与文档 | 新增可靠性专项测试，并更新 API、部署、报告和检查清单 |

## 3. 实现策略

### 3.1 上游取消

- `ProviderAdapter` 增加默认 `cancel(session_id, corr_id) -> bool`。
- `GatewayApp` 在 Provider 选路后记录 `corr_id -> provider`。
- `handle_cancel` 成功进入 Cancelled 状态后，调用当前 Provider 的 cancel hook。
- Mock Provider 维护被取消的 `(session_id, corr_id)`，用于自动化测试。

### 3.2 健康检查与自动摘除

- `ProviderRoute` 增加健康状态、连续失败次数、熔断到期时间、最近错误。
- `ProviderRouter.select()` 只从健康且未熔断的 route 中选择。
- Provider 返回错误或抛异常时调用 `router.record_failure(provider_name)`。
- Provider 成功完成时调用 `router.record_success(provider_name)`。
- `router.check_health()` 周期性或按接口触发所有 provider 的 `health_check()`。

### 3.3 真实背压

- `BoundedQueue.push()` 保留兼容行为，但新增 async `put()`。
- `put()` 在队列满时等待 `pop()` 释放空间。
- 等待超过 `backpressure_timeout` 后返回失败，Gateway 返回 `QUEUE_FULL`。
- 新增 `drop_oldest=False` 默认行为；只有显式配置兼容模式时才丢旧项。

### 3.4 OTel Collector 与可视化

- 新增 `deploy/observability/docker-compose.yml`。
- 新增 `deploy/observability/otel-collector-config.yml`。
- 新增 `deploy/observability/prometheus.yml`。
- 新增 `deploy/observability/grafana-dashboard.json`。
- 新增 `evidence/visualization/reliability-dashboard.html`，无需外部服务也能打开查看示例图表。

## 4. 验收标准

- 新增 `tests/test_reliability.py` 覆盖：
  - Provider cancel hook 被调用。
  - 故障 Provider 达到阈值后被摘除并路由到备用 Provider。
  - 熔断冷却后健康检查可恢复 Provider。
  - `BoundedQueue.put()` 在满队列上等待，并在超时后失败。
  - metrics 包含 backpressure / cancel / health 状态。
- 完整测试：`python -m pytest -q` 通过。
- 文档和 dashboard 文件可作为课程报告证据引用。

## 5. 当前边界

- OpenAI/Anthropic 等 HTTP 流在客户端层不一定提供请求级 cancel API，本轮提供 best-effort cancel hook；Mock/Ollama 适配器可测试。
- 健康检查默认使用轻量本地 adapter 检查；真实 Provider 的深度健康检查需有效 API key。
- Dashboard 配置是可部署模板，不在自动化测试中启动 Docker。
