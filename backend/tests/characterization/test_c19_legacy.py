"""C-19: rows written by the pre-refactor code must stay readable and playable.

The fixture is a frozen data-only dump (see make_legacy_fixture.py; header records the
schema version it was taken at). Every migration newer than that version is replayed over
it: their down sections run on the empty schema, the dump is loaded, then their up sections
run over the legacy rows, all in one transaction. So this guards both "legacy-shaped rows
are readable/playable by the current schema and code" and "the newer migrations keep
(or convert) legacy data", e.g. a roll left pending before #32 becomes expired.

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
MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
LEGACY_PENDING_ROLL = "7c1d1f0e-5b7a-4c8e-9a51-2f4d3b6e8a10"


def legacy_schema_version() -> str:
    """Latest migration version applied when the dump was taken (2nd header line)."""
    return FIXTURE.read_text(encoding="utf-8").splitlines()[1].split()[-1]


def newer_migrations(version: str) -> list[tuple[str, str]]:
    """(up, down) SQL of every dbmate migration newer than `version`, oldest first."""
    sections = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name.split("_", 1)[0] <= version:
            continue
        text = path.read_text(encoding="utf-8")
        up, down = text.split("-- migrate:down", 1)
        sections.append((up.split("-- migrate:up", 1)[1], down))
    return sections


async def load_legacy_game(pool) -> tuple[str, str]:
    """Replace the test DB content with the legacy dump; return (game_id, user_email)."""
    sql = FIXTURE.read_text(encoding="utf-8")
    game_id = sql.splitlines()[0].split()[-1]
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE games CASCADE; TRUNCATE users CASCADE; TRUNCATE genres CASCADE;")
        # The dump has circular FKs (games <-> locations) and already contains the rows the
        # entity_registry triggers would create: load it as a replica (no FK checks, no
        # triggers), scoped to this transaction. Needs a superuser, as in the test DB.
        # The migrations newer than the dump go down first and up again over its rows.
        migrations = newer_migrations(legacy_schema_version())
        async with conn.transaction():
            for _, down in reversed(migrations):
                await conn.execute(down)
            try:
                await conn.execute("SET LOCAL session_replication_role = replica")
            except asyncpg.InsufficientPrivilegeError as exc:
                _db_unavailable(f"C-19 needs a superuser role to load the legacy dump: {exc}")
            await conn.execute(sql)
            await conn.execute("SET LOCAL session_replication_role = origin")
            for up, _ in migrations:
                await conn.execute(up)
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
    assert rolls == 2
    assert body["state"]["pending_roll"] is None

    events = await h.chat(game_id, "Je reprends ma partie.")
    await h.drain()
    assert "done" in h.summarize(events)

    r = await client.get(f"/api/games/{game_id}", headers=h.headers)
    assert len(r.json()["messages"]) > before


async def test_legacy_pending_rows_are_expired(test_pool, legacy_game):
    """#32: a roll left without a message by the old code is expired, the resolved one kept."""
    game_id, _ = legacy_game
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, status, message_id IS NULL AS orphan FROM mechanic_rolls"
            " WHERE game_id = $1::uuid ORDER BY created_at", game_id)
    assert [(r["status"], r["orphan"]) for r in rows] == [("resolved", False), ("expired", True)]
    assert rows[1]["id"] == LEGACY_PENDING_ROLL


async def test_legacy_users_start_at_token_version_zero(client, test_pool, legacy_game):
    """#83: users saved before token_version get version 0 and can sign in again."""
    _, email = legacy_game
    async with test_pool.acquire() as conn:
        assert await conn.fetchval("SELECT token_version FROM users WHERE email = $1", email) == 0
    login = await client.post("/api/auth/login",
                              json={"identifier": email, "password": "testpassword"})
    assert login.status_code == 200, login.text
    me = await client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert me.status_code == 200


async def test_legacy_arrival_facts_get_protagonist_keys(test_pool, legacy_game):
    """#28: the migration renames the system semantic keys valentin:* to protagonist:*."""
    from uuid import UUID

    from kg.reader import KnowledgeGraphReader

    game_id, _ = legacy_game
    async with test_pool.acquire() as conn:
        keys = await conn.fetch(
            "SELECT semantic_key FROM facts WHERE game_id = $1::uuid AND cycle = 1"
            " ORDER BY semantic_key", game_id)
        arrival = await KnowledgeGraphReader(test_pool, UUID(game_id)).get_arrival_event(conn)
    assert [k["semantic_key"] for k in keys] == [
        "protagonist:arrival:incident", "protagonist:arrival:mood", "protagonist:arrival:need",
        "protagonist:arrival:sensory", "protagonist:arrival:station"]
    assert arrival["arrival_description"].startswith("Arrivée sur la station via navette cargo")
    assert arrival["initial_mood"] == "fatigué, nauséeux, décalé"
    assert arrival["immediate_need"] == "Trouver l'appartement et dormir"
    assert arrival["incident"] == "Systèmes bagages en panne, attente indéterminée"
