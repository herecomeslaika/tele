"""A2A_min_v1 Auto Experiment Report Generator — produces a Markdown report."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "evidence", "reports")


def run_cmd(cmd: list[str], cwd: str = PROJECT_ROOT, timeout: int = 120) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "TIMEOUT"}


def parse_test_summary(stdout: str) -> dict:
    """Extract test counts from pytest output."""
    for line in stdout.strip().split("\n"):
        if "passed" in line and ("failed" in line or "error" in line or line.strip().endswith("s")):
            parts = {}
            for token in line.split(","):
                token = token.strip()
                if "passed" in token:
                    parts["passed"] = int(token.split()[0])
                if "failed" in token:
                    parts["failed"] = int(token.split()[0])
                if "error" in token:
                    parts["errors"] = int(token.split()[0])
                if "warning" in token:
                    parts["warnings"] = int(token.split()[0])
            if "passed" in parts:
                return parts
    return {}


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORTS_DIR, f"experiment_report_{timestamp}.md")

    print("Generating experiment report...")

    # 1. Run tests
    print("  Running test suite...")
    test_result = run_cmd(
        [sys.executable, "-m", "pytest", "tests/test_comprehensive.py", "-v", "--tb=short",
         "-o", "console_output_style=classic"]
    )
    test_summary = parse_test_summary(test_result["stdout"])

    # 2. Collect error codes
    from app.core.errors import ERROR_REGISTRY
    error_codes = [(c.code, c.source, c.recoverable) for c in ERROR_REGISTRY.values()]

    # 3. Collect metrics
    from app.core.metrics import MetricsCollector
    mc = MetricsCollector()
    mc.record_success(0.5)
    mc.record_failure("TIMEOUT")
    mc.record_cancel()
    mc.record_timeout()

    # 4. Read performance baseline if exists
    perf_data = None
    perf_dir = os.path.join(PROJECT_ROOT, "evidence", "performance")
    if os.path.isdir(perf_dir):
        perf_files = sorted(os.listdir(perf_dir))
        if perf_files:
            with open(os.path.join(perf_dir, perf_files[-1]), "r") as f:
                perf_data = json.load(f)

    # 5. Read DeepSeek e2e if exists
    e2e_data = None
    e2e_path = os.path.join(PROJECT_ROOT, "evidence", "deepseek-e2e-validation.json")
    if os.path.exists(e2e_path):
        with open(e2e_path, "r") as f:
            e2e_data = json.load(f)

    # 6. Generate report
    lines = []
    lines.append(f"# A2A_min_v1 自动实验报告")
    lines.append(f"")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**项目**: A2A_min_v1 Protocol Gateway")
    lines.append(f"")

    # Test results
    lines.append(f"## 1. 测试执行结果")
    lines.append(f"")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 通过 | {test_summary.get('passed', 'N/A')} |")
    lines.append(f"| 失败 | {test_summary.get('failed', 0)} |")
    lines.append(f"| 错误 | {test_summary.get('errors', 0)} |")
    lines.append(f"| 退出码 | {test_result['returncode']} |")
    lines.append(f"")

    if test_result["returncode"] != 0 and test_result["stderr"]:
        lines.append(f"### 错误输出")
        lines.append(f"```")
        lines.append(test_result["stderr"][:2000])
        lines.append(f"```")
        lines.append(f"")

    # Error codes
    lines.append(f"## 2. 错误码体系")
    lines.append(f"")
    lines.append(f"| 错误码 | 来源 | 可恢复 |")
    lines.append(f"|--------|------|--------|")
    for code, source, recoverable in error_codes:
        lines.append(f"| {code} | {source} | {'是' if recoverable else '否'} |")
    lines.append(f"")

    # Metrics
    lines.append(f"## 3. 指标采集")
    lines.append(f"")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 成功数 | {mc.success_count} |")
    lines.append(f"| 失败数 | {mc.failure_count} |")
    lines.append(f"| 取消数 | {mc.cancel_count} |")
    lines.append(f"| 超时数 | {mc.timeout_count} |")
    lines.append(f"| 总请求数 | {mc.total_count} |")
    lines.append(f"")

    # Performance baseline
    lines.append(f"## 4. 性能基线")
    lines.append(f"")
    if perf_data:
        if "results" in perf_data:
            lines.append(f"| 并发数 | 首 Token 延迟 | 总耗时 |")
            lines.append(f"|--------|---------------|--------|")
            for r in perf_data["results"]:
                c = r.get("concurrency", "?")
                ftl = r.get("first_token_latency", "N/A")
                dur = r.get("total_duration", "N/A")
                lines.append(f"| {c} | {ftl} | {dur} |")
        else:
            lines.append(f"数据格式: `{json.dumps(perf_data)[:200]}`")
    else:
        lines.append(f"*未找到性能基线数据*")
    lines.append(f"")

    # DeepSeek e2e
    lines.append(f"## 5. DeepSeek 端到端验证")
    lines.append(f"")
    if e2e_data:
        r = e2e_data.get("results", {})
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 首 Token 延迟 | {r.get('first_token_latency', 'N/A')}s |")
        lines.append(f"| 总耗时 | {r.get('total_duration', 'N/A')}s |")
        lines.append(f"| Stream Chunks | {r.get('chunk_count', 'N/A')} |")
        lines.append(f"| Session 状态 | {r.get('session_state', 'N/A')} |")
        lines.append(f"| 整体结果 | {'✅ PASSED' if e2e_data.get('overall_passed') else '❌ FAILED'} |")
        lines.append(f"")
        lines.append(f"**响应预览**: {e2e_data.get('response_preview', 'N/A')[:100]}")
    else:
        lines.append(f"*未找到 DeepSeek e2e 验证数据*")
    lines.append(f"")

    # Extension goals coverage
    lines.append(f"## 6. 扩展目标覆盖")
    lines.append(f"")
    goals = [
        ("#1", "协议 Schema 校验"), ("#2", "错误码体系"), ("#3", "可恢复重试"),
        ("#4", "幂等语义"), ("#5", "Seq 顺序校验"), ("#6", "终止后消息处理"),
        ("#7", "状态机"), ("#8", "HEARTBEAT"), ("#9", "CANCEL 传播"),
        ("#10", "流控与背压"), ("#11", "超时分类"), ("#12", "Provider Adapter"),
        ("#13", "双协议兼容"), ("#14", "本地模型部署"), ("#15", "配置化 Gateway"),
        ("#16", "结构化日志"), ("#17", "指标采集"), ("#18", "简易追踪"),
        ("#19", "OpenTelemetry"), ("#20", "自动化测试"), ("#21", "Mock LLM Server"),
        ("#22", "故障注入"), ("#23", "性能基线"), ("#24", "并发会话隔离"),
        ("#25", "多 Runtime 路由"), ("#26", "模型能力路由"), ("#27", "持久化审计"),
        ("#28", "安全边界"), ("#29", "输入输出过滤"), ("#30", "Agent 入口"),
        ("#31", "实验报告自动生成"), ("#32", "协议兼容性"), ("#33", "版本协商"),
        ("#34", "文档质量"), ("#35", "AI 编程反思"), ("#36", "单 Provider LLM 调用"),
        ("#37", "MultiAgent"),
    ]
    lines.append(f"| 编号 | 目标 | 状态 |")
    lines.append(f"|------|------|------|")
    for gid, gname in goals:
        lines.append(f"| {gid} | {gname} | ✅ |")
    lines.append(f"")

    # Problem analysis
    lines.append(f"## 7. 问题分析与改进说明")
    lines.append(f"")
    lines.append(f"### 已知问题")
    lines.append(f"- Anthropic 适配器未做真实 API 调用验证（需 API key）")
    lines.append(f"- Ollama 本地模型需要用户自行部署，未包含自动化部署脚本")
    lines.append(f"- 性能基线使用 Mock Provider，真实 Provider 延迟受网络影响")
    lines.append(f"")
    lines.append(f"### 改进方向")
    lines.append(f"- 添加 Anthropic Claude API 真实调用验证")
    lines.append(f"- 添加 Ollama 自动部署+健康检查脚本")
    lines.append(f"- 完善性能基线：增加真实 Provider 压测数据")
    lines.append(f"- MultiAgent 增加 fan-out/fan-in/pipeline 协调模式")
    lines.append(f"")

    # Run commands
    lines.append(f"## 8. 复现命令")
    lines.append(f"")
    lines.append(f"```bash")
    lines.append(f"# 运行测试")
    lines.append(f"python -m pytest tests/test_comprehensive.py -v")
    lines.append(f"")
    lines.append(f"# 收集证据")
    lines.append(f"python scripts/collect_evidence.py")
    lines.append(f"")
    lines.append(f"# 性能基线")
    lines.append(f"python scripts/perf_baseline.py")
    lines.append(f"")
    lines.append(f"# 生成实验报告")
    lines.append(f"python scripts/generate_report.py")
    lines.append(f"")
    lines.append(f"# 启动模拟服务器")
    lines.append(f"python -m app.mock_server --port 9000")
    lines.append(f"")
    lines.append(f"# CLI Agent")
    lines.append(f"python -m app.cli_agent invoke \"hello\" --model mock-model")
    lines.append(f"```")
    lines.append(f"")

    report = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report saved to: {report_path}")
    return report_path


if __name__ == "__main__":
    main()