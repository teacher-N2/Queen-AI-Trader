from collections import defaultdict
from contextlib import contextmanager
from threading import RLock
from typing import Iterator


class KeyedLockManager:
    def __init__(self) -> None:
        self._manager_lock = RLock()
        self._locks: dict[str, RLock] = defaultdict(RLock)

    @contextmanager
    def lock(self, scope: str, key: str) -> Iterator[None]:
        lock_key = f"{scope}:{key}"
        with self._manager_lock:
            lock = self._locks[lock_key]
        with lock:
            yield


lock_manager = KeyedLockManager()
