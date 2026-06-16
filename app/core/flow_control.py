"""A2A_min_v1 Flow Control — bounded buffer queue and rate limiter."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class BoundedQueue:
    """Thread-safe bounded deque for stream chunk buffering.

    By default, a full queue refuses new items so callers can apply real
    backpressure. Legacy drop-oldest behavior is still available by setting
    drop_oldest=True.
    """

    max_length: int = 1000
    drop_oldest: bool = False
    _queue: deque = field(default_factory=deque)
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    def push(self, item: object) -> bool:
        """Try to push an item without waiting.

        Returns False when the queue is full. If drop_oldest=True, the oldest
        item is dropped and False still signals that backpressure occurred.
        """
        was_full = len(self._queue) >= self.max_length
        if was_full:
            if not self.drop_oldest:
                return False
            self._queue.popleft()
        self._queue.append(item)
        return not was_full

    async def put(self, item: object, timeout: float | None = None) -> bool:
        """Wait until space is available, then enqueue the item.

        Returns False if timeout expires before space is available.
        """
        async with self._condition:
            if self.drop_oldest:
                return self.push(item)

            start = time.monotonic()
            while len(self._queue) >= self.max_length:
                if timeout is None:
                    await self._condition.wait()
                    continue
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    return False
                try:
                    await asyncio.wait_for(self._condition.wait(), remaining)
                except asyncio.TimeoutError:
                    return False
            self._queue.append(item)
            self._condition.notify_all()
            return True

    def pop(self) -> object | None:
        """Pop the oldest item, or None if empty."""
        if self._queue:
            item = self._queue.popleft()
            self._notify_space_available()
            return item
        return None

    async def get(self, timeout: float | None = None) -> object | None:
        """Wait for an item and pop it, returning None on timeout."""
        async with self._condition:
            start = time.monotonic()
            while not self._queue:
                if timeout is None:
                    await self._condition.wait()
                    continue
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    return None
                try:
                    await asyncio.wait_for(self._condition.wait(), remaining)
                except asyncio.TimeoutError:
                    return None
            item = self._queue.popleft()
            self._condition.notify_all()
            return item

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

    def _notify_space_available(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def notify() -> None:
            async with self._condition:
                self._condition.notify_all()

        loop.create_task(notify())


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

    async def wait_and_acquire(self, tokens: int = 1) -> bool:
        """Async wait until tokens are available, then consume them."""
        while not self.acquire(tokens):
            await asyncio.sleep(0.01)
        return True

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now
