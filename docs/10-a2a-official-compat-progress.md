# 10 - 官方 A2A 兼容层进度追踪

| 项目 | 状态 | 证据/文件 | 备注 |
| ---- | ---- | --------- | ---- |
| 二次迭代计划 | 已完成 | `docs/09-a2a-official-compat-plan.md` | 记录目标、范围、接口和验收标准 |
| 标准数据模型 | 已完成 | `app/models/a2a.py` | Task / Message / Part / Artifact / AgentCard / 标准错误 |
| 兼容转换层 | 已完成 | `app/core/a2a_compat.py` | 官方 A2A HTTP+JSON 与 A2A_min_v1 Envelope 映射 |
| Agent Card | 已完成 | `GET /.well-known/agent-card.json` | 对外暴露能力发现信息 |
| Extended Agent Card | 已完成 | `GET /extendedAgentCard` | 未启用扩展卡时返回标准错误 |
| `/message:send` | 已完成 | `POST /message:send` | 同步执行并返回最终 Task |
| `/message:stream` | 已完成 | `POST /message:stream` | SSE 返回 StreamResponse |
| 任务查询 | 已完成 | `GET /tasks/{id}`, `GET /tasks` | 查询标准 Task 快照 |
| 任务取消/订阅 | 已完成 | `POST /tasks/{id}:cancel`, `POST /tasks/{id}:subscribe` | 终态任务返回标准错误；非终态可订阅 |
| 标准错误格式 | 已完成 | `app/core/a2a_compat.py` | `google.rpc.Status` / `ErrorInfo` 风格 |
| 测试依赖 | 已完成 | `requirements-dev.txt` | `pytest` + `pytest-asyncio` |
| 陈旧测试修复 | 已完成 | `tests/test_*.py` | 修复旧 API、旧枚举、旧错误引用 |
| A2A 兼容测试 | 已完成 | `tests/test_a2a_compat.py` | 覆盖 Agent Card、消息发送、流式、任务、标准错误 |
| 项目文档更新 | 已完成 | README / docs | 说明兼容层与课程版协议的关系 |
| 个人期末报告初稿 | 已完成 | `evidence/final-term-report/个人期末报告-A2A兼容层补充初稿.md`、`FinalTerm-Report` 目录 | 已起草并复制到课程目录；需提交前补姓名、学号、组内分工 |
| 完整测试验收 | 已完成 | pytest 输出 | `python -m pytest -q`：231 passed；`python -m pytest tests/test_comprehensive.py -q`：141 passed |

## 当前结论

当前项目已经从课程版 `A2A_min_v1` 网关扩展为“双接口”形态：

- 课程实验接口继续保留：`/invoke`、`/stream`、`/cancel`、`/heartbeat`、`/ws`。
- 官方 A2A 兼容入口新增：Agent Card、`/message:send`、`/message:stream`、标准 Task 查询/取消/订阅。
- 内部核心仍复用原状态机、路由、安全、审计和 Provider Adapter，避免把官方兼容层写成另一套并行网关。

## 后续可扩展方向

- 持久化 Task Store：把当前内存任务快照落到 JSONL、SQLite 或 Redis。
- Push Notification：实现官方 A2A 的任务状态回调能力。
- Extended Agent Card：在鉴权后返回更详细的内部能力、模型、限流和成本信息。
- Upstream Cancel：对支持取消的 Provider 实现真正上游中断，而不是仅停止向客户端转发。
- 多 Agent 官方兼容：把现有 fan-out / registry 能力映射为多个 AgentSkill 或多 AgentCard。
