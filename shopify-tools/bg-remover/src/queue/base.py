from abc import ABC, abstractmethod
from typing import Dict, Any, NamedTuple, Optional


class DispatchResult(NamedTuple):
    """Outcome of dispatch_product_task.

    outcome is one of: ``enqueued``, ``deduplicated``, ``simulated``.
    """

    task_id: str
    outcome: str


class BaseTaskDispatcher(ABC):
    """Abstract base class for background task dispatchers."""

    @abstractmethod
    def dispatch_product_task(
        self,
        product_id: str,
        shop_domain: str,
        topic: str = "products/update",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DispatchResult:
        """Dispatch a background task to process a product.

        Args:
            product_id: Shopify product GID (e.g. 'gid://shopify/Product/12345').
            shop_domain: Shopify store domain.
            topic: Webhook event topic.
            metadata: Optional additional key-value metadata.

        Returns:
            DispatchResult: Task id and outcome (enqueued / deduplicated / simulated).
        """
        pass


class BaseLockStore(ABC):
    """Abstract base class for distributed product locks."""

    @abstractmethod
    def acquire_lock(self, lock_key: str, ttl_seconds: int = 120) -> bool:
        """Attempt to acquire a lock for lock_key.

        Args:
            lock_key: Lock identifier (e.g. 'product:gid://shopify/Product/12345').
            ttl_seconds: Time-To-Live in seconds for the lock.

        Returns:
            bool: True if lock was successfully acquired, False if already locked.
        """
        pass

    @abstractmethod
    def release_lock(self, lock_key: str) -> None:
        """Release an acquired lock."""
        pass


class BaseDedupStore(ABC):
    """Abstract base class for webhook deduplication stores."""

    @abstractmethod
    def was_seen(self, key: str, ttl_seconds: int = 300) -> bool:
        """True if key is already recorded and unexpired. Does not record the key."""
        pass

    def remember(self, key: str, ttl_seconds: int = 300) -> None:
        """Record key as seen for ttl_seconds. No-op if key is empty."""
        pass

    def is_duplicate(self, key: str, ttl_seconds: int = 300) -> bool:
        """True if already seen; otherwise record the key and return False."""
        if self.was_seen(key, ttl_seconds=ttl_seconds):
            return True
        self.remember(key, ttl_seconds=ttl_seconds)
        return False
