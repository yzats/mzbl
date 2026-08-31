import time
from typing import Dict, Any, Optional
from .base import BaseLockStore, BaseDedupStore, BaseShopStore


class InMemoryLockStore(BaseLockStore):
    """In-memory implementation of product lock store for local testing."""

    def __init__(self):
        self._locks: Dict[str, float] = {}  # lock_key -> expire_timestamp

    def acquire_lock(self, lock_key: str, ttl_seconds: int = 120) -> bool:
        now = time.time()
        # Clean expired
        if lock_key in self._locks and now > self._locks[lock_key]:
            del self._locks[lock_key]

        if lock_key in self._locks:
            return False  # Currently locked

        self._locks[lock_key] = now + ttl_seconds
        return True

    def release_lock(self, lock_key: str) -> None:
        if lock_key in self._locks:
            del self._locks[lock_key]


class InMemoryDedupStore(BaseDedupStore):
    """In-memory implementation of webhook deduplication store for local testing."""

    def __init__(self):
        self._items: Dict[str, float] = {}  # key -> expire_timestamp

    def was_seen(self, key: str, ttl_seconds: int = 300) -> bool:
        if not key:
            return False
        now = time.time()
        if key in self._items:
            if now <= self._items[key]:
                return True
            del self._items[key]
        return False

    def remember(self, key: str, ttl_seconds: int = 300) -> None:
        if not key:
            return
        self._items[key] = time.time() + ttl_seconds


class InMemoryShopStore(BaseShopStore):
    """In-memory shop registry for local tests and functions-framework."""

    def __init__(self):
        self._shops: Dict[str, Dict[str, Any]] = {}

    def get_shop(self, shop: str) -> Optional[Dict[str, Any]]:
        key = (shop or "").strip().lower()
        if not key:
            return None
        record = self._shops.get(key)
        return dict(record) if record else None

    def upsert_shop(self, shop: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        key = (shop or "").strip().lower()
        current = self._shops.get(key, {"shop": key})
        merged = {**current, **fields, "shop": key, "updatedAt": time.time()}
        self._shops[key] = merged
        return dict(merged)

    def delete_shop(self, shop: str) -> None:
        key = (shop or "").strip().lower()
        self._shops.pop(key, None)
