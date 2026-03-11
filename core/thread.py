"""Thread/async helpers shared across modules."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine


def run_async_safely(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine from sync code in both sync and async-call contexts.

    - If no loop is currently running on this thread: uses ``asyncio.run``.
    - If a loop is running (e.g. FastAPI/Streamlit): runs the coroutine on a
      dedicated background thread with its own event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}

    def _thread_runner() -> None:
        try:
            result_holder["result"] = asyncio.run(coro)
        except BaseException as exc:  # preserve original exception type
            error_holder["error"] = exc

    worker = threading.Thread(target=_thread_runner, daemon=True)
    worker.start()
    worker.join()

    if "error" in error_holder:
        raise error_holder["error"]

    return result_holder.get("result")
