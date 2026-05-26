"""A2A_min_v1 Retry Manager — limited retry for recoverable errors."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from app.core.errors import get_error_def


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0          # seconds
    max_delay: float = 30.0
    backoff_factor: float = 2.0      # exponential backoff multiplier


@dataclass
class RetryResult:
    success: bool
    attempts: int
    last_error_code: Optional[str] = None
    last_error_msg: Optional[str] = None
    total_delay: float = 0.0


@dataclass
class RetryManager:
    """Retry mechanism for recoverable errors.

    Only retries errors marked as recoverable in the ErrorCodeDef registry.
    Uses exponential backoff between retries.
    """

    config: RetryConfig = field(default_factory=RetryConfig)

    def _compute_delay(self, attempt: int) -> float:
        delay = self.config.base_delay * (self.config.backoff_factor ** (attempt - 1))
        return min(delay, self.config.max_delay)

    async def execute_with_retry(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> RetryResult:
        """Execute an async function with retry on recoverable errors.

        The function should return a result or raise an exception with
        an error_code attribute.
        """
        attempts = 0
        total_delay = 0.0
        last_error_code = None
        last_error_msg = None

        while attempts < self.config.max_retries + 1:
            attempts += 1
            try:
                result = await fn(*args, **kwargs)
                if hasattr(result, "type") and result.type == "ERROR":
                    payload = result.payload if hasattr(result, "payload") else {}
                    error_code = payload.get("error_code", "INTERNAL_ERROR")
                    error_def = get_error_def(error_code)

                    if not error_def.recoverable:
                        return RetryResult(
                            success=False,
                            attempts=attempts,
                            last_error_code=error_code,
                            last_error_msg=payload.get("message", str(payload)),
                        )

                    last_error_code = error_code
                    last_error_msg = payload.get("message", str(payload))

                    if attempts > self.config.max_retries:
                        return RetryResult(
                            success=False,
                            attempts=attempts,
                            last_error_code=last_error_code,
                            last_error_msg=last_error_msg,
                            total_delay=total_delay,
                        )

                    delay = self._compute_delay(attempts)
                    total_delay += delay
                    await asyncio.sleep(delay)
                    continue

                return RetryResult(success=True, attempts=attempts, total_delay=total_delay)

            except Exception as e:
                error_code = getattr(e, "error_code", "INTERNAL_ERROR")
                error_def = get_error_def(error_code)

                last_error_code = error_code
                last_error_msg = str(e)

                if not error_def.recoverable:
                    return RetryResult(
                        success=False,
                        attempts=attempts,
                        last_error_code=error_code,
                        last_error_msg=last_error_msg,
                    )

                if attempts > self.config.max_retries:
                    return RetryResult(
                        success=False,
                        attempts=attempts,
                        last_error_code=last_error_code,
                        last_error_msg=last_error_msg,
                        total_delay=total_delay,
                    )

                delay = self._compute_delay(attempts)
                total_delay += delay
                await asyncio.sleep(delay)

        return RetryResult(
            success=False,
            attempts=attempts,
            last_error_code=last_error_code,
            last_error_msg=last_error_msg,
            total_delay=total_delay,
        )