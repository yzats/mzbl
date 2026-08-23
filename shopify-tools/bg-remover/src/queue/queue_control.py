"""Pause / resume the product Cloud Tasks queue (rembg circuit breaker)."""

import os
import time
from typing import Any, Dict, Optional

from src.queue.custom_metrics import write_circuit_open_gauge
from src.utils import applog

CIRCUIT_OPEN_LOG = "[CIRCUIT OPEN]"
CIRCUIT_STILL_OPEN_LOG = "[CIRCUIT STILL OPEN]"
CIRCUIT_CLOSED_LOG = "[CIRCUIT CLOSED]"
CIRCUIT_COLLECTION = "circuit_state"
CIRCUIT_DOC = "rembg"
# Consecutive canary failures: 5m, 15m, 30m, then 60m cap.
CANARY_HOLD_SECONDS = (5 * 60, 15 * 60, 30 * 60, 60 * 60)

_local_circuit_state: Dict[str, Any] = {"fail_count": 0, "next_canary_at": 0.0}


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


def _circuit_doc():
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    if not project_id:
        return None
    try:
        from google.cloud import firestore
        return firestore.Client(project=project_id).collection(CIRCUIT_COLLECTION).document(
            CIRCUIT_DOC
        )
    except Exception as e:
        applog.warning(f"Firestore circuit_state unavailable: {e}")
        return None


def _read_circuit_state() -> Dict[str, Any]:
    ref = _circuit_doc()
    if not ref:
        return dict(_local_circuit_state)
    try:
        snap = ref.get()
        if not snap.exists:
            return {"fail_count": 0, "next_canary_at": 0.0}
        data = snap.to_dict() or {}
        return {
            "fail_count": int(data.get("fail_count") or 0),
            "next_canary_at": float(data.get("next_canary_at") or 0),
        }
    except Exception as e:
        applog.warning(f"Failed to read circuit_state: {e}")
        return {"fail_count": 0, "next_canary_at": 0.0}


def _write_circuit_state(fail_count: int, next_canary_at: float) -> None:
    global _local_circuit_state
    _local_circuit_state = {"fail_count": fail_count, "next_canary_at": next_canary_at}
    ref = _circuit_doc()
    if not ref:
        return
    try:
        ref.set({
            "fail_count": fail_count,
            "next_canary_at": next_canary_at,
            "updated_at": time.time(),
        })
    except Exception as e:
        applog.warning(f"Failed to write circuit_state: {e}")


def canary_hold_seconds(fail_count: int) -> int:
    if fail_count <= 0:
        return CANARY_HOLD_SECONDS[0]
    idx = min(fail_count - 1, len(CANARY_HOLD_SECONDS) - 1)
    return CANARY_HOLD_SECONDS[idx]


def canary_is_due() -> bool:
    """True if a paused-queue /rmbg canary may run. Missing/error → True (fail-open)."""
    return time.time() >= float(_read_circuit_state().get("next_canary_at") or 0)


def record_canary_failure() -> int:
    """Increment fail_count and set next_canary_at. Returns hold seconds."""
    state = _read_circuit_state()
    fail_count = int(state.get("fail_count") or 0) + 1
    hold = canary_hold_seconds(fail_count)
    _write_circuit_state(fail_count, time.time() + hold)
    return hold


def reset_canary_backoff() -> None:
    _write_circuit_state(0, 0.0)


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
