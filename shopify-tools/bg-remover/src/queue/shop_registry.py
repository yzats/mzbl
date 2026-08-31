"""Shared shop registry (in-memory locally, Firestore in GCP)."""

import os

from src.queue.memory_stores import InMemoryShopStore

_memory_store = InMemoryShopStore()
_gcp_store = None


def get_shop_store():
    """Return Firestore shop store in GCP, or the in-memory store locally."""
    global _gcp_store
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    if not project_id:
        return _memory_store
    if _gcp_store is None:
        from src.queue.firestore_stores import GCPFirestoreShopStore
        _gcp_store = GCPFirestoreShopStore(project_id=project_id)
    return _gcp_store
