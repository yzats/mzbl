"""
Squarespace Shared Library

A shared library for interacting with Squarespace API, providing:
- Rate limiting for API requests
- Inventory downloading and caching
- SKU-based product lookup with case-insensitive matching
"""

from .inventory_manager import SquarespaceInventoryManager
from .rate_limiter import rate_limited
from .config import load_config_from_path, load_config_from_env

__version__ = "1.0.0"
__all__ = [
    'SquarespaceInventoryManager',
    'rate_limited',
    'load_config_from_path',
    'load_config_from_env',
]


