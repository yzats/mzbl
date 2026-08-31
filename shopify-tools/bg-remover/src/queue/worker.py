import json
from typing import Any, Tuple, Dict, Optional
import functions_framework
from flask import Request

import os

try:
    import config as _app_config
except ImportError:
    _app_config = None


def _setting(name: str, default: str = "") -> str:
    env_val = os.environ.get(name)
    if env_val is not None and str(env_val).strip() != "":
        return str(env_val).strip()
    if _app_config is not None:
        return str(getattr(_app_config, name, default) or default)
    return default


SHOPIFY_STORE_URL = _setting("SHOPIFY_STORE_URL")
SHOPIFY_ADMIN_API_ACCESS_TOKEN = _setting("SHOPIFY_ADMIN_API_ACCESS_TOKEN")
SHOPIFY_API_VERSION = _setting("SHOPIFY_API_VERSION", "2026-10")
REMBG_API_URL = _setting("REMBG_API_URL", "https://api.rembg.com/rmbg")
REMBG_API_KEY = _setting("REMBG_API_KEY")

from src.shopify import ShopifyGraphQLClient, ShopifyAPIError, RetryableShopifyError
from src.shopify.store_host import shopify_admin_host
from src.removers import (
    RembgHostedRemover,
    BackgroundRemoverError,
    RetryableBackgroundRemoverError,
    RembgUnavailableError,
)
from src.queue.custom_metrics import increment_images_processed
from src.queue.memory_stores import InMemoryLockStore
from src.queue.queue_control import pause_product_queue
from src.queue.base import product_lock_key
from src.queue.shop_registry import get_shop_store
from src.utils import applog

# Global Product Lock Store for Worker
lock_store = InMemoryLockStore()
_gcp_lock_store = None


def get_lock_store():
    """Return Firestore lock store in GCP, or the in-memory store locally."""
    global _gcp_lock_store
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    if not project_id:
        return lock_store
    if _gcp_lock_store is None:
        from src.queue.firestore_stores import GCPFirestoreLockStore
        _gcp_lock_store = GCPFirestoreLockStore(project_id=project_id)
    return _gcp_lock_store


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

    payload_shop = str(payload.get("shop_domain") or "")
    shop_url = shopify_admin_host(payload_shop)
    if not shop_url:
        applog.error("Shopify store host is missing or is not a *.myshopify.com Admin host.")
        return {"status": "error", "message": "Invalid Shopify store host"}, 400

    record = get_shop_store().get_shop(shop_url)
    token = ""
    if record:
        token = str(record.get("accessToken") or "").strip()
        if record.get("status") == "disconnected":
            token = ""
    if not token:
        configured_host = shopify_admin_host(SHOPIFY_STORE_URL)
        fallback_token = SHOPIFY_ADMIN_API_ACCESS_TOKEN
        if fallback_token and (not configured_host or configured_host == shop_url):
            token = fallback_token
            record = None
        else:
            applog.info(f"[200 SKIPPED] Shop not registered: {shop_url}")
            return {"status": "skipped", "reason": "Shop not registered"}, 200

    if record is not None and not record.get("autoEnabled", False):
        applog.info(f"[200 SKIPPED] autoEnabled is false for {shop_url}")
        return {"status": "skipped", "reason": "autoEnabled is false"}, 200

    images_scope = "all"
    bg_color = None
    if record is not None:
        images_scope = str(record.get("imagesScope") or "all")
        if record.get("fillMode") == "hex" and record.get("fillHex"):
            bg_color = str(record.get("fillHex"))

    shopify_client = ShopifyGraphQLClient(
        store_url=shop_url,
        access_token=token,
        api_version=SHOPIFY_API_VERSION,
    )
    remover = RembgHostedRemover(api_key=REMBG_API_KEY, api_url=REMBG_API_URL)

    active_lock_store = get_lock_store()
    lock_key = product_lock_key(shop_url, product_id)
    if not active_lock_store.acquire_lock(lock_key, ttl_seconds=120):
        applog.info(
            f"[200 SKIPPED] Product lock active for {shop_url} {product_id}. Skipping duplicate worker run."
        )
        return {"status": "skipped", "reason": "Product currently processing"}, 200

    try:
        unprocessed_images = shopify_client.get_unprocessed_images(
            product_id, images_scope=images_scope
        )

        if not unprocessed_images:
            applog.info(f"No unprocessed images for {product_id}")
            return {"status": "success", "processed_count": 0, "message": "No unprocessed images"}, 200

        applog.info(f"Processing {len(unprocessed_images)} image(s) on {product_id}")

        from process_product import process_product_batch

        processed_count = process_product_batch(
            shopify_client=shopify_client,
            remover=remover,
            product_id=product_id,
            unprocessed_images=unprocessed_images,
            bg_color=bg_color,
        )

        applog.info(f"Processed {processed_count} image(s) for {product_id}")
        increment_images_processed(processed_count)
        return {"status": "success", "processed_count": processed_count}, 200

    except (ShopifyAPIError, BackgroundRemoverError) as e:
        if isinstance(e, RembgUnavailableError):
            applog.warning(f"Rembg unavailable for {product_id}: {e}")
            pause_product_queue(str(e))
            return {"status": "error", "circuit": "open", "message": str(e)}, 503
        if isinstance(e, RetryableBackgroundRemoverError):
            applog.warning(f"Retryable rembg error for {product_id}: {e}")
            if e.pause_circuit:
                pause_product_queue(str(e))
                return {"status": "error", "circuit": "open", "message": str(e)}, 503
            return {"status": "error", "message": str(e)}, 503
        if isinstance(e, RetryableShopifyError):
            applog.warning(f"Retryable Shopify error for {product_id}: {e}")
            return {"status": "error", "message": str(e)}, 503
        applog.error(f"Non-retryable error for {product_id}: {e}")
        return {"status": "error", "message": str(e)}, 400

    finally:
        active_lock_store.release_lock(lock_key)


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
