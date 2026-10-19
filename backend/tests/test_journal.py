"""The world_changes journal (#105): every world write made inside a turn's transaction
is recorded by the zz_journal_* triggers, in firing order, and nothing outside a turn."""

import json
from uuid import UUID

import pytest

from domain.turn import NarrationState
from repos import turns
from repos.uow import uow
from tests.test_game_and_populator import _setup_game_with_world

pytestmark = pytest.mark.integration

# Tables with a game_id that are not world state: never journaled (llm_calls: cost
# accounting, #106; a rolled back turn keeps the calls it paid for).
NOT_JOURNALED = {"messages", "conversations", "extraction_logs", "turns", "llm_calls"}
# World tables without a game_id column (pivots and per-entity engine rows).
PIVOTS = {
    "fact_participants",
    "arc_participants",
    "event_participants",
    "chronology_participants",
    "npc_fate",
    "npc_d6",
    "npc_narrative",
    "object_fate",
    "object_d6",
    "object_narrative",
}


@pytest.fixture
async def world(client, test_user, test_pool):
    """(game_id, turn_id): a populated game and one open turn."""
    game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game_id)
    return game_id, turn_id


async def _journal(conn, turn_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        """SELECT id, table_name, row_id, op, old_row, new_row FROM world_changes
        WHERE turn_id = $1 ORDER BY id""",
        turn_id,
    )
    out = []
    for r in rows:
        d = dict(r)
        for key in ("old_row", "new_row"):
            if isinstance(d[key], str):
                d[key] = json.loads(d[key])
        out.append(d)
    return out


async def _count(conn) -> int:
    return await conn.fetchval("SELECT count(*) FROM world_changes")


async def test_insert_update_delete_are_journaled_in_order(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        async with uow(conn, turn_id):
            char_id = await conn.fetchval(
                "INSERT INTO characters (game_id, name) VALUES ($1, 'Journa') RETURNING id",
                game_id,
            )
            await conn.execute(
                "UPDATE characters SET mood = 'grave' WHERE id = $1", char_id
            )
            await conn.execute("DELETE FROM characters WHERE id = $1", char_id)
        rows = [
            r for r in await _journal(conn, turn_id) if r["table_name"] == "characters"
        ]

    assert [r["op"] for r in rows] == ["I", "U", "D"]
    assert {r["row_id"] for r in rows} == {char_id}
    assert rows[0]["new_row"]["name"] == "Journa"
    assert rows[0]["old_row"] is None
    assert set(rows[1]["old_row"]) == {"mood"}
    assert rows[1]["new_row"] == {"mood": "grave"}
    assert rows[2]["old_row"]["name"] == "Journa"
    assert rows[2]["new_row"] is None


async def test_registry_row_is_journaled_before_the_entity(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        async with uow(conn, turn_id):
            await conn.execute(
                "INSERT INTO characters (game_id, name) VALUES ($1, 'Registre')",
                game_id,
            )
        rows = await _journal(conn, turn_id)

    assert [(r["table_name"], r["op"]) for r in rows] == [
        ("entity_registry", "I"),
        ("characters", "I"),
    ]


async def test_cascade_children_are_journaled_after_the_parent(test_pool, world):
    """An ON DELETE CASCADE runs its child deletes without firing their AFTER triggers on
    the spot (RI uses SPI with fire_triggers = false): they are queued behind the parent's
    own zz_journal_id, so the children's D rows follow the parent's, in the same turn."""
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO characters (game_id, name) VALUES ($1, 'Témoin')", game_id
        )
        fact_id = await conn.fetchval(
            "SELECT create_fact($1, 1, 'action', 'Un fait', p_participants => $2::jsonb)",
            game_id,
            [{"name": "Témoin", "role": "actor"}],
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM fact_participants WHERE fact_id = $1", fact_id
            )
            == 1
        )
        async with uow(conn, turn_id):
            await conn.execute("DELETE FROM facts WHERE id = $1", fact_id)
        rows = await _journal(conn, turn_id)

    deletes = [(r["table_name"], r["op"]) for r in rows]
    assert deletes == [("facts", "D"), ("fact_participants", "D")]


