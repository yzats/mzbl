import json
import logging
import hashlib
from typing import Dict, Any, Optional

from .base import BaseTaskDispatcher

logger = logging.getLogger(__name__)


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
    ) -> str:
        """Constructs and enqueues a Cloud Task with Named Task deduplication."""
        payload = {
            "product_id": product_id,
            "shop_domain": shop_domain,
            "topic": topic,
            "metadata": metadata or {},
        }

        # Deterministic Task Name derived from product ID hash to prevent duplicate enqueued tasks
        clean_pid = product_id.split("/")[-1]
        pid_hash = hashlib.sha256(product_id.encode("utf-8")).hexdigest()[:12]
        task_id = f"task-product-{clean_pid}-{pid_hash}"
        task_name = f"{self.queue_path}/tasks/{task_id}"

        if not self.client:
            logger.warning(f"google-cloud-tasks library not installed. Simulated dispatch of task: {task_name}")
            return task_name

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
            logger.info(f"Successfully enqueued GCP Cloud Task: {response.name}")
            return response.name
        except Exception as e:
            # GCP Cloud Tasks returns 409 Already Exists (ALREADY_EXISTS) if a task with task_name exists
            if "ALREADY_EXISTS" in str(e) or "409" in str(e):
                logger.info(f"GCP Cloud Task already exists in queue (deduplicated): {task_name}")
                return task_name
            logger.error(f"Failed to enqueue GCP Cloud Task {task_name}: {e}")
            raise
