"""Pause / resume the product Cloud Tasks queue (rembg circuit breaker)."""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

CIRCUIT_OPEN_LOG = "[CIRCUIT OPEN]"
CIRCUIT_STILL_OPEN_LOG = "[CIRCUIT STILL OPEN]"
CIRCUIT_CLOSED_LOG = "[CIRCUIT CLOSED]"


def _queue_client_and_path():
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    location = os.environ.get("GCP_REGION", "us-central1")
    queue_name = os.environ.get("QUEUE_NAME", "bg-remover-queue")
    if not project_id:
        return None, ""
    try:
        from google.cloud import tasks_v2
        client = tasks_v2.CloudTasksClient()
        queue_path = client.queue_path(project_id, location, queue_name)
        return client, queue_path
    except Exception as e:
        logger.warning("Cloud Tasks client unavailable for circuit control: %s", e)
        return None, ""


def pause_product_queue(reason: str) -> bool:
    """Pause bg-remover-queue. Returns True if the queue was newly paused (emit alert)."""
    client, queue_path = _queue_client_and_path()
    if not client:
        msg = f"{CIRCUIT_OPEN_LOG} (local/no client) rembg unavailable: {reason}"
        print(msg, flush=True)
        logger.error(msg)
        return True

    from google.cloud.tasks_v2 import Queue

    try:
        queue = client.get_queue(name=queue_path)
        if queue.state == Queue.State.PAUSED:
            msg = f"{CIRCUIT_STILL_OPEN_LOG} queue already paused: {reason}"
            print(msg, flush=True)
            logger.warning(msg)
            return False
        client.pause_queue(name=queue_path)
        msg = f"{CIRCUIT_OPEN_LOG} paused {queue_path}: {reason}"
        print(msg, flush=True)
        logger.error(msg)
        return True
    except Exception as e:
        msg = f"{CIRCUIT_OPEN_LOG} failed to pause queue {queue_path}: {e} reason={reason}"
        print(msg, flush=True)
        logger.error(msg)
        return False


def resume_product_queue() -> bool:
    """Resume bg-remover-queue. Returns True if the queue was resumed."""
    client, queue_path = _queue_client_and_path()
    if not client:
        msg = f"{CIRCUIT_CLOSED_LOG} (local/no client) rembg probe ok"
        print(msg, flush=True)
        logger.warning(msg)
        return True

    from google.cloud.tasks_v2 import Queue

    try:
        queue = client.get_queue(name=queue_path)
        if queue.state == Queue.State.RUNNING:
            logger.info("Queue already running: %s", queue_path)
            return False
        client.resume_queue(name=queue_path)
        msg = f"{CIRCUIT_CLOSED_LOG} resumed {queue_path}"
        print(msg, flush=True)
        logger.warning(msg)
        return True
    except Exception as e:
        logger.error("Failed to resume queue %s: %s", queue_path, e)
        return False


def is_product_queue_paused() -> Optional[bool]:
    """Return True if paused, False if running, None if unknown."""
    client, queue_path = _queue_client_and_path()
    if not client:
        return None
    from google.cloud.tasks_v2 import Queue

    try:
        queue = client.get_queue(name=queue_path)
        return queue.state == Queue.State.PAUSED
    except Exception as e:
        logger.warning("Could not read queue state: %s", e)
        return None