async def test_update_without_change_is_not_journaled(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        before = await _count(conn)
        async with uow(conn, turn_id):
            await conn.execute(
                "UPDATE characters SET mood = mood WHERE game_id = $1", game_id
            )
        assert await _count(conn) == before


async def test_games_update_of_world_columns_only(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        async with uow(conn, turn_id):
            await conn.execute("UPDATE games SET name = 'x' WHERE id = $1", game_id)
        assert await _journal(conn, turn_id) == []
        async with uow(conn, turn_id):
            await conn.execute(
                "UPDATE games SET current_cycle = current_cycle + 1 WHERE id = $1",
                game_id,
            )
        rows = await _journal(conn, turn_id)

    assert [(r["table_name"], r["op"], r["row_id"]) for r in rows] == [
        ("games", "U", game_id)
    ]
    assert set(rows[0]["old_row"]) == {"current_cycle"}


async def test_write_outside_a_turn_is_not_journaled(test_pool, world):
    game_id, _ = world
    async with test_pool.acquire() as conn:
        before = await _count(conn)
        async with conn.transaction():
            char_id = await conn.fetchval(
                "INSERT INTO characters (game_id, name) VALUES ($1, 'Horstour') RETURNING id",
                game_id,
            )
            await conn.execute(
                "UPDATE characters SET mood = 'las' WHERE id = $1", char_id
            )
            await conn.execute(
                "UPDATE games SET current_cycle = current_cycle + 1 WHERE id = $1",
                game_id,
            )
            await conn.execute("DELETE FROM characters WHERE id = $1", char_id)
        assert await _count(conn) == before


async def test_journal_is_attached_to_every_world_table(test_pool):
    async with test_pool.acquire() as conn:
        with_game_id = {
            r["table_name"]
            for r in await conn.fetch(
                """SELECT c.table_name FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = 'public' AND c.column_name = 'game_id'
              AND t.table_type = 'BASE TABLE'"""
            )
        }
        triggers: dict[str, set[str]] = {}
        for r in await conn.fetch(
            """SELECT event_object_table, trigger_name FROM information_schema.triggers
                WHERE trigger_schema = 'public' AND trigger_name LIKE 'zz_journal_%'"""
        ):
            triggers.setdefault(r["event_object_table"], set()).add(r["trigger_name"])

    expected = (with_game_id - NOT_JOURNALED) | PIVOTS | {"games"}
    assert PIVOTS.isdisjoint(with_game_id)
    assert set(triggers) == expected
    for table in expected:
        assert triggers[table] == {"zz_journal_id", "zz_journal_u"}, table


async def test_deleting_the_turn_drops_its_journal_and_logs_and_keeps_its_rows(
    test_pool, world
):
    """Journal and extraction logs go with the turn (CASCADE); the message and the roll
    stay, with turn_id NULL (SET NULL)."""
    game_id, turn_id = world
    state = NarrationState(cycle=1, time="", location=None, npcs_present=[], date=None)
    async with test_pool.acquire() as conn:
        user_id, _ = await turns.save_turn_messages(
            conn,
            game_id,
            user_message="Je pars.",
            assistant_message="Tu pars.",
            state=state,
            narrator_deltas={},
            engine_snapshot=None,
            turn_id=None,
        )
        await conn.execute(
            "UPDATE messages SET turn_id = $1 WHERE id = $2", turn_id, user_id
        )
        log_id = await conn.fetchval(
            """INSERT INTO extraction_logs (game_id, type, turn_id)
            VALUES ($1, 'extraction', $2) RETURNING id""",
            game_id,
            turn_id,
        )
        roll_id = await conn.fetchval(
            """INSERT INTO mechanic_rolls (game_id, engine, roll_details, outcome, turn_id)
            VALUES ($1, 'fate_core', '{}'::jsonb, 'success', $2) RETURNING id""",
            game_id,
            turn_id,
        )
        async with uow(conn, turn_id):
            await conn.execute(
                "INSERT INTO characters (game_id, name) VALUES ($1, 'Effacé')", game_id
            )
        assert await _journal(conn, turn_id)

        assert await turns.delete_turns(conn, game_id, [turn_id]) == 1

        assert await _journal(conn, turn_id) == []
        assert (
            await conn.fetchval("SELECT turn_id FROM messages WHERE id = $1", user_id)
            is None
        )
        assert await conn.fetchval("SELECT 1 FROM messages WHERE id = $1", user_id) == 1
        assert (
            await conn.fetchval("SELECT 1 FROM extraction_logs WHERE id = $1", log_id)
            is None
        )
        roll = await conn.fetchrow(
            "SELECT turn_id FROM mechanic_rolls WHERE id = $1", roll_id
        )
        assert roll is not None
        assert roll["turn_id"] is None


async def test_delete_turns_purges_open_turns_of_the_game(test_pool, test_user, world):
    from services.game_service import GameService

    game_id, listed = world
    other_game = await GameService(test_pool).create_game(test_user["id"])
    async with test_pool.acquire() as conn:
        stale_open = await turns.open_turn(conn, game_id)
        committed = await turns.open_turn(conn, game_id)
        await turns.mark_committed(conn, committed)
        await turns.mark_committed(conn, listed)
        other_open = await turns.open_turn(conn, other_game)
        other_listed = await turns.open_turn(conn, other_game)
        await turns.mark_committed(conn, other_listed)

        # Another game's turns survive, even when listed by mistake.
        assert await turns.delete_turns(conn, game_id, [listed, other_listed]) == 2

        remaining = {
            r["id"]: r["status"]
            for r in await conn.fetch(
                "SELECT id, status FROM turns WHERE game_id = ANY($1)",
                [game_id, other_game],
            )
        }
    assert remaining == {
        committed: "committed",
        other_open: "open",
        other_listed: "committed",
    }
    assert stale_open not in remaining


async def test_director_commitments_insert_is_journaled(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        async with uow(conn, turn_id):
            row_id = await conn.fetchval(
                """INSERT INTO director_commitments (game_id, kind, text)
                VALUES ($1, 'clock', 'The tide rises') RETURNING id""",
                game_id,
            )
        rows = [
            r
            for r in await _journal(conn, turn_id)
            if r["table_name"] == "director_commitments"
        ]
    assert [(r["row_id"], r["op"]) for r in rows] == [(row_id, "I")]
