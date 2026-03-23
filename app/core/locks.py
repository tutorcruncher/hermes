import asyncio


class _RefCountedLock:
    """
    Lock wrapper to track how many coroutines are waiting on or holding the lock.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._count = 0

    async def __aenter__(self):
        """
        async enter called when entering the `async with` block
        """
        self._count += 1
        try:
            await self._lock.acquire()
        except BaseException:
            self._count -= 1
            raise
        return self

    async def __aexit__(self, *exc):
        """
        called on exiting the async block
        """
        self._lock.release()
        self._count -= 1

    @property
    def in_use(self):
        return self._count > 0


class LockRegistry:
    """
    Per ID lock for a safe cleanup. Each ID gets its own lock so concurrent operations on different IDs
    run in parallel while the operations on the same ID are serialised.
    """

    def __init__(self):
        self._locks: dict[int, _RefCountedLock] = {}

    def get(self, key: int) -> _RefCountedLock:
        if key not in self._locks:
            self._locks[key] = _RefCountedLock()
        return self._locks[key]

    def release(self, key: int) -> None:
        lock = self._locks.get(key)
        if lock and not lock.in_use:
            self._locks.pop(key, None)
