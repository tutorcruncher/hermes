import asyncio

import pytest

from app.core.locks import LockRegistry


class TestLockRegistry:
    """Tests that the LockRegistry correctly removes locks from its internal dict
    when they are no longer needed, and keeps them when they are still in use.
    Covers normal completion, exceptions, cancellation, and concurrent use."""

    async def test_cleanup_after_normal_completion(self):
        """Lock is removed from the registry after the work finishes normally."""
        registry = LockRegistry()
        async with registry.acquire(1):
            assert 1 in registry._locks
        assert 1 not in registry._locks

    async def test_cleanup_after_body_raises(self):
        """Lock is removed from the registry even when the body raises an exception."""
        registry = LockRegistry()
        with pytest.raises(ValueError):
            async with registry.acquire(1):
                raise ValueError('boom')
        assert 1 not in registry._locks

    async def test_cleanup_after_waiter_cancelled(self):
        """Lock is removed after a queued waiter is cancelled mid-wait."""
        registry = LockRegistry()

        async with registry.acquire(1):

            async def waiter():
                async with registry.acquire(1):
                    pass

            task = asyncio.create_task(waiter())
            # Let the waiter reach the acquire() and block
            await asyncio.sleep(0)
            # Cancel it while it's waiting
            task.cancel()
            await asyncio.sleep(0)

        assert 1 not in registry._locks

    async def test_lock_not_evicted_while_waiter_queued(self):
        """Lock stays in the registry while another coroutine is still waiting on it."""
        registry = LockRegistry()
        entered = asyncio.Event()

        async with registry.acquire(1):

            async def waiter():
                async with registry.acquire(1):
                    entered.set()

            task = asyncio.create_task(waiter())
            await asyncio.sleep(0)
            # Waiter is queued, lock should still be in the registry
            assert 1 in registry._locks

        # Let waiter finish
        await entered.wait()
        await task
        assert 1 not in registry._locks

    async def test_different_keys_independent(self):
        """Different keys run concurrently and both get cleaned up independently."""
        registry = LockRegistry()
        order = []

        async def work(key, label):
            async with registry.acquire(key):
                order.append(f'{label}_start')
                await asyncio.sleep(0)
                order.append(f'{label}_end')

        await asyncio.gather(work(1, 'a'), work(2, 'b'))
        # Both should interleave since they use different keys
        assert order == ['a_start', 'b_start', 'a_end', 'b_end']
        assert 1 not in registry._locks
        assert 2 not in registry._locks
