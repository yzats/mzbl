"""Pause / resume the product Cloud Tasks queue (rembg circuit breaker)."""

import os
from typing import Optional

from src.queue.custom_metrics import write_circuit_open_gauge
from src.utils import applog

CIRCUIT_OPEN_LOG = "[CIRCUIT OPEN]"
CIRCUIT_STILL_OPEN_LOG = "[CIRCUIT STILL OPEN]"
CIRCUIT_CLOSED_LOG = "[CIRCUIT CLOSED]"


def emit_circuit_log(msg: str) -> None:
    """One structured line. OPEN/STILL OPEN are WARNING; CLOSED is INFO."""
    if msg.startswith(CIRCUIT_CLOSED_LOG):
        applog.info(msg)
    else:
        applog.warning(msg)


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
        applog.warning(f"Cloud Tasks client unavailable for circuit control: {e}")
        return None, ""


def pause_product_queue(reason: str) -> bool:
    """Pause bg-remover-queue. Returns True if the queue was newly paused (emit alert)."""
    client, queue_path = _queue_client_and_path()
    if not client:
        emit_circuit_log(f"{CIRCUIT_OPEN_LOG} (local/no client) rembg unavailable: {reason}")
        write_circuit_open_gauge(True)
        return True

    from google.cloud.tasks_v2 import Queue

    try:
        queue = client.get_queue(name=queue_path)
        if queue.state == Queue.State.PAUSED:
            emit_circuit_log(f"{CIRCUIT_STILL_OPEN_LOG} queue already paused: {reason}")
            write_circuit_open_gauge(True)
            return False
        client.pause_queue(name=queue_path)
        emit_circuit_log(f"{CIRCUIT_OPEN_LOG} paused {queue_path}: {reason}")
        write_circuit_open_gauge(True)
        return True
    except Exception as e:
        emit_circuit_log(f"{CIRCUIT_OPEN_LOG} failed to pause queue {queue_path}: {e} reason={reason}")
        write_circuit_open_gauge(True)
        return False


def resume_product_queue() -> bool:
    """Resume bg-remover-queue. Returns True if the queue was resumed."""
    client, queue_path = _queue_client_and_path()
    if not client:
        emit_circuit_log(f"{CIRCUIT_CLOSED_LOG} (local/no client) rembg probe ok")
        write_circuit_open_gauge(False)
        return True

    from google.cloud.tasks_v2 import Queue

    try:
        queue = client.get_queue(name=queue_path)
        if queue.state == Queue.State.RUNNING:
            applog.info(f"Queue already running: {queue_path}")
            write_circuit_open_gauge(False)
            return False
        client.resume_queue(name=queue_path)
        emit_circuit_log(f"{CIRCUIT_CLOSED_LOG} resumed {queue_path}")
        write_circuit_open_gauge(False)
        return True
    except Exception as e:
        applog.error(f"Failed to resume queue {queue_path}: {e}")
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
        applog.warning(f"Could not read queue state: {e}")
        return None
