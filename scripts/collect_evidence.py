#!/usr/bin/env python3
"""
Evidence collection script for A2A_min_v1 extension goals.
Runs all extension tests and exports structured logs to evidence/extension-goals/.
"""

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
        [sys.executable, "-m", "pytest", test_pattern, "-v", "--tb=short", "-o", "console_output_style=classic"],
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
    print("A2A_min_v1 — Extension Goals Evidence Collection")
    print(f"Timestamp: {timestamp}")
    print("=" * 60)

    test_specs = [
        ("tests/test_router.py", "Extension Goal 1: Multi-Provider Router"),
        ("tests/test_tracing.py", "Extension Goal 2: OpenTelemetry Tracing"),
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
        f.write(f"A2A_min_v1 Extension Goals — Test Run Log\n")
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
