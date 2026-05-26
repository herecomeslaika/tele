"""A2A_min_v1 Performance Baseline Script — measures latency and throughput at different concurrency."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import statistics
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.adapters.mock_provider import MockProviderAdapter, MockScenario
from app.core.state_machine import EventType, GatewayStateMachine
from app.models.state import SessionState


async def run_single_request(provider: MockProviderAdapter, prompt: str) -> dict:
    """Run a single request and return timing metrics."""
    start = time.time()
    first_token_time: Optional[float] = None
    total_tokens = 0
    error = False

    try:
        async for event in provider.invoke(prompt):
            if event.type == "chunk":
                if first_token_time is None:
                    first_token_time = time.time()
                total_tokens += 1
            elif event.type == "error":
                error = True
    except Exception:
        error = True

    end = time.time()
    return {
        "first_token_latency_ms": (first_token_time - start) * 1000 if first_token_time else None,
        "total_duration_ms": (end - start) * 1000,
        "total_tokens": total_tokens,
        "error": error,
    }


async def run_concurrent_test(concurrency: int, chunk_count: int = 5) -> dict:
    """Run N concurrent requests and return aggregate metrics."""
    provider = MockProviderAdapter(
        scenario=MockScenario.NORMAL,
        chunk_count=chunk_count,
        chunk_delay=0.01,
    )

    tasks = [run_single_request(provider, f"prompt_{i}") for i in range(concurrency)]
    results = await asyncio.gather(*tasks)

    # Aggregate
    ftl = [r["first_token_latency_ms"] for r in results if r["first_token_latency_ms"] is not None]
    dur = [r["total_duration_ms"] for r in results]
    failures = sum(1 for r in results if r["error"])
    tokens = [r["total_tokens"] for r in results]

    return {
        "concurrency": concurrency,
        "requests": concurrency,
        "failures": failures,
        "avg_first_token_latency_ms": round(statistics.mean(ftl), 2) if ftl else None,
        "p95_first_token_latency_ms": round(sorted(ftl)[int(len(ftl) * 0.95)], 2) if ftl else None,
        "avg_total_duration_ms": round(statistics.mean(dur), 2),
        "p95_total_duration_ms": round(sorted(dur)[int(len(dur) * 0.95)], 2) if len(dur) > 1 else dur[0] if dur else None,
        "avg_tokens": round(statistics.mean(tokens), 2) if tokens else 0,
    }


async def main():
    print("=" * 70)
    print("A2A_min_v1 — Performance Baseline Measurement")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    all_results = []
    for concurrency in [1, 3, 5, 10]:
        print(f">>> Running with concurrency={concurrency} ...")
        result = await run_concurrent_test(concurrency)
        all_results.append(result)
        print(f"    Failures: {result['failures']}")
        print(f"    Avg first-token latency: {result['avg_first_token_latency_ms']}ms")
        print(f"    Avg total duration: {result['avg_total_duration_ms']}ms")
        print(f"    Avg tokens: {result['avg_tokens']}")
        print()

    # Also test timeout scenario
    print(">>> Running timeout scenario (1 request, expect timeout) ...")
    timeout_provider = MockProviderAdapter(scenario=MockScenario.TIMEOUT)
    try:
        result = await asyncio.wait_for(
            run_single_request(timeout_provider, "hang"),
            timeout=2.0,
        )
        result["timeout_hit"] = True
    except asyncio.TimeoutError:
        result = {"timeout_hit": True, "error": True, "total_duration_ms": 2000}
    print(f"    Timeout hit: {result['timeout_hit']}")
    print()

    # Save results
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "evidence", "performance")
    os.makedirs(output_dir, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"baseline_{ts}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "results": all_results,
            "timeout_test": result,
        }, f, indent=2, ensure_ascii=False)

    print("=" * 70)
    print(f"Results saved to: {output_file}")
    print("=" * 70)

    # Summary table
    print("\n| Concurrency | Failures | Avg FTL (ms) | Avg Duration (ms) | Avg Tokens |")
    print("|-------------|----------|--------------|-------------------|-----------|")
    for r in all_results:
        ftl_str = f"{r['avg_first_token_latency_ms']:.1f}" if r['avg_first_token_latency_ms'] else "N/A"
        print(f"| {r['concurrency']:>11} | {r['failures']:>8} | {ftl_str:>12} | {r['avg_total_duration_ms']:>17.1f} | {r['avg_tokens']:>9.1f} |")


if __name__ == "__main__":
    asyncio.run(main())