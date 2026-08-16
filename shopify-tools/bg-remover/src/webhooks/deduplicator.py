import time
from typing import Set, Dict, Optional


class WebhookDeduplicator:
    """In-memory deduplicator for tracking recently processed webhook IDs and product IDs.
    
    Prevents duplicate processing caused by rapid webhook retransmissions or retries.
    In production GCP deployment, this can be backed by Cloud Firestore / Memorystore (Redis).
    """

    def __init__(self, ttl_seconds: int = 300):
        """Initialize deduplicator with a TTL (default 5 minutes / 300s)."""
        self.ttl_seconds = ttl_seconds
        self._seen_webhooks: Dict[str, float] = {}  # webhook_id -> timestamp
        self._active_products: Dict[str, float] = {}  # product_id -> timestamp

    def _cleanup_expired(self, now: float) -> None:
        """Purge records older than ttl_seconds."""
        expired_webhooks = [
            wid for wid, ts in self._seen_webhooks.items()
            if now - ts > self.ttl_seconds
        ]
        for wid in expired_webhooks:
            del self._seen_webhooks[wid]

        expired_products = [
            pid for pid, ts in self._active_products.items()
            if now - ts > self.ttl_seconds
        ]
        for pid in expired_products:
            del self._active_products[pid]

    def is_duplicate_webhook(self, webhook_id: str) -> bool:
        """Check if X-Shopify-Webhook-Id has already been seen within TTL window."""
        if not webhook_id:
            return False

        now = time.time()
        self._cleanup_expired(now)

        if webhook_id in self._seen_webhooks:
            return True

        self._seen_webhooks[webhook_id] = now
        return False

    def is_product_currently_processing(self, product_id: str) -> bool:
        """Check if product_id is currently being processed within TTL window."""
        if not product_id:
            return False

        now = time.time()
        self._cleanup_expired(now)

        return product_id in self._active_products

    def mark_product_processing(self, product_id: str) -> None:
        """Mark a product_id as currently being processed."""
        if product_id:
            self._active_products[product_id] = time.time()

    def mark_product_completed(self, product_id: str) -> None:
        """Remove product_id from active processing tracking upon completion."""
        if product_id in self._active_products:
            del self._active_products[product_id]
