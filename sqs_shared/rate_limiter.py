"""
Rate limiting decorator for API requests

This module provides a decorator to rate-limit function calls, useful for
respecting API rate limits.
"""

import time
import functools
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


def rate_limited(requests_per_minute: int) -> Callable:
    """
    Decorator to rate-limit function calls.
    
    Args:
        requests_per_minute: Maximum number of requests allowed per minute.
                           Set to 0 or negative to disable rate limiting.
    
    Usage:
        @rate_limited(60)
        def my_api_call():
            # Make API request
            pass
    """
    def decorator(func: Callable) -> Callable:
        # Store request timestamps for this specific function
        request_times = []
        
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal request_times
            
            # Skip rate limiting if disabled
            if requests_per_minute <= 0:
                return func(*args, **kwargs)
            
            current_time = time.time()
            
            # Remove requests older than 1 minute
            request_times = [t for t in request_times if current_time - t < 60.0]
            
            # If we've made too many requests in the last minute, wait
            if len(request_times) >= requests_per_minute:
                oldest_request = min(request_times)
                wait_time = 60.0 - (current_time - oldest_request) + 0.1  # Add small buffer
                if wait_time > 0:
                    logger.debug(f"Rate limit reached for {func.__name__}, waiting {wait_time:.1f} seconds")
                    time.sleep(wait_time)
                    current_time = time.time()
            
            # Record this request
            request_times.append(current_time)
            
            # Call the actual function
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


