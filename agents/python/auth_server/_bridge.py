"""Sync-over-async bridge for authlib's callbacks.

authlib's OAuth2 core (``AuthorizationServer``, grant classes, client/token
mixins) is entirely synchronous — there is no Starlette/FastAPI integration
and no async support. This repo's database access (asyncpg) is entirely
async. Rather than adding a second, synchronous Postgres driver just for
this one service, the token endpoint runs authlib's synchronous call chain
in a worker thread (via ``asyncio.to_thread``) and any of its callbacks
that need the database submit a coroutine back onto the main event loop —
the one that owns the asyncpg pool — via ``run_coroutine_threadsafe`` and
block only the worker thread while waiting.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_main_loop: asyncio.AbstractEventLoop | None = None


def bind_main_loop() -> None:
    """Capture the running event loop. Call once, during app startup."""
    global _main_loop
    _main_loop = asyncio.get_running_loop()


def run_coro_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from synchronous code and block for the result.

    Safe to call from a worker thread (e.g. inside ``asyncio.to_thread``);
    raises if called from the main loop's own thread, since that would
    deadlock waiting on itself.
    """
    if _main_loop is None:
        raise RuntimeError("bind_main_loop() was not called during startup")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("run_coro_sync() must not be called from the main event loop's thread")
    return asyncio.run_coroutine_threadsafe(coro, _main_loop).result()
