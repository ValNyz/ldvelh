"""Finish a started commit and what follows it even if the turn is cancelled meanwhile (#20).

Once the commit has started (DB only, milliseconds), the commit, the done payload and the
background scheduling (extraction, Director) must run: a client closing the stream at that
moment cancels nothing.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


async def finish_despite_cancel(coro: Coroutine[Any, Any, None], *, ref: str) -> None:
    """Run `coro` to completion; a cancellation of the caller is re-raised only afterwards.

    Not cancelled: behaves like `await coro` (its exceptions propagate to the caller).
    Cancelled: waits for `coro` to finish, logs its failure if any (the caller is going
    away and cannot report it), then re-raises CancelledError.
    """
    task = asyncio.create_task(coro)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        if task.cancelled():
            raise
        logger.info(f"[TURN:{ref}] Cancelled once the commit started; finishing the turn")
        await _wait_ignoring_cancel(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error(f"[TURN:{ref}] Post-commit step failed after cancellation",
                         exc_info=task.exception())
        raise


async def _wait_ignoring_cancel(task: asyncio.Task) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue  # cancelled again from outside: keep waiting for the shielded task
        except Exception:
            return  # the caller logs task.exception()
