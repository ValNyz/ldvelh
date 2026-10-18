"""Shutdown order of main.lifespan: background jobs drain before the pool closes (#19, #94)."""

import asyncio
import logging
import uuid

import asyncpg
import pytest

import main
from config import get_settings
from workers import supervisor


class _FakePool:
    def __init__(self, calls):
        self._calls = calls

    async def close(self):
        self._calls.append("pool.close")


@pytest.fixture
def fake_pool(monkeypatch):
    calls = []

    async def create_pool(*args, **kwargs):
        return _FakePool(calls)

    async def seed(pool, settings):
        return None

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(main, "_seed_dev_user", seed)
    return calls


async def test_lifespan_drains_before_closing_the_pool(fake_pool, monkeypatch):
    async def spy(timeout):
        assert timeout == get_settings().supervisor_drain_timeout
        fake_pool.append("drain")

    monkeypatch.setattr(supervisor, "drain", spy)
    async with main.lifespan(main.app):
        pass
    assert fake_pool == ["drain", "pool.close"]


async def test_lifespan_cancels_a_stuck_job_at_shutdown(fake_pool, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "supervisor_drain_timeout", 0.1)
    caplog.set_level(logging.WARNING)
    async with main.lifespan(main.app):
        task = supervisor.enqueue(uuid.uuid4(), "stuck", asyncio.sleep(3600))
        await asyncio.sleep(0)
    assert task.cancelled()
    assert "Cancelled at shutdown" in caplog.text
    assert fake_pool == ["pool.close"]


async def test_pool_connections_carry_the_server_side_timeouts(test_pool):
    from tests.conftest import TEST_DB_URL

    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=1,
                                     server_settings=main.POOL_SERVER_SETTINGS)
    try:
        async with pool.acquire() as conn:
            assert await conn.fetchval("SHOW idle_in_transaction_session_timeout") == "30s"
            assert await conn.fetchval("SHOW statement_timeout") == "1min"
    finally:
        await pool.close()
