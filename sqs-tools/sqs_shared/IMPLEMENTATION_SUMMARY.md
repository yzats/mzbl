# Squarespace Shared Library - Implementation Summary

## Overview

Successfully created a shared library (`sqs_shared`) that extracts reusable Squarespace API functionality from `sqs-image-uploader` and makes it available to other scripts.

## What Was Created

### Directory Structure

```
/Users/yzats/devl/mzbl/sqs_shared/
├── __init__.py                 # Package initialization and exports
├── rate_limiter.py            # Rate limiting decorator
├── config.py                  # Configuration helpers
├── inventory_manager.py       # Main inventory management class
├── requirements.txt           # Dependencies
├── README.md                  # Usage documentation
└── test_*.py                  # Test scripts
```

### Files Created

1. **`__init__.py`** - Makes sqs_shared a proper Python package
   - Exports: `SquarespaceInventoryManager`, `rate_limited`, `load_config_from_path`, `load_config_from_env`
   - Version: 1.0.0

2. **`rate_limiter.py`** - Decorator-based rate limiting
   - `@rate_limited(requests_per_minute)` decorator
   - Maintains request timestamps per decorated function
   - Automatically waits when rate limit is reached

3. **`config.py`** - Configuration loading helpers
   - `load_config_from_path(config_path)` - Load from config.py files
   - `load_config_from_env()` - Load from environment variables

4. **`inventory_manager.py`** - Core inventory management
   - `SquarespaceInventoryManager` class
   - Methods for downloading, caching, and looking up products
   - Case-insensitive SKU matching with uppercase normalization
   - Conflict detection for SKUs differing only by case

5. **`requirements.txt`** - Dependencies
   - requests>=2.31.0
   - typing-extensions>=4.0.0 (Python < 3.8)

6. **`README.md`** - Complete usage documentation

## What Was Refactored

### `sqs-image-uploader/sqs_image_uploader.py`

**Removed Methods** (now in shared library):
- `get_products()` - Download products with pagination
- `_get_cached_products()` - Get products from cache
- `_get_products_with_file_cache()` - Cache with user prompting
- `_get_cache_file_age()` - Get cache file age
- `_format_age()` - Format timedelta
- `_save_products_to_cache()` - Save to cache
- `_load_products_from_cache()` - Load from cache
- `_build_sku_lookup()` - Build SKU lookup dictionary
- `get_product_by_sku()` - Look up product by SKU

**Added**:
- Import of `SquarespaceInventoryManager` from shared library
- `self.inventory_manager` instance in `__init__`

**Updated Calls**:
- `self.get_product_by_sku(sku)` → `self.inventory_manager.get_product_by_sku(sku)`
- `self._get_cached_products()` → `self.inventory_manager.get_products_with_cache(force_refresh=...)`

## Key Features

### 1. Case-Insensitive SKU Matching

All SKUs are normalized to uppercase for matching:
- Directory `SQ5011818` matches Squarespace SKU `sq5011818`
- Directory `abc123` matches Squarespace SKU `ABC123`
- Logs when case normalization occurs
- Warns about SKUs differing only by case

### 2. Rate Limiting

Decorator-based approach that can be applied to any function:
```python
@rate_limited(300)  # 300 requests per minute
def my_api_call():
    pass
```

### 3. Caching with User Interaction

- Prompts user to refresh or use cached inventory
- Shows cache age in human-readable format
- Supports force refresh mode
- Automatically falls back to fresh download on cache errors

### 4. Configuration Flexibility

Can load configuration from:
- Script-specific config.py files
- Environment variables
- Direct parameter passing

## Usage Example

```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqs_shared import SquarespaceInventoryManager

# Initialize
manager = SquarespaceInventoryManager(
    api_key="your-api-key",
    site_id="your-site-id",
    cache_filename="products_cache.json",
    requests_per_minute=300
)

# Get products with caching
products = manager.get_products_with_cache(force_refresh=False)

# Look up by SKU (case-insensitive)
product = manager.get_product_by_sku("ABC123")
```

## Testing

All files have been validated:
- ✅ Python syntax is valid for all modules
- ✅ Import structure is correct
- ✅ No linting errors (except expected warnings about uninstalled dependencies)

## Integration Status

### ✅ Completed
- Created shared library structure
- Implemented all core functionality
- Refactored sqs-image-uploader to use shared library
- Validated syntax and structure
- Created documentation

### 📝 Notes
- The library requires `requests` to be installed: `pip install -r requirements.txt`
- Other scripts can now use this library by adding parent directory to path
- The image uploader maintains backward compatibility (same command-line interface)

## Next Steps for Other Scripts

To use this library in other scripts:

1. Add import at top of script:
```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sqs_shared import SquarespaceInventoryManager
```

2. Initialize the manager:
```python
manager = SquarespaceInventoryManager(
    api_key=YOUR_API_KEY,
    site_id=YOUR_SITE_ID,
    cache_filename="cache.json",
    requests_per_minute=300
)
```

3. Use the methods:
```python
products = manager.get_products_with_cache()
product = manager.get_product_by_sku("SKU123")
```

## Files Modified

- `/Users/yzats/devl/mzbl/sqs-image-uploader/sqs_image_uploader.py` - Refactored to use shared library

## Files Created

- `/Users/yzats/devl/mzbl/sqs_shared/__init__.py`
- `/Users/yzats/devl/mzbl/sqs_shared/rate_limiter.py`
- `/Users/yzats/devl/mzbl/sqs_shared/config.py`
- `/Users/yzats/devl/mzbl/sqs_shared/inventory_manager.py`
- `/Users/yzats/devl/mzbl/sqs_shared/requirements.txt`
- `/Users/yzats/devl/mzbl/sqs_shared/README.md`
- `/Users/yzats/devl/mzbl/sqs_shared/IMPLEMENTATION_SUMMARY.md`
- `/Users/yzats/devl/mzbl/sqs_shared/test_*.py` (test scripts)


