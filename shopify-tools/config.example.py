"""
Example configuration for MZBL Shopify Tools.

Copy this file to config.py and replace the placeholder values.
Do not commit config.py to git as it contains sensitive credentials.
"""

# rembg.com API settings
REMBG_API_URL = "https://api.rembg.com/rmbg"
REMBG_API_KEY = "your-rembg-api-key"
REMBG_TIMEOUT = 30  # Timeout in seconds for image processing requests

# Default background replacement color (#ffffff or #ffffffff)
DEFAULT_BG_COLOR = "#ffffff"

# Shopify App Credentials & Store API settings
SHOPIFY_STORE_URL = "your-shop.myshopify.com"
SHOPIFY_CLIENT_ID = "your-shopify-client-id"
SHOPIFY_CLIENT_SECRET = "your-shopify-client-secret"
SHOPIFY_ADMIN_API_ACCESS_TOKEN = "shpat_xxxxxxxxxxxxxxxxxxxxxxxx"
SHOPIFY_API_VERSION = "2024-04"

# GCP Pub/Sub & Webhook Integration settings
SHOPIFY_PUBSUB_SERVICE_ACCOUNT = "delivery@shopify-pubsub-webhooks.iam.gserviceaccount.com"

# Idempotency Metafield settings (for Stage 3+)
SHOPIFY_METAFIELD_NAMESPACE = "custom"
SHOPIFY_METAFIELD_KEY = "bg_removed"

# Rate limiting / Queue settings (for Stage 4/5)
MAX_RETRIES = 3
RETRY_DELAY = 5
