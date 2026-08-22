import hashlib
from typing import Optional, Any
from src.utils import applog
from .base import BaseLockStore, BaseDedupStore


def firestore_document_id(key: str) -> str:
    """Return a Firestore-safe document ID.

    Firestore treats ``/`` as a path separator, so GraphQL GIDs like
    ``gid://shopify/Product/123`` cannot be used as document names.
    SHA-256 hex is stable, unique, and always a valid ID. The original
    key is stored in document fields (``lock_key`` / ``key``).
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class GCPFirestoreLockStore(BaseLockStore):
    """GCP Cloud Firestore implementation of Product Processing Lock."""

    def __init__(self, collection_name: str = "product_locks", project_id: Optional[str] = None):
        self.collection_name = collection_name
        self.project_id = project_id

        try:
            from google.cloud import firestore
            self.db = firestore.Client(project=project_id)
        except Exception as e:
            self.db = None
            applog.warning(f"FirestoreLockStore client unavailable ({e}); operating in mock mode.")

    def acquire_lock(self, lock_key: str, ttl_seconds: int = 120) -> bool:
        if not self.db:
            return True

        import time
        doc_ref = self.db.collection(self.collection_name).document(firestore_document_id(lock_key))
        now = time.time()

        try:
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict() or {}
                expires_at = data.get("expires_at", 0)
                if now < expires_at:
                    return False  # Lock is active

            # Lock is absent or expired, acquire
            doc_ref.set({
                "lock_key": lock_key,
                "created_at": now,
                "expires_at": now + ttl_seconds,
            })
            return True
        except Exception as e:
            applog.warning(f"Firestore acquire_lock error for {lock_key}: {e}")
            return True  # Fail open to allow worker execution if Firestore has transient issues

    def release_lock(self, lock_key: str) -> None:
        if not self.db:
            return

        try:
            self.db.collection(self.collection_name).document(firestore_document_id(lock_key)).delete()
        except Exception as e:
            applog.warning(f"Firestore release_lock error for {lock_key}: {e}")


class GCPFirestoreDedupStore(BaseDedupStore):
    """GCP Cloud Firestore implementation of Webhook Deduplication Store."""

    def __init__(self, collection_name: str = "webhook_dedup", project_id: Optional[str] = None):
        self.collection_name = collection_name
        self.project_id = project_id

        try:
            from google.cloud import firestore
            self.db = firestore.Client(project=project_id)
        except Exception as e:
            self.db = None
            applog.warning(f"FirestoreDedupStore client unavailable ({e}); operating in mock mode.")

    def was_seen(self, key: str, ttl_seconds: int = 300) -> bool:
        if not key or not self.db:
            return False
        import time
        try:
            doc = self.db.collection(self.collection_name).document(firestore_document_id(key)).get()
            if not doc.exists:
                return False
            data = doc.to_dict() or {}
            return time.time() < data.get("expires_at", 0)
        except Exception as e:
            applog.warning(f"Firestore was_seen error for {key}: {e}")
            return False

    def remember(self, key: str, ttl_seconds: int = 300) -> None:
        if not key or not self.db:
            return
        import time
        now = time.time()
        try:
            self.db.collection(self.collection_name).document(firestore_document_id(key)).set({
                "key": key,
                "created_at": now,
                "expires_at": now + ttl_seconds,
            })
        except Exception as e:
            applog.warning(f"Firestore remember error for {key}: {e}")
