"""Unit of work: one transaction on the caller's connection, journaled under a turn (#105).

Inside it, every world write is recorded in world_changes by the zz_journal_* triggers,
which read the turn id from the transaction-local setting ldvelh.turn_id.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from domain.errors import SourceMessageGone
from repos.turns import hold_source_message


@asynccontextmanager
async def uow(
    conn, turn_id: UUID | None, *, source_message_id: UUID | None = None
) -> AsyncIterator:
    """Transaction on `conn`; writes are journaled under `turn_id` when given.

    With `source_message_id`, the message is share-locked first: a rollback deleting it
    waits for this transaction, and a message already gone raises SourceMessageGone
    before any write (#23).
    """
    async with conn.transaction():
        if source_message_id and not await hold_source_message(conn, source_message_id):
            raise SourceMessageGone(source_message_id)
        if turn_id:
            # is_local = true: the setting ends with the transaction.
            await conn.execute(
                "SELECT set_config('ldvelh.turn_id', $1::text, true)", str(turn_id)
            )
        yield conn


async def current_turn_id(conn) -> UUID | None:
    """The turn the current transaction is journaled under, if any."""
    value = await conn.fetchval("SELECT current_setting('ldvelh.turn_id', true)")
    return UUID(value) if value else None
