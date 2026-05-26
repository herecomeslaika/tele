# 07 — AI 辅助编程反思

## 1. 核心 Prompt 摘要

### 1.1 第一轮：工程骨架搭建
- **Prompt 核心指令**：生成基础目录结构、模块职责定义、配置样例和最小启动入口代码
- **关键约束**：绝对不要一次性生成完整的协议实现，每个模块只写骨架和 docstring

### 1.2 第二轮：协议核心校验与状态机
- **Prompt 核心指令**：实现核心的校验组件（Envelope Pydantic 验证、SeqChecker）和状态流转代码（GatewayStateMachine）
- **关键约束**：绝对不要在这一步实现具体的大模型网络调用逻辑

### 1.3 第三轮：Provider 适配层与可观测性
- **Prompt 核心指令**：实现 Provider 适配层（OpenAI/Anthropic/Ollama/Mock）和结构化可观测性体系（StructuredLogger、TraceContext、AuditLogger）
- **关键约束**：只进行调用和适配，不修改已有核心逻辑

### 1.4 第四轮：扩展目标与最终收尾
- **Prompt 核心指令**：实现多 Provider 路由隔离（ProviderRouter 六种策略）和 OpenTelemetry 追踪链路
- **关键约束**：不破坏现有主链路代码，新增文件而非修改核心模块

---

## 2. AI 生成代码的人工修改点

### 2.1 修改列表
| 文件 | 修改内容 | 修改原因 |
|------|----------|----------|
| `app/main.py:473` | 将 `event=f"msg_type=..."` 改为 `msg_type=envelope.type.value` | log_event 的 event 参数名冲突导致 TypeError |
| `app/core/errors.py` | 添加 ALREADY_CANCELLED 错误码定义 | handle_cancel 使用硬编码字符串而非注册的错误码 |
| `app/adapters/router.py:61` | 将 `sort(key=lambda r: r.priority)` 改为 `reverse=True` | priority 路由应选最高优先级而非最低 |
| `app/main.py:387-408` | handle_cancel 添加幂等性注册 `register(corr_id, "CANCEL", sm.state)` | 取消后未注册幂等性，导致重复取消返回 MSG_AFTER_TERMINAL 而非 ALREADY_CANCELLED |
| `app/mock_server.py:90-169` | DUPLICATE_TOKEN/OUT_OF_ORDER 添加 continue，LONG_RESPONSE 添加 if i==0 限制 | 场景分支缺少 continue 导致 fallthrough bug |

### 2.2 修改模式分析
- 大部分修改是逻辑 bug 修复，核心架构无需改动
- 参数名冲突和排序方向是 AI 容易犯的错误：AI 假设了参数语义但未验证实际用法
- 幂等性遗漏属于边界处理缺失：AI 实现了正常路径但忽略了异常路径的完整性

---

## 3. 验证方式

### 3.1 自动化测试
- 测试框架：pytest + pytest-asyncio
- 总用例数：114
- 通过率：100%
- 命令：`python -m pytest tests/test_comprehensive.py -v`

### 3.2 证据收集
- 证据脚本：`scripts/collect_evidence.py`
- 输出位置：`evidence/extension-goals/`
- 命令：`python scripts/collect_evidence.py`

### 3.3 手动验证项
- 使用 RealProviderAdapter 对 DeepSeek 发起真实流式调用，确认 STREAM_CHUNK 逐 token 产出
- 使用 MockProviderAdapter 各场景验证边界行为（超时、中断、乱序）
- 使用 CLI Agent 验证端到端交互：`python -m app.cli_agent invoke "hello" --model mock-model`

---

## 4. 经验总结

### 4.1 Prompt 设计经验
- 分轮次、明确约束边界"绝对不要做X"比"请做Y"更有效
- 每轮聚焦一个主题，避免 AI 一次性生成过多代码导致质量下降

### 4.2 AI 代码审查要点
- AI 生成的异常处理容易遗漏边界，终态拦截逻辑需要人工确认
- 参数名冲突和语义假设需要运行时验证，不能仅靠静态审查
- 路由排序方向（升序 vs 降序）需要对照文档语义验证

### 4.3 改进建议
- 下一轮可以要求 AI 在每个模块开头用 docstring 声明不变量
- 要求 AI 为每个分支逻辑（if/elif）添加 continue/return 防止 fallthrough