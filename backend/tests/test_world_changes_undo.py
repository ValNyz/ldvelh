"""world_changes_undo (#22): the inverse replay of turns' journal (#105) puts the world
back exactly as it was before the turns, without journaling itself."""

from uuid import UUID

import asyncpg
import pytest

from kg.populator import KnowledgeGraphPopulator
from repos import turns
from repos.uow import uow
from tests.test_game_and_populator import _setup_game_with_world

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(client, test_user, test_pool):
    """(game_id, turn_id): a populated game and one open turn."""
    game_id, _, _ = await _setup_game_with_world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game_id)
    return game_id, turn_id


async def _undo(conn, *turn_ids: UUID) -> int:
    return await conn.fetchval("SELECT world_changes_undo($1::uuid[])", list(turn_ids))


async def _journaled_tables(conn) -> list[str]:
    return [
        r["t"]
        for r in await conn.fetch(
            """SELECT tgrelid::regclass::text AS t FROM pg_trigger
            WHERE tgname = 'zz_journal_id' ORDER BY 1"""
        )
    ]


async def _world(conn) -> dict[str, list[str]]:
    """Every row of every journaled table, as sorted JSON text."""
    out = {}
    for table in await _journaled_tables(conn):
        rows = await conn.fetch(f"SELECT to_jsonb(t)::text AS j FROM {table} t")
        out[table] = sorted(r["j"] for r in rows)
    return out


async def _registry_names(conn, game_id: UUID, entity_type: str = "character") -> set:
    rows = await conn.fetch(
        "SELECT name FROM entity_registry WHERE game_id = $1 AND entity_type = $2",
        game_id,
        entity_type,
    )
    return {r["name"] for r in rows}


async def _new_character(conn, game_id: UUID, name: str) -> UUID:
    return await conn.fetchval(
        "INSERT INTO characters (game_id, true_name, mood, occupation) "
        "VALUES ($1, $2, 'calme', 'docker') RETURNING id",
        game_id,
        name,
    )


async def _registry_id(conn, game_id: UUID, name: str) -> UUID:
    return await conn.fetchval(
        "SELECT id FROM entity_registry WHERE game_id = $1 AND name = $2", game_id, name
    )


