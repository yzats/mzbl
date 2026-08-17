import sys
import json
import logging
from typing import Any, Tuple, Dict, Optional
import functions_framework
from flask import Request

try:
    import config
    SHOPIFY_STORE_URL = getattr(config, "SHOPIFY_STORE_URL", "")
    SHOPIFY_ADMIN_API_ACCESS_TOKEN = getattr(config, "SHOPIFY_ADMIN_API_ACCESS_TOKEN", "")
    SHOPIFY_API_VERSION = getattr(config, "SHOPIFY_API_VERSION", "2024-04")
    REMBG_API_URL = getattr(config, "REMBG_API_URL", "https://api.rembg.com/rmbg")
    REMBG_API_KEY = getattr(config, "REMBG_API_KEY", "")
    DEFAULT_BG_COLOR = getattr(config, "DEFAULT_BG_COLOR", "#ffffff")
    DELETE_ORIGINAL = getattr(config, "DELETE_ORIGINAL", False)
except ImportError:
    import os
    SHOPIFY_STORE_URL = os.environ.get("SHOPIFY_STORE_URL", "")
    SHOPIFY_ADMIN_API_ACCESS_TOKEN = os.environ.get("SHOPIFY_ADMIN_API_ACCESS_TOKEN", "")
    SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2024-04")
    REMBG_API_URL = os.environ.get("REMBG_API_URL", "https://api.rembg.com/rmbg")
    REMBG_API_KEY = os.environ.get("REMBG_API_KEY", "")
    DEFAULT_BG_COLOR = os.environ.get("DEFAULT_BG_COLOR", "#ffffff")
    DELETE_ORIGINAL = os.environ.get("DELETE_ORIGINAL", "false").lower() == "true"

from src.shopify import ShopifyGraphQLClient, ShopifyAPIError
from src.removers import RembgHostedRemover, BackgroundRemoverError, RetryableBackgroundRemoverError
from src.queue.memory_stores import InMemoryLockStore

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Global Product Lock Store for Worker
lock_store = InMemoryLockStore()


def execute_background_removal_job(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Execute background removal job for a product.

    Args:
        payload: Dict containing 'product_id' and optional 'shop_domain'.

    Returns:
        Tuple[Dict[str, Any], int]: Result dict and HTTP status code.
    """
    product_id = payload.get("product_id")
    if not product_id:
        return {"status": "error", "message": "Missing product_id in payload"}, 400

    shop_url = payload.get("shop_domain") or SHOPIFY_STORE_URL
    token = SHOPIFY_ADMIN_API_ACCESS_TOKEN

    if not shop_url or not token:
        logger.error("Missing Shopify credentials for background removal worker job.")
        return {"status": "error", "message": "Shopify API credentials missing"}, 500

    shopify_client = ShopifyGraphQLClient(
        store_url=shop_url,
        access_token=token,
        api_version=SHOPIFY_API_VERSION,
    )
    remover = RembgHostedRemover(api_key=REMBG_API_KEY, api_url=REMBG_API_URL)

    lock_key = f"lock:product:{product_id}"
    if not lock_store.acquire_lock(lock_key, ttl_seconds=120):
        logger.info(f"Product lock active for {product_id}. Skipping duplicate worker run.")
        return {"status": "skipped", "reason": "Product currently processing"}, 200

    try:
        logger.info(f"Worker starting background removal process for Product ID: {product_id}")
        unprocessed_images = shopify_client.get_unprocessed_images(product_id)

        if not unprocessed_images:
            logger.info(f"No unprocessed images found for Product ID: {product_id}. Completed.")
            return {"status": "success", "processed_count": 0, "message": "No unprocessed images"}, 200

        logger.info(f"Found {len(unprocessed_images)} image(s) to process on product {product_id}.")

        from process_product import process_product_batch

        processed_count = process_product_batch(
            shopify_client=shopify_client,
            remover=remover,
            product_id=product_id,
            unprocessed_images=unprocessed_images,
            bg_color=DEFAULT_BG_COLOR,
            delete_original=DELETE_ORIGINAL,
        )

        logger.info(f"Successfully processed {processed_count} image(s) for product {product_id}.")
        return {"status": "success", "processed_count": processed_count}, 200

    except (ShopifyAPIError, BackgroundRemoverError) as e:
        logger.error(f"Error processing background removal for product {product_id}: {e}")
        if isinstance(e, RetryableBackgroundRemoverError):
            return {"status": "error", "message": str(e)}, 503  # HTTP 503 triggers GCP Task Retry
        return {"status": "error", "message": str(e)}, 400

    finally:
        lock_store.release_lock(lock_key)


@functions_framework.http
def bg_remover_worker(request: Request) -> Tuple[Any, int, Dict[str, str]]:
    """GCP Cloud Function (HTTP triggered) / Local Worker endpoint for processing queued tasks.

    Args:
        request: Flask request object from functions_framework.

    Returns:
        Tuple[str, int, Dict[str, str]]: JSON response tuple.
    """
    if request.method != "POST":
        return json.dumps({"error": "Method not allowed"}), 405, {"Content-Type": "application/json"}

    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception as e:
        return json.dumps({"error": f"Invalid JSON payload: {e}"}), 400, {"Content-Type": "application/json"}

    res_dict, status_code = execute_background_removal_job(payload)
    return json.dumps(res_dict), status_code, {"Content-Type": "application/json"}
