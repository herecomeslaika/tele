"""A2A_min_v1 Evidence Collection Script — runs all tests and collects structured evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE_DIR = os.path.join(PROJECT_ROOT, "evidence", "extension-goals")


def run_tests(test_pattern: str, label: str) -> dict:
    """Run pytest for a specific test file and capture results."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_pattern, "-v", "--tb=short",
         "-o", "console_output_style=classic"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return {
        "label": label,
        "test_pattern": test_pattern,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "passed": result.returncode == 0,
    }


def main():
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 60)
    print("A2A_min_v1 — Comprehensive Evidence Collection")
    print(f"Timestamp: {timestamp}")
    print("=" * 60)

    test_specs = [
        ("tests/test_comprehensive.py", "All Extension Goals — Comprehensive Suite"),
        ("tests/test_comprehensive.py::TestSchemaValidation", "Protocol Schema Validation (#1)"),
        ("tests/test_comprehensive.py::TestErrorCodeSystem", "Error Code System (#2)"),
        ("tests/test_comprehensive.py::TestSeqChecker", "Seq Order Check (#5)"),
        ("tests/test_comprehensive.py::TestTerminalStateHandling", "Terminal State Handling (#6)"),
        ("tests/test_comprehensive.py::TestStateMachine", "State Machine (#7)"),
        ("tests/test_comprehensive.py::TestHeartbeat", "Heartbeat (#8)"),
        ("tests/test_comprehensive.py::TestCancelPropagation", "Cancel Propagation (#9)"),
        ("tests/test_comprehensive.py::TestTimeoutClassification", "Timeout Classification (#11)"),
        ("tests/test_comprehensive.py::TestFlowControl", "Flow Control (#10)"),
        ("tests/test_comprehensive.py::TestProviderAdapter", "Provider Adapter (#12, #36)"),
        ("tests/test_comprehensive.py::TestLoggingAndTracing", "Structured Logging & Tracing (#16, #18)"),
        ("tests/test_comprehensive.py::TestMetrics", "Metrics (#17)"),
        ("tests/test_comprehensive.py::TestAudit", "Audit (#27)"),
        ("tests/test_comprehensive.py::TestSecurity", "Security (#28)"),
        ("tests/test_comprehensive.py::TestPolicyFilter", "Policy Filter (#29)"),
        ("tests/test_comprehensive.py::TestProtocolCompatibility", "Protocol Compatibility (#32)"),
        ("tests/test_comprehensive.py::TestVersionNegotiation", "Version Negotiation (#33)"),
        ("tests/test_comprehensive.py::TestFaultInjection", "Fault Injection (#22)"),
        ("tests/test_comprehensive.py::TestConfiguration", "Configuration (#15)"),
        ("tests/test_comprehensive.py::TestConcurrentIsolation", "Concurrent Session Isolation (#24)"),
        ("tests/test_comprehensive.py::TestOpenTelemetry", "OpenTelemetry (#19)"),
        ("tests/test_comprehensive.py::TestIdempotency", "Idempotency (#4)"),
        ("tests/test_comprehensive.py::TestRetryMechanism", "Retry Mechanism (#3)"),
        ("tests/test_comprehensive.py::TestIntegration", "Integration Pipeline"),
        ("tests/test_comprehensive.py::TestExtendedIntegration", "Extended Integration (#20)"),
    ]

    all_results = []
    for pattern, label in test_specs:
        print(f"\n>>> Running: {label}")
        r = run_tests(pattern, label)
        all_results.append(r)
        status = "PASSED" if r["passed"] else "FAILED"
        print(f"    Result: {status}")

    # Write combined evidence file
    evidence_file = os.path.join(EVIDENCE_DIR, f"extension_evidence_{timestamp}.json")
    with open(evidence_file, "w", encoding="utf-8") as f:
        json.dump({
            "collection_timestamp": timestamp,
            "results": [
                {
                    "label": r["label"],
                    "test_pattern": r["test_pattern"],
                    "passed": r["passed"],
                    "returncode": r["returncode"],
                    "stdout": r["stdout"],
                    "stderr": r["stderr"],
                }
                for r in all_results
            ],
        }, f, indent=2, ensure_ascii=False)

    # Write human-readable log
    log_file = os.path.join(EVIDENCE_DIR, f"extension_log_{timestamp}.txt")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"A2A_min_v1 Comprehensive Evidence — Test Run Log\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write("=" * 60 + "\n\n")
        for r in all_results:
            f.write(f"## {r['label']}\n")
            f.write(f"Pattern: {r['test_pattern']}\n")
            f.write(f"Status: {'PASSED' if r['passed'] else 'FAILED'}\n\n")
            f.write(r["stdout"])
            if r["stderr"]:
                f.write("\n--- STDERR ---\n")
                f.write(r["stderr"])
            f.write("\n" + "=" * 60 + "\n\n")

    # Summary
    all_passed = all(r["passed"] for r in all_results)
    print("\n" + "=" * 60)
    print(f"Overall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print(f"Evidence files:")
    print(f"  {evidence_file}")
    print(f"  {log_file}")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()