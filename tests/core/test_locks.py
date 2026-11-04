import asyncio
import logging
from unittest.mock import patch

import fakeredis
import pytest
from redis.asyncio.lock import Lock
from redis.exceptions import ConnectionError as RedisConnectionError, LockError

from app.core.locks import RedisLockRegistry

_real_reacquire = Lock.reacquire


def _lock_logs(caplog):
    return [(r.levelname, r.getMessage()) for r in caplog.records if r.name == 'hermes.locks']


def _other_tasks():
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}


class TestRedisLockRegistry:
    """Tests that RedisLockRegistry correctly serialises concurrent operations."""

    @pytest.fixture
    def redis_client(self):
        return fakeredis.aioredis.FakeRedis()

    @pytest.fixture
    def registry(self, redis_client, monkeypatch):
        monkeypatch.setattr('app.core.redis.redis_client', redis_client)
        return RedisLockRegistry('test', lease_timeout_seconds=10)

    @pytest.fixture
    def short_lease_registry(self, redis_client, monkeypatch):
        monkeypatch.setattr('app.core.redis.redis_client', redis_client)
        return RedisLockRegistry('test', lease_timeout_seconds=0.8)

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
        registry = RedisLockRegistry('test', lease_timeout_seconds=10, blocking_timeout_seconds=0.5)

        async with registry.acquire(1):
            with pytest.raises(LockError):
                async with registry.acquire(1):
                    pass

    async def test_lease_renewed_while_held(self, short_lease_registry, redis_client, caplog):
        """A lock held for longer than its lease keeps its key and releases cleanly."""
        caplog.set_level(logging.WARNING, logger='hermes.locks')

        async with short_lease_registry.acquire(1):
            await asyncio.sleep(1.5)
            assert await redis_client.get('test:1') is not None

        assert await redis_client.get('test:1') is None
        assert _lock_logs(caplog) == []
        assert _other_tasks() == set()

    async def test_waiter_waits_past_lease(self, short_lease_registry):
        """A waiter with no blocking timeout waits for a holder that outlives the lease."""
        order = []
        acquired = asyncio.Event()

        async def holder():
            async with short_lease_registry.acquire(1):
                acquired.set()
                order.append('a_start')
                await asyncio.sleep(1.5)
                order.append('a_end')

        async def waiter():
            await acquired.wait()
            async with short_lease_registry.acquire(1):
                order.append('b_start')
                order.append('b_end')

        await asyncio.gather(holder(), waiter())
        assert order == ['a_start', 'a_end', 'b_start', 'b_end']

    async def test_lock_taken_by_other_owner_logged_not_raised(self, short_lease_registry, redis_client, caplog):
        """A lock lost to another owner is logged on renewal and release, and the other owner's key is untouched."""
        caplog.set_level(logging.WARNING, logger='hermes.locks')

        async with short_lease_registry.acquire(1):
            await redis_client.set('test:1', 'other')
            await asyncio.sleep(0.5)

        assert await redis_client.get('test:1') == b'other'
        assert _lock_logs(caplog) == [
            ('WARNING', 'Lock test:1 is no longer owned, stopping renewal'),
            ('ERROR', 'Lock test:1 was lost before it was released'),
        ]
        assert _other_tasks() == set()

    @patch.object(Lock, 'reacquire', autospec=True)
    async def test_renewal_error_logged_and_retried(self, mock_reacquire, short_lease_registry, redis_client, caplog):
        """Two failed renewals in a row are logged and retried before the lease runs out, so the lock is kept."""
        caplog.set_level(logging.WARNING, logger='hermes.locks')

        def reacquire(lock):
            if mock_reacquire.call_count <= 2:
                raise RedisConnectionError('Connection reset by peer')
            return _real_reacquire(lock)

        mock_reacquire.side_effect = reacquire

        async with short_lease_registry.acquire(1):
            await asyncio.sleep(1.5)
            assert await redis_client.get('test:1') is not None

        assert mock_reacquire.call_count >= 3
        assert _lock_logs(caplog) == [
            ('WARNING', 'Failed to renew lock test:1: Connection reset by peer'),
            ('WARNING', 'Failed to renew lock test:1: Connection reset by peer'),
        ]
        assert _other_tasks() == set()

    @patch.object(Lock, 'reacquire', autospec=True)
    async def test_hung_renewal_timed_out_and_retried(self, mock_reacquire, short_lease_registry, redis_client, caplog):
        """A hung renewal is timed out and retried on schedule, so the lock is kept."""
        caplog.set_level(logging.WARNING, logger='hermes.locks')

        def reacquire(lock):
            if mock_reacquire.call_count == 1:
                return asyncio.sleep(3600)
            return _real_reacquire(lock)

        mock_reacquire.side_effect = reacquire

        async with short_lease_registry.acquire(1):
            await asyncio.sleep(1.5)
            assert await redis_client.get('test:1') is not None

        assert mock_reacquire.call_count >= 2
        assert _lock_logs(caplog) == [('WARNING', 'Renewing lock test:1 timed out after 0.1s')]
        assert _other_tasks() == set()

    async def test_max_hold_stops_renewal(self, redis_client, monkeypatch, caplog):
        """Renewal stops after max_hold_seconds, so a stuck holder loses the lock within one more lease."""
        monkeypatch.setattr('app.core.redis.redis_client', redis_client)
        registry = RedisLockRegistry('test', lease_timeout_seconds=0.8, max_hold_seconds=0.5)
        caplog.set_level(logging.WARNING, logger='hermes.locks')

        async with registry.acquire(1):
            await asyncio.sleep(1.5)

        assert _lock_logs(caplog) == [
            ('ERROR', 'Lock test:1 held for over 0.5s, no longer renewing it'),
            ('ERROR', 'Lock test:1 was lost before it was released'),
        ]
        assert _other_tasks() == set()
