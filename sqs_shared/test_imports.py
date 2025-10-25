#!/usr/bin/env python3
"""
Simple import test to verify the sqs_shared library structure is correct
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("🧪 Testing sqs_shared library structure...\n")

# Test module imports
try:
    import sqs_shared
    print("✅ sqs_shared module imports successfully")
except ImportError as e:
    print(f"❌ Failed to import sqs_shared: {e}")
    sys.exit(1)

# Test submodule imports
try:
    from sqs_shared import rate_limiter
    print("✅ rate_limiter submodule imports successfully")
except ImportError as e:
    print(f"❌ Failed to import rate_limiter: {e}")
    sys.exit(1)

try:
    from sqs_shared import config
    print("✅ config submodule imports successfully")
except ImportError as e:
    print(f"❌ Failed to import config: {e}")
    sys.exit(1)

# Test that main exports are available
try:
    from sqs_shared import rate_limited
    print("✅ rate_limited decorator is exported")
except ImportError as e:
    print(f"❌ rate_limited not exported: {e}")
    sys.exit(1)

try:
    from sqs_shared import load_config_from_path, load_config_from_env
    print("✅ config helpers are exported")
except ImportError as e:
    print(f"❌ config helpers not exported: {e}")
    sys.exit(1)

# Check __all__ exports
print(f"\n📦 Exported items: {sqs_shared.__all__}")
print(f"📌 Version: {sqs_shared.__version__}")

print("\n🎉 All import tests passed!")
print("✅ Library structure is correct")


