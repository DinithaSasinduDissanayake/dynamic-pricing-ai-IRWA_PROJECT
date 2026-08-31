from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Tuple, Type, Union, Optional


async def retry(
    fn: Callable[..., Any],
    *args: Any,
    attempts: int = 3,
    delay: float = 0.0,
    backoff: float = 1.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
    **kwargs: Any,
) -> Any:
    """
    Execute a callable (async or sync) and retry up to `attempts` times upon exceptions.

    :param fn: Async or sync callable to execute.
    :param attempts: Maximum number of attempts (must be >= 1).
    :param delay: Initial delay between retry attempts in seconds.
    :param backoff: Multiplier applied to delay after each failure.
    :param exceptions: Exception type or tuple of exception types to catch and retry.
    :return: The return value of `fn`.
    """
    max_attempts = max(1, int(attempts))
    cur_delay = max(0.0, float(delay))
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            if inspect.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            res = fn(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res
        except exceptions as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
            if cur_delay > 0:
                await asyncio.sleep(cur_delay)
                cur_delay *= backoff

    if last_exc is not None:
        raise last_exc
