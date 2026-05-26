# A2A_min_v1 Sequence Checker — per-corr_id monotonic seq validation

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SeqResult:
    ok: bool
    expected: int | None = None
    actual: int | None = None
    reason: str = ""


@dataclass
class SeqChecker:
    """
    Validates that STREAM_CHUNK seq numbers are strictly sequential
    within each corr_id. Tracks the last-seen seq per corr_id.
    """

    _last_seq: dict[str, int] = field(default_factory=dict)

    def check(self, corr_id: str, seq: int) -> SeqResult:
        """Check a seq against the expected sequence for this corr_id."""
        expected = self._last_seq.get(corr_id, 0) + 1

        if seq == expected:
            self._last_seq[corr_id] = seq
            return SeqResult(ok=True, expected=expected, actual=seq)

        # Determine specific failure reason
        last = self._last_seq.get(corr_id, 0)
        if seq <= last:
            reason = f"seq rollback or duplicate: got {seq}, last seen {last}"
        else:
            reason = f"seq gap: expected {expected}, got {seq}"

        return SeqResult(ok=False, expected=expected, actual=seq, reason=reason)

    def reset(self, corr_id: str) -> None:
        """Remove tracking for a corr_id (e.g. after STREAM_END)."""
        self._last_seq.pop(corr_id, None)

    def last_seq(self, corr_id: str) -> int | None:
        """Return the last accepted seq for a corr_id, or None if unknown."""
        return self._last_seq.get(corr_id)
