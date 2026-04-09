import asyncio

import fakeredis
import pytest
from redis.exceptions import LockError

from app.core.locks import RedisLockRegistry


class TestRedisLockRegistry:
    """Tests that RedisLockRegistry correctly serialises concurrent operations."""

    @pytest.fixture
    def redis_client(self):
        return fakeredis.aioredis.FakeRedis()

    @pytest.fixture
    def registry(self, redis_client, monkeypatch):
        monkeypatch.setattr('app.core.redis.redis_client', redis_client)
        return RedisLockRegistry('test', lease_timeout=10)

    async def test_same_key_serialised(self, registry):
        """Two concurrent acquires on the same key run one at a time."""
        order = []

        async def work(label):
            async with registry.acquire(1):
                order.append(f'{label}_start')
                await asyncio.sleep(0.01)
                order.append(f'{label}_end')

        await asyncio.gather(work('a'), work('b'))
        assert order == ['a_start', 'a_end', 'b_start', 'b_end']

    async def test_different_keys_concurrent(self, registry):
        """Different keys run concurrently."""
        order = []

        async def work(key, label):
            async with registry.acquire(key):
                order.append(f'{label}_start')
                await asyncio.sleep(0.01)
                order.append(f'{label}_end')

        await asyncio.gather(work(1, 'a'), work(2, 'b'))
        assert order == ['a_start', 'b_start', 'a_end', 'b_end']

    async def test_lock_released_after_exception(self, registry):
        """Lock is released even when the body raises."""
        with pytest.raises(ValueError):
            async with registry.acquire(1):
                raise ValueError('boom')

        # Should be able to acquire again immediately
        async with registry.acquire(1):
            pass

    async def test_lock_released_after_cancellation(self, registry):
        """Lock is released when a holder is cancelled."""
        acquired = asyncio.Event()

        async def holder():
            async with registry.acquire(1):
                acquired.set()
                await asyncio.sleep(10)

        task = asyncio.create_task(holder())
        await acquired.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should be able to acquire again
        async with registry.acquire(1):
            pass

    async def test_lock_key_has_ttl(self, registry, redis_client):
        """The Redis key has a TTL so it auto-expires if the holder crashes."""
        async with registry.acquire(1):
            ttl = await redis_client.ttl('test:1')
            assert ttl > 0

    async def test_blocking_timeout_raises_lock_error(self, redis_client, monkeypatch):
        """A waiter gives up after blocking_timeout and raises LockError."""
        monkeypatch.setattr('app.core.redis.redis_client', redis_client)
        registry = RedisLockRegistry('test', lease_timeout=10, blocking_timeout=0.5)

        async with registry.acquire(1):
            with pytest.raises(LockError):
                async with registry.acquire(1):
                    pass
