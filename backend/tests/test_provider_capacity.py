"""Capacity is held by real workers, not by the request coroutine's lifetime."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.provider_capacity import ProviderBusyError, ProviderCapacity


def test_timeout_does_not_release_worker_slot():
    capacity = ProviderCapacity()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def operation():
        entered.set()
        try:
            release.wait(3)
        finally:
            finished.set()

    async def check():
        call = asyncio.create_task(capacity.run(operation, limit=1))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            assert capacity.active == 1
            with pytest.raises(ProviderBusyError):
                await capacity.run(lambda: pytest.fail("Saturated call ran"), limit=1)
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 1)
        # Wait for the worker's finally bookkeeping without a wall-clock sleep.
        for _ in range(100):
            if capacity.active == 0:
                break
            await asyncio.sleep(0)
        assert await capacity.run(lambda: "recovered", limit=1) == "recovered"
        assert capacity.active == 0

    asyncio.run(check())


def test_cancelled_queued_worker_keeps_slot_until_it_exits():
    capacity = ProviderCapacity()
    blocker, entered = threading.Event(), threading.Event()

    async def check():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))

        def block():
            entered.set()
            blocker.wait(2)

        occupying = loop.run_in_executor(None, block)
        # Wait without consuming the only executor thread.
        for _ in range(1000):
            if entered.is_set():
                break
            await asyncio.sleep(0.001)
        assert entered.is_set()
        call = asyncio.create_task(capacity.run(lambda: None, limit=1))
        try:
            await asyncio.sleep(0)
            assert capacity.active == 1
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            assert capacity.active == 1
        finally:
            blocker.set()
            await occupying
        # Executor shutdown must finish the shielded queued call as well.
        await loop.shutdown_default_executor()
        assert capacity.active == 0

    asyncio.run(check())


def test_worker_error_releases_capacity():
    capacity = ProviderCapacity()

    def fail():
        raise ValueError("offline error")

    async def check():
        with pytest.raises(ValueError):
            await capacity.run(fail, limit=1)
        assert capacity.active == 0
        assert await capacity.run(lambda: 42, limit=1) == 42

    asyncio.run(check())


def test_late_failure_is_consumed_after_cancellation():
    capacity = ProviderCapacity()
    release, entered = threading.Event(), threading.Event()

    def fail_late():
        entered.set()
        release.wait(2)
        raise ValueError("must not appear in unhandled task logs")

    async def check():
        errors = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, ctx: errors.append(ctx))
        call = asyncio.create_task(capacity.run(fail_late, limit=1))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
        finally:
            release.set()
        async def released():
            while capacity.active:
                await asyncio.sleep(0.001)
        await asyncio.wait_for(released(), timeout=2)
        await asyncio.sleep(0)
        assert not errors

    asyncio.run(check())
