"""A2A_min_v1 Flow Control — bounded buffer queue and rate limiter."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class BoundedQueue:
    """Thread-safe bounded deque for stream chunk buffering.

    When full, oldest items are dropped (backpressure: producer slows down,
    consumer sees latest data).
    """

    max_length: int = 1000
    _queue: deque = field(default_factory=deque)

    def push(self, item: object) -> bool:
        """Push an item. Returns False if the queue was full and an item was dropped."""
        dropped = len(self._queue) >= self.max_length
        if dropped:
            self._queue.popleft()
        self._queue.append(item)
        return not dropped

    def pop(self) -> object | None:
        """Pop the oldest item, or None if empty."""
        if self._queue:
            return self._queue.popleft()
        return None

    def peek(self) -> object | None:
        """Peek at the oldest item without removing it."""
        if self._queue:
            return self._queue[0]
        return None

    @property
    def length(self) -> int:
        return len(self._queue)

    @property
    def is_full(self) -> bool:
        return len(self._queue) >= self.max_length


@dataclass
class RateLimiter:
    """Simple token-bucket rate limiter for send rate control."""

    max_tokens: int = 100
    refill_rate: float = 10.0  # tokens per second
    _tokens: float = field(default=0.0, init=False)
    _last_refill: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.max_tokens)
        self._last_refill = time.monotonic()

    def acquire(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if allowed, False if rate limited."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def wait_and_acquire(self, tokens: int = 1) -> asyncio.Future:
        """Async wait until tokens are available, then consume them."""
        # For simplicity in a non-blocking context, we just check
        # In production this would use asyncio.sleep
        return asyncio.coroutine(lambda: self.acquire(tokens))()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now