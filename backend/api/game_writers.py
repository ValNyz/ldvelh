"""Writers of the accepted /chat requests per game, while their task runs (C-13, #20, #79).

A game is busy when its lock is held, unless every one of these writers lost its client.
Every accepted writer stays registered until its own task is done (done callback), so
an entry cannot leak (task cancelled before its first step) nor vanish early (a queued
resend cancelled while an older, client-less turn still holds the lock).
"""

import asyncio

from api.streaming import SSEWriter

_writers: dict[str, list[SSEWriter]] = {}


def register(key: str, writer: SSEWriter, task: asyncio.Task) -> None:
    """Track `writer` for game `key` until `task` is done."""
    _writers.setdefault(key, []).append(writer)
    task.add_done_callback(lambda _task: _unregister(key, writer))


def _unregister(key: str, writer: SSEWriter) -> None:
    writers = _writers.get(key)
    if writers is None:
        return
    writers[:] = [w for w in writers if w is not writer]  # only this writer's own entry
    if not writers:
        del _writers[key]


def writers_of(key: str) -> list[SSEWriter]:
    """The registered writers of a game (a copy)."""
    return list(_writers.get(key, ()))


def is_busy(key: str, held: bool) -> bool:
    """C-13: a new /chat is rejected while the game lock is held (`held`), unless every accepted
    request lost its client (they are being cancelled: the new one queues behind them).

    No writer at all with the lock held is busy: something else holds it (e.g. a rollback).
    """
    if not held:
        return False
    writers = writers_of(key)
    return not writers or any(not w.disconnected for w in writers)
