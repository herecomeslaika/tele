"""A2A_min_v1 Metrics Collector — request counters and latency stats."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Metrics:
    """Runtime metrics for the gateway."""

    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    cancel_count: int = 0
    timeout_count: int = 0
    first_token_latencies: list[float] = field(default_factory=list)
    total_durations: list[float] = field(default_factory=list)
    active_sessions: int = 0

    def record_request(self) -> None:
        self.request_count += 1
        self.active_sessions += 1

    def record_success(self, first_token_latency: Optional[float] = None,
                       total_duration: Optional[float] = None) -> None:
        self.success_count += 1
        self.active_sessions -= 1
        if first_token_latency is not None:
            self.first_token_latencies.append(first_token_latency)
        if total_duration is not None:
            self.total_durations.append(total_duration)

    def record_failure(self) -> None:
        self.failure_count += 1
        self.active_sessions -= 1

    def record_cancel(self) -> None:
        self.cancel_count += 1
        self.active_sessions -= 1

    def record_timeout(self) -> None:
        self.timeout_count += 1
        self.active_sessions -= 1

    def avg_first_token_latency(self) -> Optional[float]:
        if not self.first_token_latencies:
            return None
        return sum(self.first_token_latencies) / len(self.first_token_latencies)

    def avg_total_duration(self) -> Optional[float]:
        if not self.total_durations:
            return None
        return sum(self.total_durations) / len(self.total_durations)

    def p95_first_token_latency(self) -> Optional[float]:
        if not self.first_token_latencies:
            return None
        sorted_lat = sorted(self.first_token_latencies)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def summary(self) -> dict:
        return {
            "request_count": self.request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "cancel_count": self.cancel_count,
            "timeout_count": self.timeout_count,
            "active_sessions": self.active_sessions,
            "avg_first_token_latency_ms": self.avg_first_token_latency(),
            "avg_total_duration_ms": self.avg_total_duration(),
            "p95_first_token_latency_ms": self.p95_first_token_latency(),
        }


# Singleton
_metrics = Metrics()


def get_metrics() -> Metrics:
    return _metrics