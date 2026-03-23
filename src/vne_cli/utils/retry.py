"""Retry logic with exponential backoff and jitter for API calls."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from vne_cli.providers.errors import ProviderRateLimitError
from vne_cli.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Execute an async function with exponential backoff on failure.

    Args:
        fn: Async callable to execute.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        retryable_exceptions: Exception types that trigger a retry.

    Returns:
        The result of fn().

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except retryable_exceptions as e:
            last_exception = e

            if attempt == max_retries:
                logger.error(
                    "All %d retries exhausted. Last error: %s",
                    max_retries,
                    e,
                )
                raise

            # Respect Retry-After for rate limit errors
            if isinstance(e, ProviderRateLimitError) and e.retry_after is not None:
                delay = e.retry_after
            else:
                delay = min(base_delay * (2**attempt), max_delay)
                # Add jitter (0.5x to 1.5x)
                delay *= 0.5 + random.random()  # noqa: S311

            logger.warning(
                "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                attempt + 1,
                max_retries + 1,
                e,
                delay,
            )
            await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checker
    assert last_exception is not None  # noqa: S101
    raise last_exception
