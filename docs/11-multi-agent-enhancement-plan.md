# 11 - MultiAgent 增强迭代方案

## 1. 背景

当前项目已经具备 Agent 注册、single delegation 和 fan-out 协调能力，但 Agent 之间主要由 Gateway 内部直接调度，协作模式仍偏简单。本次迭代目标是把 MultiAgent 从“单次委派/并发广播”扩展为可组合的协作编排层，支持更多真实工作流。

## 2. 迭代目标

| 编号 | 目标 | 说明 |
| ---- | ---- | ---- |
| M1 | fan-in | 多个 Agent 并发执行不同或相同任务，并将结果聚合为一个最终响应 |
| M2 | pipeline | 按步骤顺序执行 Agent 链路，前一步结果进入后一步上下文 |
| M3 | planner-worker-reviewer | 内置“规划-执行-审查”协作流，适合复杂任务分解与质量检查 |
| M4 | 跨 HTTP Agent 调用 | AgentProfile 支持 endpoint，优先调用外部 HTTP Agent，而不是只走本地 Provider |
| M5 | 结果聚合 | 支持 json、concat、summary 三种聚合策略 |
| M6 | 失败补偿 | 支持 partial、fail_fast、compensate 三种失败策略，记录补偿结果 |
| M7 | API 与测试 | 新增 REST 端点、自动化测试和文档说明 |

## 3. 协议输入设计

### 3.1 fan-in

```json
{
  "type": "AGENT_DELEGATE",
  "session_id": "s1",
  "corr_id": "c1",
  "payload": {
    "pattern": "fan-in",
    "target_agents": ["researcher", "coder", "tester"],
    "task": "分析这个功能应该如何实现",
    "aggregation": "summary",
    "failure_policy": "partial"
  }
}
```

### 3.2 pipeline

```json
{
  "payload": {
    "pattern": "pipeline",
    "task": "完成接口兼容层",
    "steps": [
      {"agent": "planner", "task": "给出实现计划：{input}"},
      {"agent": "worker", "task": "根据计划实现：{previous}"},
      {"agent": "reviewer", "task": "审查实现结果：{previous}"}
    ],
    "failure_policy": "fail_fast"
  }
}
```

### 3.3 planner-worker-reviewer

```json
{
  "payload": {
    "pattern": "planner-worker-reviewer",
    "task": "增强 MultiAgent 协作能力",
    "planner_agent": "planner",
    "worker_agents": ["worker-1", "worker-2"],
    "reviewer_agent": "reviewer",
    "aggregation": "summary",
    "failure_policy": "compensate",
    "compensation_agent": "fallback-worker"
  }
}
```

## 4. 实现策略

- 在 `app/core/multi_agent.py` 中增加统一的 `_execute_agent_task`，集中处理本地 Provider 调用、HTTP Agent 调用、记录更新、并发计数和错误归档。
- `AgentProfile.endpoint` 不为空时，优先通过 HTTP POST 调用外部 Agent；否则使用本地 ProviderRouter。
- fan-out 保持兼容现有行为；fan-in 在 fan-out 执行结果基础上增加聚合。
- pipeline 逐步执行，使用 `{input}`、`{previous}`、`{step_index}`、`{agent_id}` 填充每一步任务模板。
- planner-worker-reviewer 复用 pipeline 与 fan-in：planner 先生成计划，worker 阶段并发执行，reviewer 最后审查聚合结果。
- 失败策略统一：
  - `partial`：失败子任务保留，父任务状态为 `partial`。
  - `fail_fast`：遇到失败立即终止父任务。
  - `compensate`：尝试调用补偿 Agent 或使用 fallback 结果，并记录 `compensations`。

## 5. 验收标准

- 新增 `tests/test_multi_agent_enhanced.py`，覆盖 fan-in、pipeline、planner-worker-reviewer、HTTP Agent 调用、聚合和失败补偿。
- 原有 `tests/test_comprehensive.py` 中 fan-out 行为继续通过。
- 新增 REST 端点：
  - `POST /delegate/fan-in`
  - `POST /delegate/pipeline`
  - `POST /delegate/planner-worker-reviewer`
- 文档更新覆盖新增 payload 字段、响应字段、失败策略和当前边界。
- 完整测试：`python -m pytest -q` 通过。

## 6. 当前边界

- HTTP Agent 调用使用同步请求-响应模型，不实现远程 SSE 合并。
- 跨 HTTP Agent 默认假设远端接受 A2A_min_v1 `INVOKE` Envelope 或返回 `{result: ...}`。
- 聚合策略 `summary` 在未配置聚合 Agent 时使用本地摘要格式；配置 `aggregator_agent` 后可委托 Agent 生成摘要。
- 失败补偿记录补偿结果，但不回滚已经完成的外部副作用。
