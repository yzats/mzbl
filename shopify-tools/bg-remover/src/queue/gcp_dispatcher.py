import json
import logging
import hashlib
import time
from typing import Dict, Any, Optional

from .base import BaseTaskDispatcher, DispatchResult

logger = logging.getLogger(__name__)


def named_task_id(product_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Build a Cloud Tasks-safe name that coalesces one product *update*, not one product forever.

    Cloud Tasks keeps completed/deleted task names as tombstones for up to ~1 hour.
    A name of only ``task-product-{id}`` therefore blocks legitimate later edits.
    Including a hash of Shopify ``updated_at`` (else webhook id / 30s bucket) lets a
    new product revision enqueue immediately while still dropping in-flight duplicates
    of the same update.
    """
    metadata = metadata or {}
    raw_pid = product_id.split("/")[-1]
    clean_pid = "".join(ch for ch in raw_pid if ch.isalnum() or ch in "-_") or "unknown"
    pid_hash = hashlib.sha256(product_id.encode("utf-8")).hexdigest()[:12]
    event_token = str(metadata.get("updated_at") or metadata.get("webhook_id") or "")
    if not event_token:
        event_token = str(int(time.time() // 30))
    event_hash = hashlib.sha256(event_token.encode("utf-8")).hexdigest()[:12]
    return f"task-product-{clean_pid}-{pid_hash}-{event_hash}"


class GCPCloudTasksDispatcher(BaseTaskDispatcher):
    """Dispatcher for publishing tasks to GCP Cloud Tasks queue with Named Task deduplication."""

    def __init__(
        self,
        project_id: str,
        location: str,
        queue_name: str,
        worker_target_url: str,
        service_account_email: Optional[str] = None,
    ):
        """Initialize GCP Cloud Tasks dispatcher.

        Args:
            project_id: GCP Project ID.
            location: GCP region (e.g. 'us-central1').
            queue_name: Cloud Tasks queue name (e.g. 'bg-remover-queue').
            worker_target_url: HTTP POST target URL of the worker Cloud Function.
            service_account_email: Optional OIDC service account email for HTTP auth.
        """
        self.project_id = project_id
        self.location = location
        self.queue_name = queue_name
        self.worker_target_url = worker_target_url
        self.service_account_email = service_account_email

        # Lazy import google-cloud-tasks to allow running local mode without GCP SDKs
        try:
            from google.cloud import tasks_v2
            self.client = tasks_v2.CloudTasksClient()
            self.queue_path = self.client.queue_path(project_id, location, queue_name)
        except Exception:
            self.client = None
            self.queue_path = f"projects/{project_id}/locations/{location}/queues/{queue_name}"

    def dispatch_product_task(
        self,
        product_id: str,
        shop_domain: str,
        topic: str = "products/update",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DispatchResult:
        """Constructs and enqueues a Cloud Task with Named Task deduplication."""
        payload = {
            "product_id": product_id,
            "shop_domain": shop_domain,
            "topic": topic,
            "metadata": metadata or {},
        }

        # Coalesce duplicate deliveries of the same product update; do not tombstone the product for 1 hour.
        task_id = named_task_id(product_id, metadata)
        task_name = f"{self.queue_path}/tasks/{task_id}"

        if not self.client:
            msg = f"[TASK SIMULATED] Cloud Tasks client unavailable; not enqueued: {task_name}"
            print(msg, flush=True)
            logger.warning(msg)
            return DispatchResult(task_id=task_name, outcome="simulated")

        from google.cloud import tasks_v2

        payload_bytes = json.dumps(payload).encode("utf-8")

        task = {
            "name": task_name,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": self.worker_target_url,
                "headers": {"Content-Type": "application/json"},
                "body": payload_bytes,
            },
        }

        if self.service_account_email:
            task["http_request"]["oidc_token"] = {
                "service_account_email": self.service_account_email
            }

        try:
            response = self.client.create_task(request={"parent": self.queue_path, "task": task})
            msg = f"[TASK ENQUEUED] {response.name}"
            print(msg, flush=True)
            logger.info(msg)
            return DispatchResult(task_id=response.name, outcome="enqueued")
        except Exception as e:
            # GCP Cloud Tasks returns 409 Already Exists if the name is in-flight or tombstoned (~1h).
            if "ALREADY_EXISTS" in str(e) or "409" in str(e):
                updated_at = (metadata or {}).get("updated_at", "")
                msg = (
                    f"[TASK DEDUPED] Cloud Tasks name already exists or is tombstoned "
                    f"(same product updated_at={updated_at!r}): {task_name}"
                )
                print(msg, flush=True)
                logger.warning(msg)
                return DispatchResult(task_id=task_name, outcome="deduplicated")
            logger.error(f"Failed to enqueue GCP Cloud Task {task_name}: {e}")
            raise
