import time
import functools
from typing import Callable, Any, Type, Tuple

from . import applog


def retry_with_exponential_backoff(
    retries: int = 3,
    backoff_in_seconds: float = 1.0,
    max_backoff_in_seconds: float = 30.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator to retry a function call with exponential backoff on retryable exceptions.

    Args:
        retries: Maximum number of retry attempts.
        backoff_in_seconds: Initial backoff delay in seconds.
        max_backoff_in_seconds: Maximum cap on backoff delay.
        retryable_exceptions: Tuple of Exception classes that trigger a retry.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            x = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    if x >= retries:
                        applog.error(
                            f"Function '{func.__name__}' failed after {retries} retries. Error: {e}"
                        )
                        raise e
                    
                    sleep_time = min(backoff_in_seconds * (2 ** x), max_backoff_in_seconds)
                    applog.warning(
                        f"Retryable error in '{func.__name__}': {e}. Retrying in {sleep_time:.1f}s (attempt {x + 1}/{retries})..."
                    )
                    time.sleep(sleep_time)
                    x += 1

        return wrapper
    return decorator
