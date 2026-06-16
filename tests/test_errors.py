"""Tests for the current structured error registry and error envelopes."""

from app.core.errors import (
    BAD_REQUEST,
    FIRST_TOKEN_TIMEOUT,
    PROVIDER_ERROR,
    SEQ_GAP,
    all_error_codes,
    get_error_def,
)
from app.models.envelope import MessageType, make_error_envelope


class TestErrorRegistry:
    def test_core_codes_defined(self):
        codes = all_error_codes()
        for expected in {
            "BAD_REQUEST",
            "UNKNOWN_SESSION",
            "SEQ_GAP",
            "PROVIDER_ERROR",
            "FIRST_TOKEN_TIMEOUT",
            "MSG_AFTER_TERMINAL",
            "AUTH_FAILED",
            "AGENT_NOT_FOUND",
        }:
            assert expected in codes

    def test_error_metadata_shape(self):
        assert BAD_REQUEST.source == "gateway"
        assert BAD_REQUEST.recoverable is False
        assert SEQ_GAP.recoverable is True
        assert SEQ_GAP.retry_recommended is True
        assert PROVIDER_ERROR.source == "provider"
        assert FIRST_TOKEN_TIMEOUT.retry_recommended is True

    def test_unknown_code_falls_back_to_internal(self):
        fallback = get_error_def("DOES_NOT_EXIST")
        assert fallback.code == "INTERNAL_ERROR"


class TestMakeErrorEnvelope:
    def test_basic_error(self):
        env = make_error_envelope(
            session_id="s1",
            corr_id="c1",
            error_code=BAD_REQUEST.code,
            message="bad request",
        )
        assert env.type == MessageType.ERROR
        assert env.payload["error_code"] == "BAD_REQUEST"
        assert env.payload["message"] == "bad request"
        assert env.session_id == "s1"
        assert env.corr_id == "c1"

    def test_error_flags_are_included(self):
        env = make_error_envelope(
            session_id="s1",
            corr_id="c1",
            error_code=SEQ_GAP.code,
            message=SEQ_GAP.description,
            recoverable=SEQ_GAP.recoverable,
            retry_recommended=SEQ_GAP.retry_recommended,
            seq=5,
        )
        assert env.seq == 5
        assert env.payload["recoverable"] is True
        assert env.payload["retry_recommended"] is True
