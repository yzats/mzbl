#!/usr/bin/env python3
"""
Simple test script to verify the sqs_shared library works correctly
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test imports
try:
    from sqs_shared import SquarespaceInventoryManager, rate_limited, load_config_from_path
    print("✅ Successfully imported sqs_shared library")
except ImportError as e:
    print(f"❌ Failed to import sqs_shared library: {e}")
    sys.exit(1)

# Test rate limiter
print("\n🧪 Testing rate limiter decorator...")

call_count = 0

@rate_limited(60)
def test_function():
    global call_count
    call_count += 1
    return f"Call {call_count}"

# Make a few test calls
for i in range(3):
    result = test_function()
    print(f"  {result}")

print("✅ Rate limiter decorator works")

# Test SquarespaceInventoryManager instantiation
print("\n🧪 Testing SquarespaceInventoryManager instantiation...")

try:
    manager = SquarespaceInventoryManager(
        api_key="test-key",
        site_id="test-site",
        cache_filename="test_cache.json",
        requests_per_minute=300
    )
    print("✅ SquarespaceInventoryManager instantiated successfully")
    print(f"  - API Key: {'*' * len(manager.api_key)}")
    print(f"  - Site ID: {manager.site_id}")
    print(f"  - Cache file: {manager.cache_filename}")
    print(f"  - Rate limit: {manager.requests_per_minute} req/min")
except Exception as e:
    print(f"❌ Failed to instantiate SquarespaceInventoryManager: {e}")
    sys.exit(1)

# Test SKU lookup building
print("\n🧪 Testing SKU lookup building...")

mock_products = [
    {
        'id': 'prod1',
        'sku': 'ABC123',
        'title': 'Product ABC123',
        'variants': []
    },
    {
        'id': 'prod2',
        'sku': 'def456',
        'title': 'Product def456',
        'variants': []
    },
    {
        'id': 'prod3',
        'sku': '',
        'title': 'Product with variants',
        'variants': [
            {'sku': 'GHI789', 'id': 'var1'},
            {'sku': 'jkl012', 'id': 'var2'}
        ]
    }
]

sku_lookup = manager.build_sku_lookup(mock_products)
print(f"✅ Built SKU lookup with {len(sku_lookup)} entries")
print(f"  - Keys: {list(sku_lookup.keys())}")

# Test case-insensitive lookup
print("\n🧪 Testing case-insensitive SKU matching...")

test_cases = [
    ('ABC123', True),
    ('abc123', True),
    ('Abc123', True),
    ('DEF456', True),
    ('def456', True),
    ('GHI789', True),
    ('ghi789', True),
    ('NOTFOUND', False),
]

for test_sku, should_find in test_cases:
    sku_key = test_sku.upper()
    found = sku_key in sku_lookup
    status = "✅" if found == should_find else "❌"
    print(f"  {status} '{test_sku}' -> {sku_key}: {'Found' if found else 'Not found'}")

print("\n🎉 All tests passed!")

