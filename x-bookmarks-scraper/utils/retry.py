"""
Generic retry decorator for resilient operations.

Provides configurable retry logic with exponential backoff for handling
transient failures in network requests, element lookups, and page loads.
This is critical for browser automation where timing issues are common.
"""

import asyncio
import functools
import random
from typing import Any, Callable, Tuple, Type

from loguru import logger


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    jitter: bool = True,
) -> Callable:
    """
    Async retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts (including first try).
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay cap for exponential backoff.
        exceptions: Tuple of exception types that trigger a retry.
        jitter: Whether to add random jitter to delays (prevents thundering herd).

    Returns:
        Decorated function with retry behavior.

    Example:
        @retry(max_attempts=3, exceptions=(TimeoutError,))
        async def load_page(page, url):
            await page.goto(url)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    if attempt == max_attempts:
                        logger.error(
                            "All {} attempts exhausted for '{}': {}",
                            max_attempts,
                            func.__name__,
                            exc,
                        )
                        raise

                    # Exponential backoff: delay doubles each attempt
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    if jitter:
                        delay += random.uniform(0, delay * 0.5)

                    logger.warning(
                        "Attempt {}/{} for '{}' failed ({}). Retrying in {:.1f}s...",
                        attempt,
                        max_attempts,
                        func.__name__,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

            # Should never reach here, but satisfy type checkers
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
