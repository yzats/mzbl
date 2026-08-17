from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseTaskDispatcher(ABC):
    """Abstract base class for background task dispatchers."""

    @abstractmethod
    def dispatch_product_task(
        self,
        product_id: str,
        shop_domain: str,
        topic: str = "products/update",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Dispatch a background task to process a product.

        Args:
            product_id: Shopify product GID (e.g. 'gid://shopify/Product/12345').
            shop_domain: Shopify store domain.
            topic: Webhook event topic.
            metadata: Optional additional key-value metadata.

        Returns:
            str: Task or execution identifier.
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
    def is_duplicate(self, key: str, ttl_seconds: int = 300) -> bool:
        """Check if key has been seen within TTL window and mark it seen.

        Args:
            key: Webhook ID or unique payload identifier.
            ttl_seconds: Time-To-Live in seconds.

        Returns:
            bool: True if key was already seen, False if new.
        """
        pass
