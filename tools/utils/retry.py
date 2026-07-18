"""Retry decorators with exponential backoff. No external deps (avoids tenacity)."""

import functools
import sys
import time


def with_retry(max_attempts: int = 3, base_wait: float = 2.0, max_wait: float = 30.0,
               exceptions=(Exception,), name: str = ""):
    """Decorator: retry a function on exception with exponential backoff.

    Args:
        max_attempts: total tries (including first attempt).
        base_wait: seconds for first backoff (doubled each retry).
        max_wait: cap on backoff sleep.
        exceptions: tuple of exception types to retry on. Default = all.
        name: optional label for log messages (defaults to function name).
    """
    def decorator(fn):
        label = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    if attempt == max_attempts - 1:
                        raise
                    wait = min(max_wait, base_wait * (2 ** attempt))
                    print(
                        f"[retry] {label} attempt {attempt + 1}/{max_attempts} failed: "
                        f"{type(e).__name__}: {e}; sleeping {wait:.1f}s",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
            raise last_err  # unreachable but satisfies linters
        return wrapper
    return decorator


# Pre-configured decorators
api_retry = with_retry(max_attempts=3, base_wait=2.0, max_wait=30.0)
claude_retry = with_retry(max_attempts=4, base_wait=5.0, max_wait=60.0)
scrape_retry = with_retry(max_attempts=2, base_wait=1.0, max_wait=10.0)