async def test_undo_removes_inserted_rows_and_their_registry_entry(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        async with uow(conn, turn_id):
            await _new_character(conn, game_id, "Nouveau")
        replayed = await _undo(conn, turn_id)
        chars = await conn.fetchval(
            "SELECT count(*) FROM characters WHERE game_id = $1 AND name = 'Nouveau'",
            game_id,
        )
        assert "Nouveau" not in await _registry_names(conn, game_id)
    assert chars == 0
    assert replayed == 3  # the character, its registry row and the alias of its name


async def test_undo_restores_updated_columns_only(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        char_id = await _new_character(conn, game_id, "Humeur")
        async with uow(conn, turn_id):
            await conn.execute(
                "UPDATE characters SET mood = 'furieux', occupation = 'pilote' WHERE id = $1",
                char_id,
            )
        await conn.execute(
            "UPDATE characters SET description = 'x' WHERE id = $1", char_id
        )
        await _undo(conn, turn_id)
        row = await conn.fetchrow(
            "SELECT mood, occupation, description FROM characters WHERE id = $1",
            char_id,
        )
    assert dict(row) == {"mood": "calme", "occupation": "docker", "description": "x"}


async def _fact_with_participant(conn, game_id: UUID, name: str) -> UUID:
    char_id = await _new_character(conn, game_id, name)
    return await conn.fetchval(
        "SELECT create_fact($1, 1, 'action', 'Un fait', p_participants => $2::jsonb)",
        game_id,
        [{"entity_id": str(char_id), "role": "actor"}],
    )


async def test_undo_reinserts_a_deleted_fact_with_its_participants(test_pool, world):
    """The cascade journals fact_participants' D after the fact's: replayed newest first,
    the participant comes back before its fact, which only the deferred foreign keys
    allow."""
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        fact_id = await _fact_with_participant(conn, game_id, "Témoin")
        participant = await conn.fetchrow(
            "SELECT * FROM fact_participants WHERE fact_id = $1", fact_id
        )
        before = await _world(conn)
        async with uow(conn, turn_id):
            await conn.execute("DELETE FROM facts WHERE id = $1", fact_id)
        assert (
            await conn.fetchval("SELECT count(*) FROM facts WHERE id = $1", fact_id)
            == 0
        )
        await _undo(conn, turn_id)
        restored = await conn.fetchrow(
            "SELECT * FROM fact_participants WHERE id = $1", participant["id"]
        )
        assert await _world(conn) == before
    assert dict(restored) == dict(participant)


async def test_undo_reinserts_a_child_deleted_before_its_parent(test_pool, world):
    """Two statements, child first: the journal is then in dependency order the other way
    round from a cascade. Both orders must replay."""
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        fact_id = await _fact_with_participant(conn, game_id, "Témoin")
        before = await _world(conn)
        async with uow(conn, turn_id):
            await conn.execute(
                "DELETE FROM fact_participants WHERE fact_id = $1", fact_id
            )
            await conn.execute("DELETE FROM facts WHERE id = $1", fact_id)
        await _undo(conn, turn_id)
        assert await _world(conn) == before


async def test_undo_reverses_a_two_level_cascade(test_pool, world):
    """entity_registry -> narrative_arcs -> arc_participants (and fact_participants): the
    grandchildren are journaled after the children, after the registry row."""
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        await _fact_with_participant(conn, game_id, "Meneur")
        await _new_character(conn, game_id, "Suiveur")
        owner = await _registry_id(conn, game_id, "Meneur")
        arc_id = await conn.fetchval(
            "INSERT INTO narrative_arcs (game_id, title, owner_id, created_cycle) "
            "VALUES ($1, 'Arc', $2, 1) RETURNING id",
            game_id,
            owner,
        )
        await conn.execute(
            "INSERT INTO arc_participants (arc_id, entity_id, role) VALUES ($1, $2, 'ally')",
            arc_id,
            await _registry_id(conn, game_id, "Suiveur"),
        )
        before = await _world(conn)
        async with uow(conn, turn_id):
            await conn.execute("DELETE FROM entity_registry WHERE id = $1", owner)
        tables = [
            r["table_name"]
            for r in await conn.fetch(
                "SELECT table_name FROM world_changes WHERE turn_id = $1 ORDER BY id",
                turn_id,
            )
        ]
        assert tables[0] == "entity_registry"
        assert tables.index("narrative_arcs") < tables.index("arc_participants")
        await _undo(conn, turn_id)
        assert await _world(conn) == before


async def test_undo_restores_a_location_and_the_rows_set_null_by_its_delete(
    test_pool, world
):
    """ON DELETE SET NULL journals the children's U after the location's D; restoring a
    fact's location_id also goes through facts_immutable."""
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        loc_id = await conn.fetchval(
            "INSERT INTO locations (game_id, name) VALUES ($1, 'Quai 9') RETURNING id",
            game_id,
        )
        char_id = await _new_character(conn, game_id, "Docker")
        await conn.execute(
            "UPDATE characters SET workplace_id = $1 WHERE id = $2", loc_id, char_id
        )
        await conn.fetchval(
            "SELECT create_fact($1, 1, 'action', 'Sur le quai', p_location_id => $2)",
            game_id,
            loc_id,
        )
        before = await _world(conn)
        async with uow(conn, turn_id):
            await conn.execute("DELETE FROM locations WHERE id = $1", loc_id)
        await _undo(conn, turn_id)
        assert await _world(conn) == before


async def test_undo_restores_a_deleted_character_and_its_registry_row_once(
    test_pool, world
):
    """Re-inserting the character must not register it again: the journaled registry row
    comes back with its own id, whichever of the two was deleted first."""
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        char_a = await _new_character(conn, game_id, "Effacé")
        char_b = await _new_character(conn, game_id, "Gommé")
        reg_a = await _registry_id(conn, game_id, "Effacé")
        reg_b = await _registry_id(conn, game_id, "Gommé")
        before = await _world(conn)
        async with uow(conn, turn_id):
            await conn.execute("DELETE FROM characters WHERE id = $1", char_a)
            await conn.execute("DELETE FROM entity_registry WHERE id = $1", reg_a)
            await conn.execute("DELETE FROM entity_registry WHERE id = $1", reg_b)
            await conn.execute("DELETE FROM characters WHERE id = $1", char_b)
        await _undo(conn, turn_id)
        assert await _registry_id(conn, game_id, "Effacé") == reg_a
        assert await _registry_id(conn, game_id, "Gommé") == reg_b
        assert await _world(conn) == before


async def test_undo_of_a_rename_restores_the_registry_name(test_pool, world):
    game_id, turn_id = world
    populator = KnowledgeGraphPopulator(None, game_id)
    async with test_pool.acquire() as conn:
        char_id = await _new_character(conn, game_id, "A")
        reg_id = await _registry_id(conn, game_id, "A")
        before = await _world(conn)
        async with uow(conn, turn_id):
            await populator.mark_character_known(conn, "A", real_name="B")
        assert await _registry_id(conn, game_id, "B") == reg_id
        await _undo(conn, turn_id)
        name = await conn.fetchval("SELECT name FROM characters WHERE id = $1", char_id)
        names = await _registry_names(conn, game_id)
        assert await _world(conn) == before
    assert name == "A"
    assert "A" in names
    assert "B" not in names


async def test_undo_restores_credits_only_when_applied(test_pool, world):
    game_id, turn_id = world
    populator = KnowledgeGraphPopulator(None, game_id)
    async with test_pool.acquire() as conn:
        balance = await conn.fetchval(
            "SELECT credits FROM protagonists WHERE game_id = $1", game_id
        )
        async with uow(conn, turn_id):
            applied, _, _ = await populator.credit_transaction(conn, -30, 1)
            refused, _, _ = await populator.credit_transaction(conn, -100000, 1)
        assert (applied, refused) == (True, False)
        await _undo(conn, turn_id)
        after = await conn.fetchval(
            "SELECT credits FROM protagonists WHERE game_id = $1", game_id
        )
    assert after == balance


async def test_undo_is_idempotent(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        fact_id = await _fact_with_participant(conn, game_id, "Témoin")
        char_id = await _new_character(conn, game_id, "Changeant")
        async with uow(conn, turn_id):
            await _new_character(conn, game_id, "Neuf")
            await conn.execute(
                "UPDATE characters SET mood = 'gai' WHERE id = $1", char_id
            )
            await conn.execute("DELETE FROM facts WHERE id = $1", fact_id)
        first = await _undo(conn, turn_id)
        state = await _world(conn)
        second = await _undo(conn, turn_id)
        assert await _world(conn) == state
    assert second == first


async def test_undo_reverses_two_turns_in_order(test_pool, world):
    game_id, t1 = world
    populator = KnowledgeGraphPopulator(None, game_id)
    async with test_pool.acquire() as conn:
        before = await _world(conn)
        t2 = await turns.open_turn(conn, game_id)
        async with uow(conn, t1):
            await _new_character(conn, game_id, "X")
        async with uow(conn, t2):
            await populator.mark_character_known(conn, "X", real_name="Y")
        await _undo(conn, t2, t1)
        assert await _world(conn) == before
        names = await _registry_names(conn, game_id)
        chars = await conn.fetchval(
            "SELECT count(*) FROM characters WHERE game_id = $1 AND name IN ('X', 'Y')",
            game_id,
        )
    assert not names & {"X", "Y"}
    assert chars == 0


async def test_undo_replays_newest_first_whatever_the_array_order(test_pool, world):
    """The same column changed by two turns: only newest first ends on the value from
    before both (oldest first would end on the middle one)."""
    game_id, t1 = world
    async with test_pool.acquire() as conn:
        char_id = await _new_character(conn, game_id, "Lunatique")
        before = await _world(conn)
        t2 = await turns.open_turn(conn, game_id)
        async with uow(conn, t1):
            await conn.execute(
                "UPDATE characters SET mood = 'gai' WHERE id = $1", char_id
            )
        async with uow(conn, t2):
            await conn.execute(
                "UPDATE characters SET mood = 'triste' WHERE id = $1", char_id
            )
        await _undo(conn, t1, t2)
        mood = await conn.fetchval("SELECT mood FROM characters WHERE id = $1", char_id)
        assert await _world(conn) == before
    assert mood == "calme"


async def test_undo_ignores_a_dropped_column(test_pool, world):
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        char_id = await _new_character(conn, game_id, "Fantôme")
        await conn.execute(
            "UPDATE characters SET mood = 'triste' WHERE id = $1", char_id
        )
        await conn.execute(
            """INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row, new_row)
            VALUES ($1, 'characters', $2, 'U', $3::jsonb, $4::jsonb)""",
            turn_id,
            char_id,
            {"mood": "calme", "ghost_col": 1},
            {"mood": "triste", "ghost_col": 2},
        )
        await conn.execute(
            """INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row, new_row)
            VALUES ($1, 'characters', $2, 'U', $3::jsonb, $4::jsonb)""",
            turn_id,
            char_id,
            {"ghost_col": 0},
            {"ghost_col": 1},
        )
        replayed = await _undo(conn, turn_id)
        mood = await conn.fetchval("SELECT mood FROM characters WHERE id = $1", char_id)
    assert mood == "calme"
    assert replayed == 1  # the U with no surviving column is skipped, not counted


async def test_undo_writes_no_journal(test_pool, world):
    """Not even when called inside another turn's unit of work."""
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        fact_id = await _fact_with_participant(conn, game_id, "Témoin")
        async with uow(conn, turn_id):
            await _new_character(conn, game_id, "Trace")
            await conn.execute("DELETE FROM facts WHERE id = $1", fact_id)
        other = await turns.open_turn(conn, game_id)
        journal_sql = "SELECT id FROM world_changes WHERE turn_id = ANY($1) ORDER BY id"
        before = await conn.fetch(journal_sql, [turn_id, other])
        async with uow(conn, other):
            await _undo(conn, turn_id)
        after = await conn.fetch(journal_sql, [turn_id, other])
    assert after == before


async def test_undo_still_enforces_foreign_keys(test_pool, world):
    """The foreign keys are only deferred: a replay leaving a broken reference fails."""
    _, turn_id = world
    async with test_pool.acquire() as conn:
        orphan = {
            "id": "00000000-0000-0000-0000-0000000000f1",
            "fact_id": "00000000-0000-0000-0000-0000000000f2",
            "entity_id": "00000000-0000-0000-0000-0000000000f3",
            "role": "actor",
        }
        await conn.execute(
            """INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row)
            VALUES ($1, 'fact_participants', $2, 'D', $3::jsonb)""",
            turn_id,
            UUID(orphan["id"]),
            orphan,
        )
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await _undo(conn, turn_id)


async def test_undo_skips_rows_of_a_dropped_table(test_pool, world):
    """Whatever the op: the table's rows went with it. Skipped rows are not counted."""
    _, turn_id = world
    async with test_pool.acquire() as conn:
        for op, old_row in (("I", None), ("U", {"x": 1}), ("D", {"id": None, "x": 1})):
            await conn.execute(
                """INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row)
                VALUES ($1, 'ghost_table', gen_random_uuid(), $2, $3::jsonb)""",
                turn_id,
                op,
                old_row,
            )
        assert await _undo(conn, turn_id) == 0


async def test_undo_refuses_a_table_that_is_not_journaled(test_pool, world):
    _, turn_id = world
    async with test_pool.acquire() as conn:
        user = {"id": "00000000-0000-0000-0000-0000000000a1", "email": "x@y"}
        await conn.execute(
            """INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row)
            VALUES ($1, 'users', $2, 'D', $3::jsonb)""",
            turn_id,
            UUID(user["id"]),
            user,
        )
        with pytest.raises(asyncpg.RaiseError, match="users is not a journaled table"):
            await _undo(conn, turn_id)
        assert (
            await conn.fetchval("SELECT count(*) FROM users WHERE email = 'x@y'") == 0
        )


async def _orphan_participant(conn) -> None:
    await conn.execute(
        "INSERT INTO fact_participants (fact_id, entity_id) "
        "VALUES (gen_random_uuid(), gen_random_uuid())"
    )


async def test_foreign_keys_stay_immediate_outside_the_replay(test_pool):
    """DEFERRABLE INITIALLY IMMEDIATE: an orphan still fails at its statement, inside a
    transaction, not at COMMIT."""
    async with test_pool.acquire() as conn, conn.transaction():
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with conn.transaction():
                await _orphan_participant(conn)


async def test_a_failed_undo_leaves_triggers_and_foreign_keys_as_before(
    test_pool, world
):
    """Caught by a savepoint, the failed replay leaves neither ldvelh.replay on (the
    registry trigger fires again) nor the foreign keys deferred."""
    game_id, turn_id = world
    async with test_pool.acquire() as conn:
        orphan = {
            "id": "00000000-0000-0000-0000-0000000000f4",
            "fact_id": "00000000-0000-0000-0000-0000000000f5",
            "entity_id": "00000000-0000-0000-0000-0000000000f6",
        }
        await conn.execute(
            """INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row)
            VALUES ($1, 'fact_participants', $2, 'D', $3::jsonb)""",
            turn_id,
            UUID(orphan["id"]),
            orphan,
        )
        async with conn.transaction():
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                async with conn.transaction():
                    await _undo(conn, turn_id)
            await _new_character(conn, game_id, "Après")
            assert "Après" in await _registry_names(conn, game_id)
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                async with conn.transaction():
                    await _orphan_participant(conn)


async def test_every_foreign_key_the_replay_can_trip_is_deferrable(test_pool):
    """Those of a journaled table, and the NO ACTION ones to a journaled table; INITIALLY
    IMMEDIATE, so normal writes still fail at the statement, not at COMMIT."""
    async with test_pool.acquire() as conn:
        rigid = await conn.fetch(
            """SELECT c.conname FROM pg_constraint c
            WHERE c.contype = 'f' AND (NOT c.condeferrable OR c.condeferred)
              AND EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgname = 'zz_journal_id'
                            AND (t.tgrelid = c.conrelid
                                 OR (t.tgrelid = c.confrelid AND c.confdeltype = 'a')))"""
        )
    assert [r["conname"] for r in rigid] == []


async def test_every_side_effect_trigger_of_a_journaled_table_skips_the_replay(
    test_pool,
):
    """Their effects are journaled: the replay restores them from the journal. Each one
    starts by returning when ldvelh.replay is on."""
    async with test_pool.acquire() as conn:
        loud = await conn.fetch(
            """SELECT t.tgname FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE NOT t.tgisinternal AND t.tgname NOT LIKE 'zz_journal_%'
              AND t.tgrelid IN (SELECT tgrelid FROM pg_trigger
                                 WHERE tgname = 'zz_journal_id')
              AND p.prosrc !~ $1""",
            r"IF current_setting\('ldvelh\.replay', true\) = 'on' THEN\s+RETURN NEW;",
        )
    assert [r["tgname"] for r in loud] == []
