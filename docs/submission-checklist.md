# 提交检查清单

## 必做项

### 协议与校验
- [x] #1 协议Schema验证 — Envelope Pydantic 校验（version/type/payload），extra="forbid"，legacy 映射
- [x] #2 错误码体系 — 27 个注册错误码，覆盖 gateway/provider/agent 三源，可恢复性标记
- [x] #5 序列号顺序检查 — SeqChecker 按 corr_id 隔离，GAP/ROLLBACK/DUPLICATE 检测
- [x] #6 终态后消息处理 — 状态机终态拦截 + GatewayApp 终态守卫
- [x] #7 状态机 — 六状态（Idle/Invoked/Streaming/Done/Failed/Cancelled），12 条转换规则

### 通信与流控
- [x] #8 心跳 — HEARTBEAT 消息处理，last_seen 更新，IDLE 状态拒绝
- [x] #9 取消传播 — CANCEL 触发状态机转换 + 幂等性注册 + ALREADY_CANCELLED 错误码
- [x] #11 超时 — 四类超时（首token/token间隔/provider响应/总任务），TimeoutChecker

### Provider 与模型
- [x] #14 本地模型部署证据 — Ollama 适配器 + mock_server 集成验证，evidence/local-model-deployment.md
- [x] #16 结构化日志 — StructuredLogger，7 必需字段（ts/level/session_id/corr_id/seq/event/duration）
- [x] #18 追踪 — TraceContext + TraceCollector，corr_id 传播，span 链重建
- [x] #21 模拟LLM服务器 — 独立 HTTP 服务器（mock_server.py），9 场景
- [x] #36 单Provider LLM调用 — OpenAIProviderAdapter + AnthropicProviderAdapter + OllamaProviderAdapter，流式/非流式

### 测试与工具
- [x] #20 自动化测试 — 114 用例，覆盖 26 个测试类，通过率 100%
- [x] #30 Agent入口点 — CLI Agent（cli_agent.py），支持 invoke/cancel/heartbeat/health/metrics/chat 模式

### 文档
- [x] #34 文档质量 — 最终实验报告（08-final-report.md）、AI编码反思（07-ai-coding-reflection.md）、本检查清单
- [x] #35 AI编码反思 — 完整记录 Prompt 策略、人工修改点、验证方式、经验总结

---

## 运行命令

```bash
# 运行测试
python -m pytest tests/test_comprehensive.py -v

# 收集证据
python scripts/collect_evidence.py

# 性能基线
python scripts/perf_baseline.py

# 启动模拟服务器
python -m app.mock_server --port 9000

# CLI Agent
python -m app.cli_agent invoke "hello" --model mock-model
```

---

## 扩展目标（终极）

### #26 模型能力路由
- [x] CapabilityRegistry — 能力声明注册、按能力/模型/任务类型查找
- [x] CapabilityProfile — 声明能力标签、模型列表、任务类型、上下文长度、流式/工具/视觉/代码/推理支持
- [x] best_match — 交集匹配 model ∩ task_type ∩ capabilities
- [x] ProviderRouter capability 策略 — 基于 CapabilityRegistry 的智能选择 + 回退
- [x] model_name/task_type 策略升级 — 利用 CapabilityRegistry 做匹配
- [x] 8 个测试用例（注册查找、能力/模型/任务过滤、交集匹配、路由集成、回退）

### #27 持久化审计
- [x] JSONL 文件写入 — 每次 record() 实时写入 JSONL 行
- [x] 跨实例持久化 — 新实例启动时加载已有 JSONL 文件重建内存索引
- [x] 灵活查询 — query() 支持 session_id/corr_id/event/时间范围组合过滤
- [x] 导出 — export_to_file() 生成独立 JSON 证据文件
- [x] 5 个测试用例（记录查询、持久化、跨实例重载、灵活查询、导出）

---

## 文件清单

```
app/
  main.py                 # FastAPI 入口 + GatewayApp + SessionStore
  cli_agent.py            # CLI Agent 入口
  mock_server.py          # 独立 HTTP Mock 服务器
  core/
    __init__.py           # 导出所有公共组件
    config.py             # GatewayConfig + ProviderEntry
    errors.py             # 27 错误码 + ErrorCodeDef + 查询 API
    state_machine.py      # 六状态状态机引擎
    seq_checker.py        # 序号校验器
    timeout.py            # 四类超时检查
    tracing.py            # OTel 追踪 + TraceCollector
    logger.py             # 结构化日志
    flow_control.py       # BoundedQueue + RateLimiter
    idempotency.py        # 幂等性管理器
    retry.py              # 退避重试
    metrics.py            # 指标收集
    security.py           # API Key 认证 + agent 注册
    policy_filter.py      # 内容过滤 + 敏感屏蔽
    audit.py              # 审计日志
  adapters/
    provider.py           # ProviderAdapter 基类
    router.py             # 多 Provider 路由
    mock_provider.py      # Mock 适配器 (9 场景)
    openai_provider.py    # OpenAI 兼容适配器
    anthropic_provider.py # Anthropic 适配器
    ollama_provider.py    # Ollama 本地适配器
    real_provider.py      # 通用 HTTP 适配器
  models/
    envelope.py           # Envelope + MessageType + 协议校验
    state.py              # SessionState 枚举
tests/
  test_comprehensive.py   # 114 测试用例
docs/
  07-ai-coding-reflection.md
  08-final-report.md
  submission-checklist.md
scripts/
  collect_evidence.py     # 证据收集脚本
  perf_baseline.py        # 性能基线脚本
evidence/
  local-model-deployment.md
config/
  .env.example            # 环境变量模板
```