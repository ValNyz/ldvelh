"""In-flight Director runs per game (#79): at most one, and the initial one is awaited.

The initial Director may outlive its turn (client gone during world generation): the
first narration turn waits for it, bounded by what is left of its timeout, so it reads
the plan; a scheduled Director is not started while another run is in flight.
"""

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Run:
    task: asyncio.Task
    wait_until: float | None  # loop time a turn may wait until (initial run only)


# Also the strong references of the running tasks.
_runs: dict[UUID, _Run] = {}


def is_running(game_id: UUID) -> bool:
    return game_id in _runs


def start(game_id: UUID, coro: Coroutine[Any, Any, Any], *,
          wait_limit: float | None = None) -> asyncio.Task | None:
    """Run `coro` as the game's Director; None (coro dropped) if one is already in flight.

    `wait_limit` (seconds): turns of this game wait for the run that long at most.
    """
    if is_running(game_id):
        coro.close()
        logger.info(f"[DIRECTOR] Already running for game {game_id}, not started")
        return None
    loop = asyncio.get_running_loop()
    task = loop.create_task(coro)
    run = _Run(task, None if wait_limit is None else loop.time() + wait_limit)
    _runs[game_id] = run
    task.add_done_callback(lambda _task: _forget(game_id, run))
    return task


def _forget(game_id: UUID, run: _Run) -> None:
    if _runs.get(game_id) is run:
        del _runs[game_id]


async def wait_for_initial(game_id: UUID) -> None:
    """Wait for the game's in-flight initial Director, within what is left of its limit."""
    run = _runs.get(game_id)
    if run is None or run.wait_until is None:
        return
    remaining = run.wait_until - asyncio.get_running_loop().time()
    if remaining <= 0:
        return
    logger.info(f"[DIRECTOR] Waiting for the initial run of game {game_id}")
    # asyncio.wait never cancels the run, even if this turn is cancelled meanwhile.
    await asyncio.wait({run.task}, timeout=remaining)
