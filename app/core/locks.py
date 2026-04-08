from contextlib import asynccontextmanager


class RedisLockRegistry:
    """
    Distributed per-ID lock via Redis. Works across multiple worker processes.
    Each ID gets its own Redis lock key so concurrent operations on different IDs
    run in parallel while operations on the same ID are serialised.
    """

    def __init__(self, prefix: str, timeout: float = 30):
        self._prefix = prefix
        self._timeout = timeout

    @asynccontextmanager
    async def acquire(self, key: int):
        """Acquire a distributed lock for the given key, yielding while held.

        The lock is released when the async block exits.
        Because `.lock()` returns a context manager where the ``__aexit__``
        calls ``release()``, which deletes the Redis key .

        As a safety net for hard crashes e.g. worker killed, the Redis
        key is created with a TTL. Hence if ``release()`` never runs,
        the key auto-expires and the lock becomes available again.
        """
        # Lazy import: redis_client is created at module level in redis.py, but tests
        # replace it with FakeRedis via monkeypatch. A top-level import here would
        # capture the original client before the patch is applied.
        from app.core.redis import redis_client

        async with redis_client.lock(
            f'{self._prefix}:{key}',
            timeout=self._timeout,
            sleep=0.2,
        ):
            yield
