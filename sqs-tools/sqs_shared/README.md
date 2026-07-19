# Squarespace Shared Library

A reusable Python library for interacting with the Squarespace API, providing inventory management, caching, and SKU lookup functionality.

## Features

- **Rate Limiting**: Decorator-based rate limiting for API requests
- **Inventory Management**: Download and cache Squarespace product inventory
- **SKU Lookup**: Fast, case-insensitive SKU-based product lookup
- **Caching**: File-based caching with age tracking and user prompts

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Basic Example

```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqs_shared import SquarespaceInventoryManager

# Initialize the manager
manager = SquarespaceInventoryManager(
    api_key="your-api-key",
    site_id="your-site-id",
    cache_filename="products_cache.json",
    requests_per_minute=300
)

# Get products with caching
products = manager.get_products_with_cache(force_refresh=False)

# Look up a product by SKU (case-insensitive)
product = manager.get_product_by_sku("ABC123")
if product:
    print(f"Found product: {product.get('title')}")
```

### Using Rate Limiter

```python
from sqs_shared import rate_limited

@rate_limited(60)  # 60 requests per minute
def my_api_call():
    # Your API call here
    pass
```

## API Reference

### SquarespaceInventoryManager

Main class for managing Squarespace product inventory.

#### Constructor

```python
SquarespaceInventoryManager(
    api_key: str,
    site_id: Optional[str] = None,
    cache_filename: str = "squarespace_products_cache.json",
    requests_per_minute: int = 300
)
```

#### Methods

- `get_products() -> List[Dict]`: Download all products from Squarespace
- `get_products_with_cache(force_refresh: bool = False) -> List[Dict]`: Get products with caching and user prompts
- `get_product_by_sku(sku: str, products: Optional[List[Dict]] = None) -> Optional[Dict]`: Look up product by SKU (case-insensitive)
- `build_sku_lookup(products: List[Dict]) -> Dict[str, List[Dict]]`: Build SKU lookup dictionary
- `save_to_cache(products: List[Dict]) -> None`: Save products to cache file
- `load_from_cache() -> List[Dict]`: Load products from cache file
- `get_cache_age() -> Optional[timedelta]`: Get age of cache file
- `format_cache_age(age: timedelta) -> str`: Format cache age as human-readable string

### rate_limited Decorator

```python
@rate_limited(requests_per_minute: int)
def your_function():
    pass
```

Decorator to rate-limit function calls. Set `requests_per_minute` to 0 or negative to disable.

## Case-Insensitive SKU Matching

The library automatically handles case-insensitive SKU matching by normalizing all SKUs to uppercase. This means:

- Directory name `SQ5011818` matches Squarespace SKU `sq5011818`
- Directory name `abc123` matches Squarespace SKU `ABC123`
- Any mixed-case combination will match correctly

The library will log when case normalization occurs and warn about potential conflicts when multiple SKUs differ only by case.

## Dependencies

- `requests>=2.31.0`
- `typing-extensions>=4.0.0` (Python < 3.8 only)

## License

Internal use only.


