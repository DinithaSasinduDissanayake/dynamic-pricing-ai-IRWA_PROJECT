from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Dict


class AsyncLockRegistry:
    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get_lock(self, key: str) -> asyncio.Lock:
        return self._locks[key]


class ThreadLockRegistry:
    def __init__(self):
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def get_lock(self, key: str) -> threading.Lock:
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]


_async_global: AsyncLockRegistry | None = None
_thread_global: ThreadLockRegistry | None = None


def get_async_lock_registry() -> AsyncLockRegistry:
    global _async_global
    if _async_global is None:
        _async_global = AsyncLockRegistry()
    return _async_global


def get_thread_lock_registry() -> ThreadLockRegistry:
    global _thread_global
    if _thread_global is None:
        _thread_global = ThreadLockRegistry()
    return _thread_global
