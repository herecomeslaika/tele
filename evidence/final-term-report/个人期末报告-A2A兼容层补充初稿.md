# Lab03 个人贡献报告（A2A 兼容层补充初稿）

> 说明：本文件根据 `FinalTerm-Report.md` 的格式要求起草。姓名、学号、小组编号、组员互评比例等信息需要提交前由本人补充确认。

## 1. 基本信息

```text
姓名：待补充
学号：待补充
小组编号：待补充
项目名称：A2A_min_v1 Protocol Gateway
本人主要角色：待补充（建议填写：协议兼容层实现、测试维护、文档补充）
负责模块：官方 A2A HTTP+JSON 兼容层、标准 Task/Message/Part 模型、A2A 兼容测试、陈旧测试修复、二次迭代文档
```

## 2. 本人实际完成的工作

本次个人工作主要围绕项目第二次迭代展开。在原有课程版 `A2A_min_v1` 网关已经具备统一 Envelope、状态机、Provider 路由、流式传输、安全边界和审计能力的基础上，我补充了面向官方 A2A HTTP+JSON 风格的兼容层，使项目既能继续满足课程实验中的自定义协议要求，也能以更标准的 Agent Card、`/message:send`、标准 Task 状态、Message/Part/Artifact 模型和 `application/a2a+json` 响应形态对外暴露。除了新增协议兼容能力，我还修复了拆分测试中对旧 API、旧错误对象和旧状态机事件的引用，使完整测试集合能够重新通过。

| 任务 | 产出文件/证据 | 本人承担情况 |
| ---- | ------------- | ------------ |
| 制定第二次迭代计划 | `docs/09-a2a-official-compat-plan.md` | 独立完成，明确官方 A2A 兼容层的目标、边界和验收标准 |
| 建立进度追踪文档 | `docs/10-a2a-official-compat-progress.md` | 独立完成，用表格记录模型、接口、测试、文档和报告状态 |
| 实现官方 A2A 数据模型 | `app/models/a2a.py` | 独立完成，定义 `AgentCard`、`Message`、`Part`、`Artifact`、`Task`、`TaskState` 和标准错误 |
| 实现协议转换层 | `app/core/a2a_compat.py` | 独立完成，实现官方 A2A 请求与内部 Envelope 的映射、Task 快照和标准错误生成 |
| 接入 HTTP+JSON 端点 | `app/main.py` | 独立完成，新增 Agent Card、`/message:send`、`/message:stream`、Task 查询/取消/订阅等接口 |
| 修复陈旧测试 | `tests/test_errors.py`、`tests/test_state_machine.py`、`tests/test_router.py`、`tests/test_timeout.py`、`tests/test_tracing.py`、`tests/test_integration.py` | 独立完成，修复旧导入、旧枚举、旧方法名和旧配置字段 |
| 新增 A2A 兼容测试 | `tests/test_a2a_compat.py` | 独立完成，覆盖 Agent Card、消息发送、流式响应、任务查询、标准错误和终态取消 |
| 补充项目说明文档 | `README.md`、`docs/02-api.md`、`docs/06-protocol.md`、`docs/08-final-report.md`、`submission-checklist.md` | 独立完成，将兼容层设计和验收结果写入项目文档 |

## 3. 本人负责的关键实现或关键文档

### 3.1 官方 A2A 数据模型

文件位置：`app/models/a2a.py`

本人修改/编写的内容：新增官方 A2A 兼容层所需的数据模型，包括 `TaskState`、`Role`、`Part`、`Message`、`TaskStatus`、`Artifact`、`Task`、`StreamResponse`、`SendMessageRequest`、`AgentCard` 以及标准错误响应模型。

这部分解决的问题是：原项目的核心协议是课程版 `A2A_min_v1` Envelope，它适合课程验收和内部执行，但不是官方 A2A 客户端期望的数据结构。官方客户端通常先访问 Agent Card 发现能力，再用 Message、Part、Task、Artifact 等对象表达任务和结果。因此需要单独建立一组边界模型，保证 HTTP 接口返回的数据结构稳定、可校验、可测试。

