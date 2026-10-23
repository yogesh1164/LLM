"""Bound admitted synchronous work, including workers abandoned by a timeout.

No application queue and no new executor: use asyncio's existing executor, but
hold a slot until the actual worker exits. Coroutine cancellation alone must
never release capacity for a still-running provider request.
"""

import asyncio
import threading
from collections.abc import Callable
from contextvars import copy_context
from typing import TypeVar

T = TypeVar("T")


class ProviderBusyError(RuntimeError):
    """Fail fast before sending a request when all worker slots are occupied."""


class ProviderCapacity:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    async def run(self, operation: Callable[[], T], *, limit: int) -> T:
        with self._lock:
            if self._active >= limit:
                raise ProviderBusyError("AI workers are busy; try again shortly")
            self._active += 1

        def worker() -> T:
            try:
                return operation()
            finally:
                with self._lock:
                    self._active -= 1

        try:
            # Like to_thread, use the default executor and propagate context.
            # Keep the Future (not a Task wrapping it) shielded so event-loop
            # task cleanup cannot abandon a reserved queued worker slot.
            context = copy_context()
            future = asyncio.get_running_loop().run_in_executor(None, context.run, worker)
        except BaseException:
            with self._lock:
                self._active -= 1
            raise

        def consume_exception(done: asyncio.Future) -> None:
            if not done.cancelled():
                done.exception()  # Late provider errors must not enter raw asyncio logs.

        future.add_done_callback(consume_exception)
        return await asyncio.shield(future)


provider_capacity = ProviderCapacity()
