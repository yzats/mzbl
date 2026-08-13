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

# Shopify App Credentials & Store API settings
SHOPIFY_STORE_URL = "kpj1i3-3t.myshopify.com"
SHOPIFY_CLIENT_ID = "4f0ebfb3dff9884a215fe3dd246f25bb"
SHOPIFY_CLIENT_SECRET = "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"
SHOPIFY_ADMIN_API_ACCESS_TOKEN = "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"
SHOPIFY_API_VERSION = "2024-04"

# GCP Pub/Sub & Webhook Integration settings
SHOPIFY_PUBSUB_SERVICE_ACCOUNT = "delivery@shopify-pubsub-webhooks.iam.gserviceaccount.com"

# Idempotency Metafield settings
SHOPIFY_METAFIELD_NAMESPACE = "custom"
SHOPIFY_METAFIELD_KEY = "bg_removed"

# Rate limiting / Queue settings
MAX_RETRIES = 3
RETRY_DELAY = 5
