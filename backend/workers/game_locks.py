"""Per-game turn lock, with purge of idle entries (#94)."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator
from uuid import UUID


@dataclass
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    holders: int = 0  # the holder plus everyone queued behind it


_entries: dict[UUID, _Entry] = {}


@asynccontextmanager
async def hold(game_id: UUID) -> AsyncIterator[None]:
    """Hold the game's turn lock; the entry is dropped once nobody holds or awaits it."""
    entry = _entries.setdefault(game_id, _Entry())
    entry.holders += 1
    try:
        async with entry.lock:
            yield
    finally:
        entry.holders -= 1
        if entry.holders == 0:
            del _entries[game_id]


def is_held(game_id: UUID) -> bool:
    entry = _entries.get(game_id)
    return entry is not None and entry.lock.locked()


def tracked() -> int:
    """Number of live entries (tests)."""
    return len(_entries)