实现思路上，我没有把官方模型和内部 Envelope 混在一起，而是把官方模型集中放在 `app/models/a2a.py`，并通过 Pydantic 做字段校验。例如 `Part` 要求 `text`、`raw`、`url`、`data` 至少且只能使用一种内容来源，避免一个 Part 同时出现多种互斥数据；`StreamResponse` 要求 `task`、`message`、`statusUpdate`、`artifactUpdate` 四类响应只能出现一种，避免 SSE 流中的事件语义不清。这样写的好处是，协议边界的错误能在模型层提前暴露，而不是拖到业务逻辑里变成难定位的问题。

验证方式：新增 `tests/test_a2a_compat.py` 中的模型校验用例，例如验证无效 `Part` 会触发校验错误；同时通过 `/message:send`、`/message:stream` 和 Task 查询测试间接验证模型能被 FastAPI 正确序列化。

### 3.2 官方 A2A 与内部 Envelope 的转换层

文件位置：`app/core/a2a_compat.py`、`app/main.py`

本人修改/编写的内容：新增 `make_agent_card`、`envelope_from_send_request`、`task_from_content`、`task_from_error`、`artifact_update_from_chunk`、`status_update`、`error_response` 等辅助函数，并在 `app/main.py` 中接入 `/.well-known/agent-card.json`、`/message:send`、`/message:stream`、`/tasks/{task_id}`、`/tasks`、`/tasks/{task_id}:cancel`、`/tasks/{task_id}:subscribe` 等端点。

这部分解决的问题是：项目不能为了兼容官方 A2A 再写一套并行网关，否则状态机、路由、安全、审计、Provider Adapter 都会出现重复实现。我的处理方式是把官方 A2A 作为“边界协议”，进入系统后转换为原有 `A2A_min_v1` Envelope，再复用原网关执行链路。这样既保留课程项目中已经验证过的核心能力，也让外部调用方式更接近官方规范。

关键映射关系如下：

| 官方 A2A | 内部 A2A_min_v1 | 说明 |
| -------- | --------------- | ---- |
| `Message.parts[].text` | `payload.prompt` | 当前主要支持文本输入 |
| `Message.contextId` | `session_id` | 未提供时自动生成 |
| `Message.taskId` | `corr_id` | 未提供时自动生成 |
| `metadata.model` | `payload.model` | 未提供时使用默认 Provider 模型 |
| `metadata.task_type` | `payload.task_type` | 用于能力路由 |
| `STREAM_CHUNK` | `TaskArtifactUpdateEvent` | 流式 token 映射为 artifact 增量 |
| `STREAM_END` | `Task.status=COMPLETED` | 最终结果汇总为标准 Task |
| `ERROR` | 标准错误或失败 Task | 根据错误类型转换 |

验证方式：我用 `TestClient` 编写端到端测试，直接调用官方兼容端点，检查响应头、响应模型、错误结构和流式 SSE 数据。完整测试通过后，说明兼容层不是孤立函数，而是能和现有 GatewayApp、MockProviderAdapter、路由和状态处理配合运行。

## 4. AI 编程工具使用记录

| 项目 | 内容 |
| ---- | ---- |
| 使用工具 | Codex |
| 主要用途 | 分析现有项目结构、规划官方 A2A 兼容层、编写模型和转换层、修复测试、补充文档、起草个人报告 |
| 关键提示词摘要 | “完成官方 A2A 兼容层，完善 Agent Card、/message:send、标准 Task 状态、Message/Part/Artifact 模型、标准错误和 application/a2a+json，并修复测试依赖和陈旧拆分测试。” |
| AI 生成内容 | `app/models/a2a.py`、`app/core/a2a_compat.py`、`tests/test_a2a_compat.py`、二次迭代文档和报告初稿 |
| 人工修改点 | 明确不替换原 `A2A_min_v1` 核心协议，而是采用边界适配；保留原 GatewayApp 执行链路；根据项目实际 API 修复测试中的旧导入和旧方法名 |
| 验证方式 | 运行 `python -m pytest -q` 和 `python -m pytest tests/test_comprehensive.py -q`，并检查新增 A2A 兼容测试覆盖情况 |

