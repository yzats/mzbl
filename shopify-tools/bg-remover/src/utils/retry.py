import time
import functools
from typing import Callable, Any, Type, Tuple

from . import applog


def retry_with_exponential_backoff(
    retries: int = 3,
    backoff_in_seconds: float = 1.0,
    max_backoff_in_seconds: float = 30.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    max_in_process_seconds: float = 90.0,
) -> Callable:
    """Decorator to retry a function call with exponential backoff on retryable exceptions.

    If the exception has ``retry_after_seconds``, that wait is used instead of
    exponential backoff. Sleeps that would exceed ``max_in_process_seconds``
    (from the first attempt) are skipped and the exception is re-raised.

    Args:
        retries: Maximum number of retry attempts.
        backoff_in_seconds: Initial backoff delay in seconds.
        max_backoff_in_seconds: Maximum cap on backoff delay.
        retryable_exceptions: Tuple of Exception classes that trigger a retry.
        max_in_process_seconds: Wall-clock budget for sleeps so the worker stays
            under its 120s request timeout.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            x = 0
            deadline = time.monotonic() + max_in_process_seconds
            while True:
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    if x >= retries:
                        applog.error(
                            f"Function '{func.__name__}' failed after {retries} retries. Error: {e}"
                        )
                        raise e

                    sleep_time = _retry_sleep_seconds(
                        e, x, backoff_in_seconds, max_backoff_in_seconds
                    )
                    remaining = deadline - time.monotonic()
                    if sleep_time > remaining:
                        applog.warning(
                            f"Retryable error in '{func.__name__}': {e}. "
                            f"Skip {sleep_time:.1f}s wait (budget {remaining:.1f}s left)."
                        )
                        raise e

                    applog.warning(
                        f"Retryable error in '{func.__name__}': {e}. "
                        f"Retrying in {sleep_time:.1f}s (attempt {x + 1}/{retries})..."
                    )
                    time.sleep(sleep_time)
                    x += 1

        return wrapper
    return decorator


def _retry_sleep_seconds(
    error: BaseException,
    attempt: int,
    backoff_in_seconds: float,
    max_backoff_in_seconds: float,
) -> float:
    raw = getattr(error, "retry_after_seconds", None)
    if raw is not None:
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            seconds = None
        else:
            if seconds >= 0:
                return seconds
    return min(backoff_in_seconds * (2 ** attempt), max_backoff_in_seconds)
