# Tests for SeqChecker

import pytest

from app.core.seq_checker import SeqChecker


class TestSeqCheckerBasic:
    def test_first_seq_is_1(self):
        checker = SeqChecker()
        result = checker.check("c1", 1)
        assert result.ok
        assert result.expected == 1
        assert result.actual == 1

    def test_sequential_accepts(self):
        checker = SeqChecker()
        assert checker.check("c1", 1).ok
        assert checker.check("c1", 2).ok
        assert checker.check("c1", 3).ok

    def test_gap_rejected(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        result = checker.check("c1", 4)
        assert not result.ok
        assert "gap" in result.reason

    def test_duplicate_rejected(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        result = checker.check("c1", 1)
        assert not result.ok
        assert "duplicate" in result.reason or "rollback" in result.reason

    def test_rollback_rejected(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        checker.check("c1", 2)
        result = checker.check("c1", 1)
        assert not result.ok
        assert "rollback" in result.reason

    def test_different_corr_ids_isolated(self):
        checker = SeqChecker()
        assert checker.check("c1", 1).ok
        assert checker.check("c2", 1).ok
        assert checker.check("c1", 2).ok
        assert checker.check("c2", 2).ok

    def test_cross_corr_id_no_interference(self):
        """A gap in c1 should not affect c2."""
        checker = SeqChecker()
        checker.check("c1", 1)
        checker.check("c2", 1)
        # c1 jumps — should fail
        assert not checker.check("c1", 5).ok
        # c2 should still be fine
        assert checker.check("c2", 2).ok


class TestSeqCheckerReset:
    def test_reset_allows_restart(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        checker.check("c1", 2)
        checker.reset("c1")
        # After reset, seq=1 should be valid again
        result = checker.check("c1", 1)
        assert result.ok

    def test_last_seq_returns_value(self):
        checker = SeqChecker()
        checker.check("c1", 1)
        checker.check("c1", 2)
        assert checker.last_seq("c1") == 2

    def test_last_seq_unknown_corr(self):
        checker = SeqChecker()
        assert checker.last_seq("unknown") is None
