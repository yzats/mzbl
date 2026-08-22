import os
import json
from typing import Any, Tuple, Dict, Optional
import functions_framework
from flask import Request

from .hmac_verifier import verify_shopify_hmac
from src.queue.memory_stores import InMemoryDedupStore
from src.queue.local_dispatcher import LocalTaskDispatcher
from src.queue.worker import execute_background_removal_job
from src.utils import applog

# Global instances for local/default setup
deduplicator = InMemoryDedupStore()
dispatcher = LocalTaskDispatcher(worker_func=execute_background_removal_job)
_gcp_deduplicator = None
_gcp_dispatcher = None


def _gcp_project_id() -> str:
    return os.environ.get("GCP_PROJECT_ID", "")


def get_deduplicator():
    """Return Firestore dedup in GCP, or the in-memory store locally."""
    global _gcp_deduplicator
    project_id = _gcp_project_id()
    if not project_id:
        return deduplicator
    if _gcp_deduplicator is None:
        from src.queue.firestore_stores import GCPFirestoreDedupStore
        _gcp_deduplicator = GCPFirestoreDedupStore(project_id=project_id)
    return _gcp_deduplicator


def get_dispatcher():
    """Return Cloud Tasks dispatcher in GCP, or the local thread dispatcher."""
    global _gcp_dispatcher
    project_id = _gcp_project_id()
    if not project_id:
        return dispatcher
    if _gcp_dispatcher is None:
        from src.queue.gcp_dispatcher import GCPCloudTasksDispatcher
        _gcp_dispatcher = GCPCloudTasksDispatcher(
            project_id=project_id,
            location=os.environ.get("GCP_REGION", "us-central1"),
            queue_name=os.environ.get("QUEUE_NAME", "bg-remover-queue"),
            worker_target_url=os.environ.get("WORKER_TARGET_URL", ""),
            service_account_email=os.environ.get("FUNCTION_RUNTIME_SA", ""),
        )
    return _gcp_dispatcher


def get_webhook_secret() -> str:
    """Prefer Secret Manager / env vars (production), then local config.py."""
    env_secret = (
        os.environ.get("SHOPIFY_WEBHOOK_SECRET", "")
        or os.environ.get("SHOPIFY_CLIENT_SECRET", "")
    ).strip()
    if env_secret:
        return env_secret
    try:
        import config as shopify_tools_config
    except ImportError:
        return ""
    return (
        getattr(shopify_tools_config, "SHOPIFY_WEBHOOK_SECRET", "")
        or getattr(shopify_tools_config, "SHOPIFY_CLIENT_SECRET", "")
        or ""
    ).strip()


@functions_framework.http
def shopify_webhook_receiver(request: Request) -> Tuple[Any, int, Dict[str, str]]:
    """GCP Cloud Function (HTTP triggered) to receive Shopify Webhooks.

    Validates HMAC signature and extracts product details for background task queueing.

    Args:
        request: Flask request object from functions_framework.

    Returns:
        Tuple[str, int, Dict[str, str]]: Response tuple (body, status_code, headers).
    """
    if request.method != "POST":
        return json.dumps({"error": "Method not allowed"}), 405, {"Content-Type": "application/json"}

    # Retrieve Shopify HMAC & Webhook headers
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    topic_header = request.headers.get("X-Shopify-Topic", "")
    shop_header = request.headers.get("X-Shopify-Shop-Domain", "")

    client_secret = get_webhook_secret()
    body_bytes = request.get_data()

    if not verify_shopify_hmac(body_bytes, hmac_header, client_secret):
        applog.warning(f"[401 UNAUTHORIZED] HMAC failed shop={shop_header} webhook_id={webhook_id}")
        return json.dumps({"error": "Unauthorized: Invalid HMAC signature"}), 401, {"Content-Type": "application/json"}

    dedup = get_deduplicator()
    if webhook_id and dedup.was_seen(webhook_id, ttl_seconds=300):
        applog.info(f"[200 SKIPPED] Duplicate Webhook ID detected: {webhook_id}")
        return json.dumps({"status": "ignored", "reason": "Duplicate webhook ID", "webhook_id": webhook_id}), 200, {"Content-Type": "application/json"}
    if webhook_id:
        dedup.remember(webhook_id, ttl_seconds=300)

    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception as e:
        applog.error(f"[400 BAD REQUEST] Invalid JSON: {e}")
        return json.dumps({"error": "Bad request: Invalid JSON payload"}), 400, {"Content-Type": "application/json"}

    product_id = payload.get("id")
    if not product_id:
        applog.info("[200 IGNORED] No product ID in payload")
        return json.dumps({"status": "ignored", "reason": "No product ID in payload"}), 200, {"Content-Type": "application/json"}

    # Format GraphQL product ID if numeric
    if isinstance(product_id, int) or str(product_id).isdigit():
        gql_product_id = f"gid://shopify/Product/{product_id}"
    else:
        gql_product_id = str(product_id)

    # Dispatch background worker task asynchronously
    dispatch = get_dispatcher().dispatch_product_task(
        product_id=gql_product_id,
        shop_domain=shop_header,
        topic=topic_header,
        metadata={
            "updated_at": payload.get("updated_at") or "",
            "webhook_id": webhook_id,
        },
    )

    if dispatch.outcome == "deduplicated":
        applog.info(
            f"[200 DEDUPED] Named Cloud Task already exists for this updated_at "
            f"(product={gql_product_id} updated_at={payload.get('updated_at')!r} task={dispatch.task_id})"
        )
        return json.dumps({
            "status": "deduplicated",
            "reason": "Cloud Tasks named task already exists or is tombstoned for this updated_at",
            "task_id": dispatch.task_id,
            "product_id": gql_product_id,
            "updated_at": payload.get("updated_at") or "",
            "topic": topic_header,
            "shop": shop_header,
        }), 200, {"Content-Type": "application/json"}

    applog.info(
        f"[200 SUCCESS] {topic_header} shop={shop_header} product={gql_product_id} "
        f"task={dispatch.task_id} outcome={dispatch.outcome}"
    )

    return json.dumps({
        "status": "success",
        "task_id": dispatch.task_id,
        "outcome": dispatch.outcome,
        "product_id": gql_product_id,
        "topic": topic_header,
        "shop": shop_header
    }), 200, {"Content-Type": "application/json"}
