"""Finish a started commit and what follows it even if the turn is cancelled meanwhile (#20).

Once the commit has started (DB only, milliseconds), the commit, the done payload and the
background scheduling (extraction, Director) must run: a client closing the stream at that
moment cancels nothing.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

from config import get_settings
from utils.log_safe import log_exception

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def finish_despite_cancel(coro: Coroutine[Any, Any, T], *, ref: str) -> T:
    """Run `coro` to completion; a cancellation of the caller is re-raised only afterwards.

    Not cancelled: behaves like `await coro` (returns its result, its exceptions propagate
    to the caller; a BaseException that is not an Exception is logged first, as no caller
    reports it).
    Cancelled: waits for `coro` to finish, logs its failure if any (the caller is going
    away and cannot report it), then re-raises CancelledError, or the failure itself when
    it is a BaseException that is not an Exception.
    """
    task = asyncio.create_task(coro)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if task.cancelled():
            raise
        logger.info(f"[TURN:{ref}] Cancelled once the commit started; finishing the turn")
        await _wait_ignoring_cancel(task)
        failure = None if task.cancelled() else task.exception()
        if failure is not None:
            _log_failure(ref, "Commit or post-commit step failed after cancellation", failure)
            if not isinstance(failure, Exception):
                raise failure
        raise
    except Exception:
        raise  # the caller reports it
    except BaseException as exc:
        _log_failure(ref, "Commit or post-commit step aborted", exc)
        raise


def _log_failure(ref: str, message: str, exc: BaseException) -> None:
    log_exception(logger, logging.ERROR, f"[TURN:{ref}] {message}", exc,
                  debug_detail=get_settings().log_prompts)


async def _wait_ignoring_cancel(task: asyncio.Task) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue  # cancelled again from outside: keep waiting for the shielded task
        except BaseException:
            return  # the caller logs task.exception()
