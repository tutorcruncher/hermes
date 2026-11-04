import asyncio
import logging
from contextlib import asynccontextmanager

from redis.asyncio.lock import Lock
from redis.exceptions import LockError, LockNotOwnedError

logger = logging.getLogger('hermes.locks')


class RedisLockRegistry:
    """
    Distributed per-ID lock via Redis. Works across multiple worker processes.
    Each ID gets its own Redis lock key so concurrent operations on different IDs
    run in parallel while operations on the same ID are serialised.

    lease_timeout is the TTL (seconds) of the Redis key. While the lock is held the lease is
    renewed every quarter of a lease, so it only expires under a live holder if three renewals
    in a row fail. It bounds how long the lock outlives a holder that crashed.
    blocking_timeout is the time (seconds) to wait for a lock to become available.
    None waits until the lock is released.
    max_hold_seconds stops renewing after that long, so a stuck holder loses the lock
    within one more lease. None renews for as long as the lock is held.
    """

    def __init__(
        self,
        prefix: str,
        lease_timeout_seconds: float,
        blocking_timeout_seconds: float | None = None,
        max_hold_seconds: float | None = None,
    ):
        self._prefix = prefix
        self._lease_timeout = lease_timeout_seconds
        self._blocking_timeout = blocking_timeout_seconds
        self._max_hold = max_hold_seconds

    @asynccontextmanager
    async def acquire(self, key: int):
        """Acquire a distributed lock for the given key, yielding while held.

        A background task renews the lease while the block runs. When the block exits
        the renewal stops and ``release()`` deletes the Redis key.

        As a safety net for hard crashes e.g. worker killed, the Redis key is created
        with a TTL. The renewal dies with the worker, so the key auto-expires and the
        lock becomes available again.

        If the lock was lost while held (key expired or taken by another owner), the
        release logs an error instead of raising, as the block has already run.
        """
        # Lazy import: redis_client is created at module level in redis.py, but tests
        # replace it with FakeRedis via monkeypatch. A top-level import here would
        # capture the original client before the patch is applied.
        from app.core.redis import redis_client

        name = f'{self._prefix}:{key}'
        lock = redis_client.lock(
            name,
            timeout=self._lease_timeout,
            sleep=0.2,  # redis locks use a polling mechanism, polling every 200ms
            blocking_timeout=self._blocking_timeout,
        )
        if not await lock.acquire():
            raise LockError(f'Unable to acquire lock {name} within the time specified')

        renewer = asyncio.create_task(self._renew(lock, name))
        try:
            yield
        finally:
            renewer.cancel()
            try:
                # wait() doesn't raise the renewer's CancelledError, so a cancelled holder still raises its own
                await asyncio.wait([renewer])
            finally:
                # Nested so that a second cancel landing on the wait above can't skip the release
                try:
                    await lock.release()
                except LockNotOwnedError:
                    logger.error(f'Lock {name} was lost before it was released', exc_info=True)

    async def _renew(self, lock: Lock, name: str):
        """Reset the lock's TTL to the full lease every quarter of a lease until cancelled.

        Renewals run on a fixed schedule and each call gets at most half an interval, so a failed
        or hung call never delays the next one, leaving two retries before the key expires.
        Stops once the lock is no longer owned, or after max_hold_seconds.
        """
        interval = self._lease_timeout / 4
        loop = asyncio.get_running_loop()
        started = next_renewal = loop.time()
        while True:
            next_renewal += interval
            await asyncio.sleep(max(0, next_renewal - loop.time()))
            if self._max_hold is not None and loop.time() - started > self._max_hold:
                logger.error(f'Lock {name} held for over {self._max_hold}s, no longer renewing it')
                return
            try:
                # redis_client has no socket timeout, so a hung call would otherwise stop renewal for good
                async with asyncio.timeout(interval / 2):
                    await lock.reacquire()
            except LockNotOwnedError:
                logger.warning(f'Lock {name} is no longer owned, stopping renewal')
                return
            except TimeoutError:
                logger.warning(f'Renewing lock {name} timed out after {interval / 2}s')
            except Exception as e:
                logger.warning(f'Failed to renew lock {name}: {e}', exc_info=True)
