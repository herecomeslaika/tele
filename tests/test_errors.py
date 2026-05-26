# Tests for ErrorCode & make_error_envelope

from app.core.errors import ErrorCode, make_error_envelope
from app.models.envelope import MessageType


class TestErrorCode:
    def test_all_codes_defined(self):
        expected = {
            "INVALID_MESSAGE_TYPE",
            "MISSING_CORRELATION_FIELDS",
            "OUT_OF_ORDER_STREAM",
            "PROVIDER_TIMEOUT",
            "FIRST_TOKEN_TIMEOUT",
            "TOKEN_INTERVAL_TIMEOUT",
            "MESSAGE_AFTER_TERMINAL",
            "ILLEGAL_STATE_TRANSITION",
            "SESSION_NOT_FOUND",
        }
        assert {c.value for c in ErrorCode} == expected


class TestMakeErrorEnvelope:
    def test_basic_error(self):
        env = make_error_envelope(
            code=ErrorCode.INVALID_MESSAGE_TYPE,
            detail="bad type",
            session_id="s1",
            corr_id="c1",
        )
        assert env.type == MessageType.ERROR
        assert env.payload["code"] == "INVALID_MESSAGE_TYPE"
        assert env.payload["detail"] == "bad type"
        assert env.session_id == "s1"
        assert env.corr_id == "c1"

    def test_original_seq_included(self):
        env = make_error_envelope(
            code=ErrorCode.OUT_OF_ORDER_STREAM,
            detail="gap",
            session_id="s1",
            corr_id="c1",
            original_seq=5,
        )
        assert env.payload["original_seq"] == 5

    def test_original_seq_omitted_when_none(self):
        env = make_error_envelope(
            code=ErrorCode.PROVIDER_TIMEOUT,
            detail="slow",
            session_id="s1",
        )
        assert "original_seq" not in env.payload
