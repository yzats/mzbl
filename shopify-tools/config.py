"""
Configuration for MZBL Shopify Tools.

Do not commit config.py to git as it contains sensitive credentials.
"""

# rembg.com API settings
REMBG_API_URL = "https://api.rembg.com/rmbg"
REMBG_API_KEY = "47410563-48a8-49e9-bc1f-07a5bb895d88"
REMBG_TIMEOUT = 30  # Timeout in seconds for image processing requests

# Default background replacement color (#ffffff or #ffffffff)
DEFAULT_BG_COLOR = "#ffffff"

# Shopify API settings
SHOPIFY_STORE_URL = "your-shop.myshopify.com"
SHOPIFY_ADMIN_API_ACCESS_TOKEN = "shpat_xxxxxxxxxxxxxxxxxxxxxxxx"
SHOPIFY_API_VERSION = "2024-04"

# Idempotency Metafield settings
SHOPIFY_METAFIELD_NAMESPACE = "custom"
SHOPIFY_METAFIELD_KEY = "bg_removed"

# Rate limiting / Queue settings
MAX_RETRIES = 3
RETRY_DELAY = 5
