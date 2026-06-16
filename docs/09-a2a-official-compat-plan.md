# 09 — 官方 A2A 兼容层二次迭代计划

## 1. 当前项目基线

当前项目已经完成课程版 `A2A_min_v1` 网关，具备统一信封、状态机、流式传输、Provider Adapter、多 Runtime/能力路由、审计、安全、策略过滤、CLI Agent、Mock Provider 和 Multi-Agent fan-out。主测试命令为：

```bash
python -m pytest tests/test_comprehensive.py -v
```

现有实现满足 Lab03 最低主链路：

```text
Agent -> Gateway -> LLM Provider -> Gateway -> Agent
```

但它仍是课程版协议，不是官方 A2A HTTP+JSON/REST 绑定的完整实现。主要缺口包括 Agent Card 发现、标准 `Task`/`Message`/`Part`/`Artifact` 数据模型、`/message:send` 与任务资源端点、`application/a2a+json` 媒体类型、标准任务状态和标准错误格式。

## 2. 二次迭代目标

本次迭代目标是在不破坏课程版 `A2A_min_v1` 的前提下，新增一个官方 A2A 兼容层：

- 暴露 `GET /.well-known/agent-card.json`，返回描述本 Gateway 能力的 `AgentCard`。
- 新增官方 A2A HTTP+JSON/REST 入口：`POST /message:send`、`POST /message:stream`、`GET /tasks/{id}`、`GET /tasks`、`POST /tasks/{id}:cancel`、`POST /tasks/{id}:subscribe`、`GET /extendedAgentCard`。
- 建立标准数据模型：`Task`、`TaskStatus`、`TaskState`、`Message`、`Role`、`Part`、`Artifact`、`TaskStatusUpdateEvent`、`TaskArtifactUpdateEvent`、`StreamResponse`、`AgentCard`。
- 将官方 A2A 请求转换为现有 `A2A_min_v1` `Envelope`，复用已有 Provider、状态机、日志、指标、审计和策略能力。
- 输出符合 REST 绑定习惯的标准错误对象，包含 `google.rpc.ErrorInfo` 风格的 `details`。
- 修复测试依赖与陈旧拆分测试，使完整 `python -m pytest -q` 可作为项目级验收命令。

## 3. 实现方案

### 3.1 数据模型

新增 `app/models/a2a.py`：

- 用 Pydantic 定义官方 A2A 核心对象。
- `Part` 强制 `text`、`raw`、`url`、`data` 四选一。
- `StreamResponse` 强制 `task`、`message`、`statusUpdate`、`artifactUpdate` 四选一。
- 所有公开 JSON 字段使用官方 camelCase 命名。

### 3.2 兼容转换层

新增 `app/core/a2a_compat.py`：

- `A2ATaskStore` 维护标准 A2A 任务快照。
- 将 `Message.parts` 中的文本或结构化数据转换为现有 `INVOKE.payload.prompt`。
- 将 `session_id/corr_id` 映射为 `contextId/taskId`。
- 将现有 `STREAM_CHUNK` 转换为 `TaskArtifactUpdateEvent`。
- 将现有 `STREAM_END` 转换为 `TASK_STATE_COMPLETED`。
- 将现有 `ERROR` 转换为标准 REST 错误对象。

### 3.3 REST 端点

在 `app/main.py` 中注册官方 A2A 端点：

```text
GET  /.well-known/agent-card.json
GET  /extendedAgentCard
POST /message:send
POST /message:stream
GET  /tasks/{id}
GET  /tasks
POST /tasks/{id}:cancel
POST /tasks/{id}:subscribe
```

响应媒体类型：

```text
application/a2a+json
```

流式响应使用 SSE：

```text
text/event-stream
```

### 3.4 测试与文档

- 新增 `tests/test_a2a_compat.py` 覆盖官方兼容层。
- 修复旧拆分测试的过期 import、旧 version 字段、旧 Provider API 和旧 Timeout API。
- 新增 `requirements-dev.txt` 管理测试依赖。
- 更新 README、API 文档、协议文档和最终报告，明确区分课程版 `A2A_min_v1` 与官方 A2A 兼容层。

## 4. 验收标准

必须通过以下命令：

```bash
python -m pytest tests/test_comprehensive.py -q
python -m pytest -q
```

功能验收：

- `GET /.well-known/agent-card.json` 返回完整 `AgentCard`。
- `POST /message:send` 可返回标准 `Task`。
- `POST /message:stream` 可返回标准 SSE `StreamResponse`。
- `GET /tasks/{id}` 可查询任务快照。
- `POST /tasks/{id}:cancel` 可取消非终态任务并返回标准任务状态。
- 标准错误响应包含 `error.code`、`error.status`、`error.message`、`google.rpc.ErrorInfo` 详情。

## 5. 风险与边界

- 本次是 HTTP+JSON/REST 兼容层，不实现 gRPC 绑定和 JSON-RPC 绑定。
- Push Notification 配置端点暂不实现，Agent Card 中声明 `pushNotifications=false`。
- `message:send` 当前同步消费 Provider 流并返回最终 `Task`；异步后台执行可作为后续迭代。
- `message:stream` 输出标准事件序列，但不实现断线恢复。
- 安全策略复用现有 Gateway 安全能力；生产级 OAuth/OIDC/mTLS 只在文档中说明边界。
