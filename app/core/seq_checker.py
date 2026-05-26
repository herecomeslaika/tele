"""A2A_min_v1 Sequence Checker — per-corr_id monotonic seq validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SeqViolationKind(str, Enum):
    GAP = "gap"
    DUPLICATE = "duplicate"
    ROLLBACK = "rollback"


@dataclass
class SeqResult:
    ok: bool
    expected: Optional[int] = None
    actual: Optional[int] = None
    violation: Optional[SeqViolationKind] = None
    reason: str = ""


@dataclass
class SeqChecker:
    """Validates that STREAM_CHUNK seq numbers are strictly sequential
    within each corr_id. Tracks the last-seen seq per corr_id."""

    _last_seq: dict[str, int] = field(default_factory=dict)

    def check(self, corr_id: str, seq: int, start: int = 1) -> SeqResult:
        """Check a seq against the expected sequence for this corr_id."""
        expected = self._last_seq.get(corr_id, start - 1) + 1

        if seq == expected:
            self._last_seq[corr_id] = seq
            return SeqResult(ok=True, expected=expected, actual=seq)

        last = self._last_seq.get(corr_id, start - 1)
        if seq == last:
            return SeqResult(
                ok=False,
                expected=expected,
                actual=seq,
                violation=SeqViolationKind.DUPLICATE,
                reason=f"seq duplicate: got {seq}, last seen {last}",
            )
        if seq < last:
            return SeqResult(
                ok=False,
                expected=expected,
                actual=seq,
                violation=SeqViolationKind.ROLLBACK,
                reason=f"seq rollback: got {seq}, last seen {last}",
            )
        return SeqResult(
            ok=False,
            expected=expected,
            actual=seq,
            violation=SeqViolationKind.GAP,
            reason=f"seq gap: expected {expected}, got {seq}",
        )

    def reset(self, corr_id: str) -> None:
        """Remove tracking for a corr_id (e.g. after STREAM_END)."""
        self._last_seq.pop(corr_id, None)

    def last_seq(self, corr_id: str) -> Optional[int]:
        """Return the last accepted seq for a corr_id, or None if unknown."""
        return self._last_seq.get(corr_id)
