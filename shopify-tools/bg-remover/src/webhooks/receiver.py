import sys
import json
import logging
from typing import Any, Tuple, Dict, Optional
import functions_framework
from flask import Request

from .hmac_verifier import verify_shopify_hmac
from src.queue.memory_stores import InMemoryDedupStore
from src.queue.local_dispatcher import LocalTaskDispatcher
from src.queue.worker import execute_background_removal_job

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Global instances for local/default setup
deduplicator = InMemoryDedupStore()
dispatcher = LocalTaskDispatcher(worker_func=execute_background_removal_job)


def get_webhook_secret() -> str:
    """Retrieve Shopify webhook secret key from config module or environment variable."""
    try:
        import config
        return getattr(config, "SHOPIFY_WEBHOOK_SECRET", "") or getattr(config, "SHOPIFY_CLIENT_SECRET", "")
    except ImportError:
        import os
        return os.environ.get("SHOPIFY_WEBHOOK_SECRET", "") or os.environ.get("SHOPIFY_CLIENT_SECRET", "")


@functions_framework.http
def shopify_webhook_receiver(request: Request) -> Tuple[Any, int, Dict[str, str]]:
    """GCP Cloud Function (HTTP triggered) to receive Shopify Webhooks.

    Validates HMAC signature and extracts product details for background task queueing.

    Args:
        request: Flask request object from functions_framework.

    Returns:
        Tuple[str, int, Dict[str, str]]: Response tuple (body, status_code, headers).
    """
    print(f"\n[WEBHOOK RECEIVED] Method: {request.method}", flush=True)

    if request.method != "POST":
        return json.dumps({"error": "Method not allowed"}), 405, {"Content-Type": "application/json"}

    # Retrieve Shopify HMAC & Webhook headers
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    topic_header = request.headers.get("X-Shopify-Topic", "")
    shop_header = request.headers.get("X-Shopify-Shop-Domain", "")

    client_secret = get_webhook_secret()
    body_bytes = request.get_data()

    print(f"  Webhook ID: {webhook_id} | Topic: {topic_header} | Shop: {shop_header}", flush=True)

    # Check for duplicate Webhook ID
    if webhook_id and deduplicator.is_duplicate(webhook_id, ttl_seconds=300):
        print(f"  [200 SKIPPED] Duplicate Webhook ID detected: {webhook_id}", flush=True)
        return json.dumps({"status": "ignored", "reason": "Duplicate webhook ID"}), 200, {"Content-Type": "application/json"}

    print(f"  HMAC Header: {hmac_header[:10]}... | Secret configured: {'Yes' if client_secret else 'No'}", flush=True)

    if not verify_shopify_hmac(body_bytes, hmac_header, client_secret):
        print(f"  [401 UNAUTHORIZED] HMAC signature verification failed!", flush=True)
        logger.warning(f"Invalid HMAC signature for webhook from {shop_header}")
        return json.dumps({"error": "Unauthorized: Invalid HMAC signature"}), 401, {"Content-Type": "application/json"}

    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception as e:
        print(f"  [400 BAD REQUEST] Failed to parse JSON: {e}", flush=True)
        logger.error(f"Failed to parse webhook JSON payload: {e}")
        return json.dumps({"error": "Bad request: Invalid JSON payload"}), 400, {"Content-Type": "application/json"}

    product_id = payload.get("id")
    if not product_id:
        print(f"  [200 IGNORED] No product ID in payload", flush=True)
        return json.dumps({"status": "ignored", "reason": "No product ID in payload"}), 200, {"Content-Type": "application/json"}

    # Format GraphQL product ID if numeric
    if isinstance(product_id, int) or str(product_id).isdigit():
        gql_product_id = f"gid://shopify/Product/{product_id}"
    else:
        gql_product_id = str(product_id)

    # Dispatch background worker task asynchronously
    task_id = dispatcher.dispatch_product_task(
        product_id=gql_product_id,
        shop_domain=shop_header,
        topic=topic_header,
    )

    print(f"  [200 SUCCESS] Dispatched task {task_id} for Product ID: {gql_product_id}", flush=True)
    logger.info(f"Received valid webhook for shop '{shop_header}', topic '{topic_header}', product ID '{gql_product_id}', task '{task_id}'")

    return json.dumps({
        "status": "success",
        "task_id": task_id,
        "product_id": gql_product_id,
        "topic": topic_header,
        "shop": shop_header
    }), 200, {"Content-Type": "application/json"}
