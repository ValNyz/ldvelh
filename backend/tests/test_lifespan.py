"""Shutdown order of main.lifespan: background jobs drain before the pool closes (#19, #94)."""

import asyncio
import logging
import uuid

import asyncpg
import pytest

import main
from services import llm_providers
from config import get_settings
from tests.conftest import TEST_DB_URL
from workers import supervisor


class _FakePool:
    def __init__(self, calls, close_error=None):
        self._calls = calls
        self._close_error = close_error

    async def close(self):
        self._calls.append("pool.close")
        if self._close_error:
            raise self._close_error


@pytest.fixture
def fake_pool(monkeypatch):
    class Calls(list):
        pass

    calls = Calls()

    async def create_pool(*args, **kwargs):
        calls.append(("create_pool", kwargs))
        return _FakePool(calls, close_error=close_error["error"])

    async def close_clients():
        calls.append("clients.close")

    close_error = {"error": None}
    calls.close_error = close_error

    async def seed(pool, settings):
        return None

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(main, "_seed_dev_user", seed)
    monkeypatch.setattr(llm_providers, "close_shared_clients", close_clients)
    return calls


async def test_lifespan_drains_before_closing_the_pool(fake_pool, monkeypatch):
    async def spy(timeout):
        assert timeout == get_settings().supervisor_drain_timeout
        fake_pool.append("drain")

    monkeypatch.setattr(supervisor, "drain", spy)
    async with main.lifespan(main.app):
        pass
    assert fake_pool[1:] == ["drain", "pool.close", "clients.close"]
    assert main.db_pool is None
    assert fake_pool[0][1]["server_settings"] == main.POOL_SERVER_SETTINGS


async def test_lifespan_cancels_a_stuck_job_at_shutdown(fake_pool, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "supervisor_drain_timeout", 0.1)
    caplog.set_level(logging.WARNING)
    async with main.lifespan(main.app):
        task = supervisor.enqueue(uuid.uuid4(), "stuck", asyncio.sleep(3600))
        await asyncio.sleep(0)
    assert task.cancelled()
    assert "Cancelled at shutdown" in caplog.text
    assert fake_pool[1:] == ["pool.close", "clients.close"]


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
    assert "pool.close" in fake_pool and "clients.close" in fake_pool


async def test_drain_and_close_still_run_when_the_body_raises(fake_pool, monkeypatch):
    async def spy(timeout):
        fake_pool.append("drain")

    monkeypatch.setattr(supervisor, "drain", spy)
    with pytest.raises(ValueError):
        async with main.lifespan(main.app):
            raise ValueError("body")
    assert fake_pool[1:] == ["drain", "pool.close", "clients.close"]


async def test_pool_closes_when_the_drain_is_cancelled(fake_pool, monkeypatch):
    async def cancelled(timeout):
        raise asyncio.CancelledError

    monkeypatch.setattr(supervisor, "drain", cancelled)
    with pytest.raises(asyncio.CancelledError):
        async with main.lifespan(main.app):
            pass
    assert fake_pool[1:] == ["pool.close", "clients.close"]


async def test_clients_close_when_the_pool_close_raises(fake_pool, monkeypatch):
    fake_pool.close_error["error"] = RuntimeError("close broke")
    with pytest.raises(RuntimeError, match="close broke"):
        async with main.lifespan(main.app):
            pass
    assert fake_pool[1:] == ["pool.close", "clients.close"]


@pytest.mark.parametrize("name", ["WEB_CONCURRENCY", "UVICORN_WORKERS"])
async def test_multi_worker_start_is_refused_before_the_pool_exists(fake_pool, monkeypatch, name):
    monkeypatch.setenv(name, "2")
    with pytest.raises(RuntimeError, match=name):
        async with main.lifespan(main.app):
            pass
    assert fake_pool == []  # no pool created, nothing to close
