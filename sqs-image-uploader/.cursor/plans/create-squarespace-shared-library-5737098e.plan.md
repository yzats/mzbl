<!-- 5737098e-3c9e-4c63-b29e-4b83475234e3 60e4cd33-1f41-4477-baee-1964f8709fff -->
# Create Squarespace Shared Library

## Overview

Create a shared library in `/Users/yzats/devl/mzbl/sqs_shared/` containing reusable Squarespace API functionality. The library will handle rate limiting, inventory downloading/caching, and SKU lookups with case-insensitive matching.

## Library Structure

### 1. Create `/Users/yzats/devl/mzbl/sqs_shared/` directory

- New folder at parent level of sqs-image-uploader

### 2. Create `/Users/yzats/devl/mzbl/sqs_shared/__init__.py`

- Make it a proper Python package
- Export main classes: `SquarespaceInventoryManager`, `rate_limited`

### 3. Create `/Users/yzats/devl/mzbl/sqs_shared/inventory_manager.py`

Main class: `SquarespaceInventoryManager`

**Constructor parameters:**

- `api_key`: Squarespace API key
- `site_id`: Squarespace site ID (optional, for future use)
- `cache_filename`: Path to cache file (default: "squarespace_products_cache.json")
- `requests_per_minute`: Rate limit (default: 300)

**Methods to extract from sqs_image_uploader.py:**

From lines 90-134: `get_products()` - Download all products with pagination

- Keep rate limiting calls
- Keep pagination logic
- Remove image-specific logic

From lines 143-176: `get_products_with_cache()` - Get products with cache and user prompting

- Rename from `_get_products_with_file_cache`
- Include force_refresh parameter
- Keep user prompt logic for cache refresh

From lines 178-185: `get_cache_age()` - Get cache file age

- Rename from `_get_cache_file_age`

From lines 187-204: `format_cache_age()` - Format timedelta to human-readable

- Rename from `_format_age`

From lines 206-222: `save_to_cache()` - Save products to cache file

- Rename from `_save_products_to_cache`

From lines 224-241: `load_from_cache()` - Load products from cache file

- Rename from `_load_products_from_cache`

From lines 243-290: `build_sku_lookup()` - Build case-insensitive SKU dictionary

- Rename from `_build_sku_lookup`
- Takes products list as parameter
- Returns Dict[str, List[Dict]]
- Includes case conflict detection and logging

**New method:** `get_product_by_sku(sku: str, products: List[Dict] = None) -> Optional[Dict]`

- Extract from lines 301-333
- If products not provided, use cached products
- Case-insensitive lookup using uppercase normalization

### 4. Create `/Users/yzats/devl/mzbl/sqs_shared/rate_limiter.py`

**Decorator function:** `rate_limited(requests_per_minute: int)`

- Extract logic from lines 68-88 (`_rate_limit` method)
- Implement as decorator that can wrap any function
- Maintain request timestamps per decorated function
- Use functools.wraps to preserve function metadata

### 5. Create `/Users/yzats/devl/mzbl/sqs_shared/config.py`

- Read from `../sqs-image-uploader/config.py` (or other script folders)
- Provide helper function: `load_config_from_path(config_path: str)`
- Return dict with API_KEY, SITE_ID, REQUESTS_PER_MINUTE

### 6. Create `/Users/yzats/devl/mzbl/sqs_shared/requirements.txt`

```
requests>=2.31.0
typing-extensions>=4.0.0; python_version < "3.8"
```

## Update sqs_image_uploader.py

### Refactor to use shared library:

1. Add import at top:
```python
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sqs_shared import SquarespaceInventoryManager
```

2. In `__init__` (lines 30-66):

- Create `SquarespaceInventoryManager` instance
- Remove rate limiting setup (lines 44-47)
- Remove cache variables (lines 49-51)

3. Remove methods (delegate to library):

- Lines 68-88: `_rate_limit()` - Use library's rate limiter
- Lines 90-134: `get_products()` - Use `inventory_manager.get_products()`
- Lines 136-141: `_get_cached_products()` - Use `inventory_manager.get_products_with_cache()`
- Lines 143-176: `_get_products_with_file_cache()` - Removed
- Lines 178-185: `_get_cache_file_age()` - Removed
- Lines 187-204: `_format_age()` - Removed
- Lines 206-222: `_save_products_to_cache()` - Removed
- Lines 224-241: `_load_products_from_cache()` - Removed
- Lines 243-290: `_build_sku_lookup()` - Use `inventory_manager.build_sku_lookup()`
- Lines 301-333: `get_product_by_sku()` - Use `inventory_manager.get_product_by_sku()`

4. Update method calls throughout:

- Replace `self.get_product_by_sku(sku)` with `self.inventory_manager.get_product_by_sku(sku)`
- Replace `self._get_cached_products()` with `self.inventory_manager.get_products_with_cache(...)`

## Key Design Decisions

1. **User prompts stay in library** - The `get_products_with_cache()` method will handle the interactive prompt
2. **SKU lookup included** - Full case-insensitive SKU lookup with conflict detection
3. **Decorator-based rate limiting** - Flexible approach that can wrap any API function
4. **Config from existing files** - Read from each script's config.py to avoid duplication

## Files to Create

- `/Users/yzats/devl/mzbl/sqs_shared/__init__.py`
- `/Users/yzats/devl/mzbl/sqs_shared/inventory_manager.py`
- `/Users/yzats/devl/mzbl/sqs_shared/rate_limiter.py`
- `/Users/yzats/devl/mzbl/sqs_shared/config.py`
- `/Users/yzats/devl/mzbl/sqs_shared/requirements.txt`

## Files to Modify

- `/Users/yzats/devl/mzbl/sqs-image-uploader/sqs_image_uploader.py`

### To-dos

- [ ] Create /Users/yzats/devl/mzbl/sqs_shared/ directory structure
- [ ] Create __init__.py to make sqs_shared a Python package
- [ ] Create rate_limiter.py with decorator-based rate limiting
- [ ] Create inventory_manager.py with SquarespaceInventoryManager class
- [ ] Create config.py with helper to load config from script folders
- [ ] Create requirements.txt for shared library
- [ ] Refactor sqs_image_uploader.py to use shared library
- [ ] Test that image uploader still works with shared library