在使用 AI 工具时，我没有直接接受“重写整个协议栈”的方向，而是先阅读现有项目结构，确认原系统已经具备状态机、路由、适配器和审计能力。之后才决定把官方 A2A 做成兼容层。这一人工决策降低了改动范围，也让新增能力可以被原测试体系验证。

## 5. 测试、运行证据与问题处理

### 5.1 官方 A2A 兼容层测试

测试/问题名称：官方 A2A HTTP+JSON 兼容层验收

现象：原项目只有课程版 `/invoke`、`/stream`、`/ws` 等接口，缺少 Agent Card、`/message:send`、标准 Task、标准错误和 `application/a2a+json`。

本人做了什么：新增 `tests/test_a2a_compat.py`，覆盖以下场景：

- `GET /.well-known/agent-card.json` 返回 Agent Card，并带有 `application/a2a+json`。
- `POST /message:send` 能把 A2A Message 转换为内部 Envelope，并返回完成状态 Task。
- `GET /tasks/{task_id}` 和 `GET /tasks` 能查询任务快照。
- `POST /message:stream` 能以 SSE 返回状态更新、artifact 增量和最终 Task。
- 查询不存在任务时返回标准错误结构。
- 对已完成任务取消时返回 `UNSUPPORTED_OPERATION`。
- 未配置 Extended Agent Card 时返回标准错误。

结果证据位置：`tests/test_a2a_compat.py`、`docs/10-a2a-official-compat-progress.md`

### 5.2 陈旧测试修复

测试/问题名称：拆分测试引用旧 API 导致失败

现象：多个测试文件仍引用旧符号或旧方法，例如旧的 `ErrorCode`、`make_error_envelope`、旧状态机事件 `CANCEL`、旧 Router 参数、旧 timeout 枚举、旧 tracing 注入方法等。

本人做了什么：逐个对照当前源码修复测试，使测试表达当前代码真实行为，而不是为了通过测试去恢复已经淘汰的接口。主要修改包括：

- `tests/test_errors.py`：改为使用当前 `ErrorCodeDef` 注册表和 `app.models.envelope.make_error_envelope`。
- `tests/test_state_machine.py`：改为当前 `EventType` 枚举。
- `tests/test_router.py`：修正 Provider 版本、优先级和路由断言。
- `tests/test_timeout.py`：修正 Provider 响应超时命名。
- `tests/test_tracing.py`：修正 payload 注入方法。
- `tests/test_integration.py`：按当前 `GatewayApp` 和 Mock Provider API 重写集成测试。

结果证据位置：`tests/test_errors.py`、`tests/test_state_machine.py`、`tests/test_router.py`、`tests/test_timeout.py`、`tests/test_tracing.py`、`tests/test_integration.py`

### 5.3 完整测试结果

运行命令：

```bash
python -m pytest -q
python -m pytest tests/test_comprehensive.py -q
```

当前结果：`python -m pytest -q` 通过，结果为 231 passed、1 warning；`python -m pytest tests/test_comprehensive.py -q` 通过，结果为 141 passed。最终提交前应以本机最后一次运行结果为准，并可将终端输出截图或保存为 `verification.txt` 作为报告证据。

## 6. 个人贡献自评与组员互评

个人自评：

```text
我认为本人贡献比例为：待小组确认后填写
依据：本人完成官方 A2A 兼容层的新增模型、转换层、HTTP 端点、测试修复、兼容测试和二次迭代文档；该部分属于在原项目基础上的第二阶段扩展，具有明确代码量、测试量和文档产出。
```

组员互评：

| 成员 | 贡献比例 | 依据 |
| ---- | -------: | ---- |
| 待补充（本人） | 待补充 | 官方 A2A 兼容层、测试修复、文档补充 |
| 待补充 | 待补充 | 待补充 |
| 待补充 | 待补充 | 待补充 |
| 待补充 | 待补充 | 待补充 |

> 提交前检查：所有成员贡献比例合计必须等于 100%。建议在小组内部确认后再替换本节占位内容。
