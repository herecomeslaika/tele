# Tests for TimeoutChecker

import time

from app.core.timeout import TimeoutChecker, TimeoutKind


class TestTimeoutChecker:
    def test_register_and_get(self):
        tc = TimeoutChecker()
        timer = tc.register("s1", "c1")
        assert tc.get("s1") is timer

    def test_heartbeat_updates_last_seen(self):
        tc = TimeoutChecker()
        tc.register("s1", "c1")
        old = tc.get("s1").last_seen
        time.sleep(0.01)
        result = tc.on_heartbeat("s1")
        assert result is True
        assert tc.get("s1").last_seen > old

    def test_heartbeat_unknown_session(self):
        tc = TimeoutChecker()
        assert tc.on_heartbeat("unknown") is False

    def test_first_token_timeout(self):
        tc = TimeoutChecker(first_token_timeout=0.05)
        tc.register("s1", "c1")
        # Simulate time passing beyond first_token_timeout
        results = tc.check_timeouts(now=time.time() + 0.1)
        assert len(results) == 1
        assert results[0][1] == TimeoutKind.FIRST_TOKEN

    def test_no_timeout_when_chunk_received(self):
        tc = TimeoutChecker(first_token_timeout=0.05)
        tc.register("s1", "c1")
        tc.on_chunk("s1")
        results = tc.check_timeouts(now=time.time() + 0.1)
        # first_token_timeout should not fire since we got a chunk
        kinds = [r[1] for r in results]
        assert TimeoutKind.FIRST_TOKEN not in kinds

    def test_token_interval_timeout(self):
        tc = TimeoutChecker(
            first_token_timeout=100.0,
            token_interval_timeout=0.05,
            provider_response_timeout=100.0,
        )
        tc.register("s1", "c1")
        tc.on_chunk("s1")  # first token received
        # Simulate gap larger than token_interval_timeout
        timer = tc.get("s1")
        timer.last_seen = time.time() - 0.1
        results = tc.check_timeouts()
        kinds = [r[1] for r in results]
        assert TimeoutKind.TOKEN_INTERVAL in kinds

    def test_provider_response_timeout(self):
        tc = TimeoutChecker(provider_response_timeout=0.05, first_token_timeout=100.0)
        tc.register("s1", "c1")
        results = tc.check_timeouts(now=time.time() + 0.1)
        assert len(results) == 1
        assert results[0][1] == TimeoutKind.PROVIDER_RESPONSE

    def test_remove_session(self):
        tc = TimeoutChecker()
        tc.register("s1", "c1")
        tc.remove("s1")
        assert tc.get("s1") is None

    def test_timeout_details_contain_corr_id(self):
        tc = TimeoutChecker(first_token_timeout=0.0)
        tc.register("s1", "c1")
        results = tc.check_timeouts(now=time.time() + 1.0)
        session_id, kind, details = results[0]
        assert kind == TimeoutKind.FIRST_TOKEN
        assert session_id == "s1"
        assert details["corr_id"] == "c1"
