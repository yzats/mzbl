import hashlib
import logging
from typing import Optional, Any
from .base import BaseLockStore, BaseDedupStore

logger = logging.getLogger(__name__)


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
            logger.warning("FirestoreLockStore client unavailable (%s); operating in mock mode.", e)

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
            logger.error(f"Firestore acquire_lock error for {lock_key}: {e}")
            return True  # Fail open to allow worker execution if Firestore has transient issues

    def release_lock(self, lock_key: str) -> None:
        if not self.db:
            return

        try:
            self.db.collection(self.collection_name).document(firestore_document_id(lock_key)).delete()
        except Exception as e:
            logger.error(f"Firestore release_lock error for {lock_key}: {e}")


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
            logger.warning("FirestoreDedupStore client unavailable (%s); operating in mock mode.", e)

    def is_duplicate(self, key: str, ttl_seconds: int = 300) -> bool:
        if not key or not self.db:
            return False

        import time
        doc_ref = self.db.collection(self.collection_name).document(firestore_document_id(key))
        now = time.time()

        try:
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict() or {}
                expires_at = data.get("expires_at", 0)
                if now < expires_at:
                    return True  # Duplicate event

            # Mark key seen with TTL
            doc_ref.set({
                "key": key,
                "created_at": now,
                "expires_at": now + ttl_seconds,
            })
            return False
        except Exception as e:
            logger.error(f"Firestore is_duplicate error for {key}: {e}")
            return False
