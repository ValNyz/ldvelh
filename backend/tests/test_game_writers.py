"""game_writers.is_busy: the C-13 busy decision (#79)."""

import asyncio

from api import game_writers
from api.streaming import SSEWriter

TIMEOUT = 5.0


async def _registered(key: str, *, disconnected: bool) -> tuple[SSEWriter, asyncio.Event]:
    writer, release = SSEWriter(), asyncio.Event()
    writer.disconnected = disconnected
    game_writers.register(key, writer, asyncio.create_task(release.wait()))
    return writer, release


async def test_free_lock_is_never_busy():
    _, release = await _registered("g-free", disconnected=False)
    assert game_writers.is_busy("g-free", asyncio.Lock()) is False
    release.set()


async def test_lock_held_without_writer_is_busy():
    """Held by something else than a chat (e.g. a rollback)."""
    lock = asyncio.Lock()
    async with lock:
        assert game_writers.is_busy("g-rollback", lock) is True


async def test_lock_held_by_client_less_requests_is_not_busy():
    lock = asyncio.Lock()
    _, r1 = await _registered("g-gone", disconnected=True)
    _, r2 = await _registered("g-gone", disconnected=True)
    async with lock:
        assert game_writers.is_busy("g-gone", lock) is False
        _, r3 = await _registered("g-gone", disconnected=False)
        assert game_writers.is_busy("g-gone", lock) is True
    for release in (r1, r2, r3):
        release.set()
    await asyncio.sleep(0.01)
    assert game_writers.writers_of("g-gone") == []
