"""C-19: rows written by the pre-refactor code must stay readable and playable.

The fixture is a frozen data-only dump (see make_legacy_fixture.py; header records the
schema version it was taken at). It is loaded into a schema built by ALL current
migrations, so this guards "legacy-shaped rows are readable/playable by the current schema
and code". It does NOT prove that a migration preserved data: migrations never run over
these rows (a pinned-version migrate-over harness is deferred to the first phase that
ships a migration).

Replica mode (see load_legacy_game) means triggers do not run on load: regenerate the
fixture when a migration adds triggers or derived tables, or they will be missing here.
"""

from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from services.auth_service import create_token
from tests.characterization.harness import ChatHarness
from tests.conftest import _db_unavailable

FIXTURE = Path(__file__).parent / "fixtures" / "legacy_game.sql"


def legacy_schema_version() -> str:
    """Latest migration version applied when the dump was taken (2nd header line)."""
    return FIXTURE.read_text(encoding="utf-8").splitlines()[1].split()[-1]


async def load_legacy_game(pool) -> tuple[str, str]:
    """Replace the test DB content with the legacy dump; return (game_id, user_email)."""
    sql = FIXTURE.read_text(encoding="utf-8")
    game_id = sql.splitlines()[0].split()[-1]
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE games CASCADE; TRUNCATE users CASCADE; TRUNCATE genres CASCADE;")
        # The dump has circular FKs (games <-> locations) and already contains the rows the
        # entity_registry triggers would create: load it as a replica (no FK checks, no
        # triggers), scoped to this transaction. Needs a superuser, as in the test DB.
        async with conn.transaction():
            try:
                await conn.execute("SET LOCAL session_replication_role = replica")
            except asyncpg.InsufficientPrivilegeError as exc:
                _db_unavailable(f"C-19 needs a superuser role to load the legacy dump: {exc}")
            await conn.execute(sql)
        email = await conn.fetchval(
            "SELECT u.email FROM users u JOIN games g ON g.user_id = u.id WHERE g.id = $1::uuid",
            game_id)
    return game_id, email


@pytest_asyncio.fixture
async def legacy_game(test_pool, scripted_llm):
    return await load_legacy_game(test_pool)


@pytest_asyncio.fixture
async def legacy_token(test_pool, legacy_game):
    game_id, email = legacy_game
    async with test_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT id FROM users WHERE email = $1", email)
    return create_token(user_id, email)


async def test_c19_legacy_game_loads_and_plays(client, test_pool, legacy_game, legacy_token, scripted_llm):
    """A legacy-shaped game loads with its Fate stats and accepts a new turn (see module docstring for scope)."""
    game_id, _ = legacy_game
    h = ChatHarness(client, test_pool, legacy_token, scripted_llm)

    r = await client.get(f"/api/games/{game_id}", headers=h.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    before = len(body["messages"])
    assert before >= 4
    stats = body["state"]["player"]["engine_stats"]
    assert stats["fate_points"] >= 1 and stats["refresh"] >= 1, stats
    assert "stress_physical" in stats and "consequences" in stats
    # Aspects are not part of the loaded vitals; they must survive in the legacy row.
    async with test_pool.acquire() as conn:
        aspects = await conn.fetchval("SELECT aspects FROM character_fate WHERE game_id = $1::uuid", game_id)
        rolls = await conn.fetchval("SELECT COUNT(*) FROM mechanic_rolls WHERE game_id = $1::uuid", game_id)
    assert aspects and len(aspects) >= 2, aspects
    assert rolls == 1

    events = await h.chat(game_id, "Je reprends ma partie.")
    await h.drain()
    assert "done" in h.summarize(events)

    r = await client.get(f"/api/games/{game_id}", headers=h.headers)
    assert len(r.json()["messages"]) > before
