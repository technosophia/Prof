"""Thread/async helpers shared across modules."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Coroutine


def run_async_safely(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine from sync code safely in any context.

    Always runs the coroutine in a dedicated background thread with its own
    event loop to avoid event loop conflicts in threaded environments.
    """
    def _thread_runner() -> Any:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_thread_runner)
        return future.result()
