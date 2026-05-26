"""A2A_min_v1 I/O Policy Filtering — configurable input/output filtering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.errors import EMPTY_REQUEST, INPUT_TOO_LONG, OUTPUT_TOO_LONG


@dataclass
class FilterConfig:
    """Configuration for I/O policy filtering."""

    reject_empty: bool = True
    max_input_chars: int = 10000
    max_output_chars: int = 50000
    sensitive_fields: list[str] = field(default_factory=lambda: [
        "api_key", "password", "token", "secret", "authorization",
    ])
    mask_char: str = "****"
    log_hits: bool = True


@dataclass
class FilterResult:
    passed: bool
    error_code: Optional[str] = None
    reason: str = ""
    masked_data: Optional[dict] = None


@dataclass
class PolicyFilter:
    """Configurable I/O policy filter.

    Filtering layers:
      - Protocol layer: empty request rejection (missing required envelope fields)
      - Gateway layer: input/output length limits, rate limiting
      - Application layer: sensitive field masking

    All policies are configurable through FilterConfig.
    """

    config: FilterConfig = field(default_factory=FilterConfig)
    _hit_log: list[dict] = field(default_factory=list)

    def filter_input(self, payload: dict) -> FilterResult:
        """Apply input filtering policies. Returns FilterResult."""
        # Empty request check (protocol layer)
        if self.config.reject_empty:
            prompt = payload.get("prompt", "")
            messages = payload.get("messages", [])
            if not prompt and not messages:
                self._log_hit("empty_request", payload)
                return FilterResult(
                    passed=False,
                    error_code=EMPTY_REQUEST.code,
                    reason="请求内容为空：prompt和messages均为空",
                )

        # Input length check (gateway layer)
        text = payload.get("prompt", "")
        if isinstance(text, str) and len(text) > self.config.max_input_chars:
            self._log_hit("input_too_long", payload, length=len(text))
            return FilterResult(
                passed=False,
                error_code=INPUT_TOO_LONG.code,
                reason=f"输入过长：{len(text)} > {self.config.max_input_chars}",
            )

        # Sensitive field masking (application layer)
        masked = self._mask_sensitive(payload)

        return FilterResult(passed=True, masked_data=masked)

    def filter_output(self, content: str) -> FilterResult:
        """Apply output filtering policies."""
        if len(content) > self.config.max_output_chars:
            self._log_hit("output_too_long", {}, length=len(content))
            return FilterResult(
                passed=False,
                error_code=OUTPUT_TOO_LONG.code,
                reason=f"输出过长：{len(content)} > {self.config.max_output_chars}",
            )
        return FilterResult(passed=True)

    def _mask_sensitive(self, data: dict) -> dict:
        masked = {}
        for k, v in data.items():
            if k.lower() in self.config.sensitive_fields:
                if isinstance(v, str) and len(v) > 4:
                    masked[k] = v[:2] + self.config.mask_char + v[-2:]
                else:
                    masked[k] = self.config.mask_char
            elif isinstance(v, dict):
                masked[k] = self._mask_sensitive(v)
            else:
                masked[k] = v
        return masked

    def _log_hit(self, rule: str, payload: dict, **extra: any) -> None:
        if self.config.log_hits:
            self._hit_log.append({"rule": rule, "payload_keys": list(payload.keys()), **extra})

    def get_hit_log(self) -> list[dict]:
        return list(self._hit_log)
