"""Buffered LLM call log (#106): each billed call is kept in memory, then written to
llm_calls in one insert at the end of its phase (request, background job, world route).

A phase flushes in a `finally`, so halted, failed and disconnected work is logged too.
The flush acquires its own connection: no caller may hold a pool connection across an LLM
call or a flush (a request would then hold two and could starve the pool, #94, #96).
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

import asyncpg

from repos import llm_calls
from utils.log_safe import log_exception

logger = logging.getLogger(__name__)

# Bounded wait for a connection: a disconnected request flushing on an exhausted pool must
# not hold its game lock indefinitely; past it, the rows are dropped (logged at ERROR).
FLUSH_ACQUIRE_TIMEOUT = 10.0


class CallLog:
    """The unwritten call rows of one phase, under the turn current at each call."""

    def __init__(
        self,
        pool: asyncpg.Pool | None,
        *,
        game_id: UUID | None,
        user_id: UUID | None,
        turn_id: UUID | None = None,
    ):
        # None: nothing is ever written (from_provider sessions, tests).
        self.pool = pool
        self.game_id = game_id
        self.user_id = user_id
        self.turn_id = turn_id
        self._rows: list[dict] = []

    def fork(self) -> "CallLog":
        """An empty log of the same game, user and turn, for a phase flushing on its own."""
        return CallLog(
            self.pool, game_id=self.game_id, user_id=self.user_id, turn_id=self.turn_id
        )

    def add(
        self,
        *,
        purpose: str,
        provider: str,
        model: str,
        usage: dict,
        cost_usd: float,
        cost_unknown: bool,
    ) -> None:
        if self.pool is None:
            return
        self._rows.append(
            {
                "turn_id": self.turn_id,
                "game_id": self.game_id,
                "user_id": self.user_id,
                "purpose": purpose,
                "provider": provider,
                "model": model,
                "usage": usage,
                "cost_usd": cost_usd,
                "cost_unknown": cost_unknown,
                "created_at": datetime.now(UTC),  # the call's time, not the flush's
            }
        )

    @property
    def pending(self) -> int:
        return len(self._rows)

    async def flush(self) -> None:
        """Write the buffered rows in one insert. The buffer is emptied first, so a failed
        flush never inserts twice; its failure is logged, never raised."""
        rows, self._rows = self._rows, []
        if not rows or self.pool is None:
            return
        try:
            async with self.pool.acquire(timeout=FLUSH_ACQUIRE_TIMEOUT) as conn:
                try:
                    await llm_calls.insert_calls(conn, rows)
                except asyncpg.ForeignKeyViolationError:
                    # A turn or game deleted while the insert ran: once more, the insert
                    # then sees the deletion and stores NULL for it.
                    await llm_calls.insert_calls(conn, rows)
        except Exception as e:
            log_exception(
                logger,
                logging.ERROR,
                f"[COST] llm_calls insert failed rows={len(rows)}",
                e,
            )
