import threading
from typing import Dict, Any, Optional, Callable

from src.utils import applog
from .base import BaseTaskDispatcher, BaseLockStore, DispatchResult
from .memory_stores import InMemoryLockStore


class LocalTaskDispatcher(BaseTaskDispatcher):
    """Local asynchronous task dispatcher using background threads for local development."""

    def __init__(
        self,
        worker_func: Callable[[Dict[str, Any]], None],
        lock_store: Optional[BaseLockStore] = None,
    ):
        """Initialize LocalTaskDispatcher with worker function and optional lock store.

        Args:
            worker_func: Function to call asynchronously when task is dispatched.
                         Signature: worker_func(payload_dict)
            lock_store: Lock store implementation (defaults to InMemoryLockStore).
        """
        self.worker_func = worker_func
        self.lock_store = lock_store or InMemoryLockStore()

    def dispatch_product_task(
        self,
        product_id: str,
        shop_domain: str,
        topic: str = "products/update",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DispatchResult:
        """Dispatches a product processing task in a background daemon thread."""
        payload = {
            "product_id": product_id,
            "shop_domain": shop_domain,
            "topic": topic,
            "metadata": metadata or {},
        }

        task_id = f"local-task-{product_id.split('/')[-1]}"

        def _runner():
            lock_key = f"lock:product:{product_id}"
            if not self.lock_store.acquire_lock(lock_key, ttl_seconds=120):
                applog.info(
                    f"[SKIPPED] Local worker product lock active for {product_id} task={task_id}"
                )
                return

            try:
                self.worker_func(payload)
            except Exception as e:
                applog.error(f"Error executing local task {task_id}: {e}")
            finally:
                self.lock_store.release_lock(lock_key)

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()

        return DispatchResult(task_id=task_id, outcome="enqueued")
