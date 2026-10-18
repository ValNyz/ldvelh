"""Shutdown order of main.lifespan: background jobs drain before the pool closes (#19, #94)."""

import asyncio
import logging
import uuid

import asyncpg
import pytest

import main
from config import get_settings
from tests.conftest import TEST_DB_URL
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
        calls.append(("create_pool", kwargs))
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
    assert fake_pool[1:] == ["drain", "pool.close"]
    assert fake_pool[0][1]["server_settings"] == main.POOL_SERVER_SETTINGS


async def test_lifespan_cancels_a_stuck_job_at_shutdown(fake_pool, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "supervisor_drain_timeout", 0.1)
    caplog.set_level(logging.WARNING)
    async with main.lifespan(main.app):
        task = supervisor.enqueue(uuid.uuid4(), "stuck", asyncio.sleep(3600))
        await asyncio.sleep(0)
    assert task.cancelled()
    assert "Cancelled at shutdown" in caplog.text
    assert fake_pool[1:] == ["pool.close"]


async def test_pool_connections_carry_the_server_side_timeouts(test_pool):
    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=1,
                                     server_settings=main.POOL_SERVER_SETTINGS)
    try:
        async with pool.acquire() as conn:
            assert await conn.fetchval("SHOW idle_in_transaction_session_timeout") == "30s"
            assert await conn.fetchval("SHOW statement_timeout") == "1min"
    finally:
        await pool.close()


async def test_pool_closes_when_the_drain_raises(fake_pool, monkeypatch):
    async def failing(timeout):
        raise RuntimeError("drain broke")

    monkeypatch.setattr(supervisor, "drain", failing)
    with pytest.raises(RuntimeError, match="drain broke"):  # the error still propagates
        async with main.lifespan(main.app):
            pass
    assert "pool.close" in fake_pool


async def test_drain_and_close_still_run_when_the_body_raises(fake_pool, monkeypatch):
    async def spy(timeout):
        fake_pool.append("drain")

    monkeypatch.setattr(supervisor, "drain", spy)
    with pytest.raises(ValueError):
        async with main.lifespan(main.app):
            raise ValueError("body")
    assert fake_pool[1:] == ["drain", "pool.close"]


@pytest.mark.parametrize("name", ["WEB_CONCURRENCY", "UVICORN_WORKERS"])
async def test_multi_worker_start_is_refused_before_the_pool_exists(fake_pool, monkeypatch, name):
    monkeypatch.setenv(name, "2")
    with pytest.raises(RuntimeError, match=name):
        async with main.lifespan(main.app):
            pass
    assert fake_pool == []  # no pool created, nothing to close
