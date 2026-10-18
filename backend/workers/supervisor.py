"""Per-game background job supervisor (#19, #94).

Every background job (post-turn extraction, Director runs...) goes through `enqueue`:
the task is referenced until it ends, the jobs of one game run one after the other in
enqueue order, and at most `supervisor_max_running_games` games run a job at once.
A job never cancels its predecessor; a cancelled or failed predecessor does not block it.

Rule: a job must not await `wait_idle` on its own game, nor a job it enqueued on its own
game. Successors wait on the current job, so such an await blocks until its timeout.
"""

import asyncio
import logging
from collections.abc import Coroutine, Iterable
from functools import partial
from typing import Any, TypeVar
from uuid import UUID

from config import get_settings
from utils.log_safe import log_exception

logger = logging.getLogger(__name__)

T = TypeVar("T")

_QUEUE_DEPTH_WARNING = 3  # unfinished jobs of one game above which enqueue warns
_SHUTDOWN_GRACE = 5.0  # seconds drain() waits for the jobs it cancelled

_jobs: dict[UUID, list[asyncio.Task]] = {}
_semaphore: asyncio.Semaphore | None = None


def _new_semaphore(max_running_games: int | None) -> asyncio.Semaphore:
    if max_running_games is None:
        max_running_games = get_settings().supervisor_max_running_games
    if max_running_games < 1:  # Semaphore(0) would block every job silently
        raise ValueError(f"max_running_games must be at least 1, got {max_running_games}")
    return asyncio.Semaphore(max_running_games)


def _slots() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = _new_semaphore(None)
    return _semaphore


async def _run(predecessors: list[asyncio.Task], coro: Coroutine[Any, Any, T]) -> T:
    if predecessors:
        await asyncio.wait(predecessors)  # never cancels them, whatever their outcome
    async with _slots():  # acquired after the chain wait: a queued job takes no slot
        return await coro


def _on_done(game_id: UUID, kind: str, coro: Coroutine, task: asyncio.Task) -> None:
    coro.close()  # a job cancelled before it started: no "never awaited" warning
    jobs = _jobs.get(game_id)
    if jobs is not None and task in jobs:
        jobs.remove(task)
        if not jobs:
            del _jobs[game_id]
    if task.cancelled():
        logger.info(f"[SUPERVISOR] {kind} cancelled game={game_id}")
    elif (exc := task.exception()) is not None:
        log_exception(logger, logging.ERROR, f"[SUPERVISOR] {kind} failed game={game_id}", exc,
                      debug_detail=get_settings().log_prompts)
    else:
        logger.debug(f"[SUPERVISOR] {kind} done game={game_id}")


def _unfinished(game_id: UUID | None = None, *,
                skip_current: bool = True) -> list[asyncio.Task]:
    if game_id is not None:
        jobs: Iterable[asyncio.Task] = _jobs.get(game_id, ())
    else:
        jobs = (task for tasks in _jobs.values() for task in tasks)
    # A job waiting on or cancelling its own game must not wait on itself.
    current = asyncio.current_task() if skip_current else None
    return [task for task in jobs if not task.done() and task is not current]


def enqueue(game_id: UUID, kind: str, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
    """Run `coro` as a background job of the game, after the game's earlier jobs."""
    # Wait for every unfinished predecessor, not only the last one: if that one is
    # cancelled while queued, an earlier job may still be running.
    # A job enqueuing on its own game is a predecessor of the new job too.
    predecessors = _unfinished(game_id, skip_current=False)
    task = asyncio.create_task(_run(predecessors, coro), name=f"{kind}:{game_id}")
    _jobs.setdefault(game_id, []).append(task)
    task.add_done_callback(partial(_on_done, game_id, kind, coro))
    depth = pending(game_id)
    if depth > _QUEUE_DEPTH_WARNING:
        logger.warning(f"[SUPERVISOR] game={game_id} queue depth={depth}")
    return task


def pending(game_id: UUID | None = None) -> int:
    """Unfinished jobs of the game, or of every game."""
    if game_id is not None:
        return sum(not task.done() for task in _jobs.get(game_id, ()))
    return sum(not task.done() for tasks in _jobs.values() for task in tasks)


async def wait_idle(game_id: UUID | None = None, *, timeout: float) -> list[asyncio.Task]:
    """Wait until the game (or every game) has no job left, jobs enqueued meanwhile included.

    Returns the tasks waited on; raises TimeoutError if some are still unfinished.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    waited: dict[asyncio.Task, None] = {}
    while tasks := _unfinished(game_id):
        waited.update(dict.fromkeys(tasks))
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"[SUPERVISOR] {len(tasks)} job(s) still running")
        await asyncio.wait(tasks, timeout=remaining)
    return list(waited)


async def cancel_game(game_id: UUID, *, timeout: float) -> int:
    """Cancel every unfinished job of the game, wait up to `timeout` for them to end.

    The jobs are those unfinished at call time: a job enqueued during the wait is not
    cancelled (rollback calls this under the game lock, so no turn enqueues meanwhile).
    """
    tasks = _unfinished(game_id)
    for task in tasks:
        task.cancel()
    if tasks:
        _, still_running = await asyncio.wait(tasks, timeout=timeout)
        if still_running:
            logger.error(f"[SUPERVISOR] game={game_id} {len(still_running)} job(s) "
                         "still running after cancel")
    return len(tasks)


async def drain(timeout: float) -> None:
    """Shutdown: let the jobs finish within `timeout`, then cancel what remains."""
    try:
        await wait_idle(timeout=timeout)
        return
    except TimeoutError:
        pass
    tasks = _unfinished()
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    _, still_running = await asyncio.wait(tasks, timeout=_SHUTDOWN_GRACE)
    for task in (task for task in tasks if task.cancelled()):
        kind, _, game_id = task.get_name().rpartition(":")
        logger.warning(f"[SUPERVISOR] Cancelled at shutdown kind={kind} game={game_id}")
    if still_running:
        logger.error(f"[SUPERVISOR] {len(still_running)} job(s) still running after shutdown")


def reset(max_running_games: int | None = None) -> None:
    """Forget every job without touching the tasks, and recreate the semaphore (tests).

    The previous event loop is closed: its tasks and semaphore cannot be reused.
    """
    global _semaphore
    _semaphore = _new_semaphore(max_running_games)
    _jobs.clear()
