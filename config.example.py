"""
Example configuration for MZBL Squarespace scripts.

Copy this file to config.py and replace the placeholder values.
Do not commit config.py; it contains API credentials.
"""

# Squarespace credentials
SQUARESPACE_PRODUCTS_RW_KEY = "your-products-read-write-api-key"
SQUARESPACE_PRODUCTS_INVENTORY_RW_KEY = "your-products-inventory-read-write-api-key"
SQUARESPACE_SITE_ID = "your-site-id"

# Backward-compatible alias used by sqs-image-uploader/test_setup.py.
SQUARESPACE_API_KEY = SQUARESPACE_PRODUCTS_RW_KEY

# Image uploader settings
ICLOUD_FOLDER_PATH = "/Users/your_username/Library/Mobile Documents/com~apple~CloudDocs/MZBL/SQS Upload"
MAX_IMAGES_PER_SKU_FOLDER = 5
MAX_RETRIES = 3

# API throttling. Set to 0 to disable local rate limiting.
REQUESTS_PER_MINUTE = 300
