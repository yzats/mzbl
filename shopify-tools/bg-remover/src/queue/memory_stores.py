import time
from typing import Dict
from .base import BaseLockStore, BaseDedupStore


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

    def is_duplicate(self, key: str, ttl_seconds: int = 300) -> bool:
        if not key:
            return False

        now = time.time()
        if key in self._items:
            if now <= self._items[key]:
                return True
            else:
                del self._items[key]

        self._items[key] = now + ttl_seconds
        return False
