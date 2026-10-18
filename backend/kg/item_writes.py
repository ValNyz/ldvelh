"""
LDVELH - Per-item writes inside a larger transaction.

Each extracted item is written in its own SAVEPOINT: a failed item (validation, unique
violation, FK, CHECK...) is rolled back alone and recorded, the other items still commit.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from config import get_settings
from utils.log_safe import log_cause, safe_text

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def write_item(
    conn: Connection, errors: list[str], label: str,
    write: Callable[[], Awaitable[T]], log_prefix: str = "",
) -> T | None:
    """Run one item's writes in a SAVEPOINT. Returns write()'s result, None on failure.

    A failed item is rolled back to its savepoint and recorded in `errors` as
    "<label>: <cause>". The cause is safe_text: a validation or database error is
    summarised (field paths / exception class, SQLSTATE, constraint, table, column), never
    its message, which can quote the rejected story value. This also covers an SQL error
    swallowed inside write(): the trailing probe statement raises in the aborted savepoint,
    which is then rolled back like any other failure.

    If the transaction is already aborted when the item starts (an error swallowed outside
    any savepoint), the SAVEPOINT itself fails and the error propagates: nothing can commit
    any more, so the caller's whole transaction must be reported as failed.
    """
    savepoint = conn.transaction()
    await savepoint.start()
    try:
        result = await write()
        await conn.execute("SELECT 1")  # raises if write() left the savepoint aborted
    except Exception as e:
        await savepoint.rollback()
        errors.append(f"{label}: {safe_text(e)}")
        log_cause(logger, logging.WARNING, f"{log_prefix}{label} item failed", e,
                  debug_detail=get_settings().log_prompts)
        return None
    await savepoint.commit()
    return result


async def write_items(
    conn: Connection, stats: dict, label: str, items: Any,
    write: Callable[[Any], Awaitable[Any]], counter: str | None = None,
    log_prefix: str = "",
) -> None:
    """`write_item` for each item; a truthy write(item) result increments stats[counter]."""
    for item in items or ():
        done = await write_item(conn, stats["errors"], label,
                                lambda item=item: write(item), log_prefix)
        if done and counter:
            stats[counter] = stats.get(counter, 0) + 1
