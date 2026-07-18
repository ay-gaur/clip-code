"""Async token-bucket rate limiter for API calls. Same as B2B repo's version + apify_limiter."""

import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter — async safe."""

    def __init__(self, rate: float, max_tokens: int = None):
        """
        Args:
            rate: Requests per second allowed.
            max_tokens: Max burst size (defaults to max(1, int(rate))).
        """
        self.rate = rate
        self.max_tokens = max_tokens if max_tokens is not None else max(1, int(rate))
        self.tokens = self.max_tokens
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available, then consume one."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.max_tokens, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                now2 = time.monotonic()
                elapsed2 = now2 - self.last_refill
                self.tokens = min(self.max_tokens, self.tokens + elapsed2 * self.rate)
                self.last_refill = now2

            self.tokens -= 1

    def acquire_sync(self):
        """Synchronous variant — uses time.sleep instead of asyncio.sleep."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens < 1:
            wait_time = (1 - self.tokens) / self.rate
            time.sleep(wait_time)
            now2 = time.monotonic()
            elapsed2 = now2 - self.last_refill
            self.tokens = min(self.max_tokens, self.tokens + elapsed2 * self.rate)
            self.last_refill = now2

        self.tokens -= 1


# Pre-configured limiters
apollo_limiter = RateLimiter(rate=3, max_tokens=3)        # 3 req/sec
tavily_limiter = RateLimiter(rate=1, max_tokens=1)        # 1 req/sec
claude_limiter = RateLimiter(rate=4, max_tokens=4)        # 4 req/sec (Acme Studio account limit)
firecrawl_limiter = RateLimiter(rate=2, max_tokens=2)     # 2 req/sec (free tier)
hunter_limiter = RateLimiter(rate=2, max_tokens=2)        # 2 req/sec
apify_limiter = RateLimiter(rate=2, max_tokens=4)         # 2 req/sec (Apify polls + dataset reads)
