"""Undo of identity writes (#153, spec §5.4): reveals, merges, learned aliases and mentions
written in a turn's unit of work are undone by the turn's journal (world_changes_undo),
with no other path."""

import json
from uuid import UUID

import pytest

from config import get_identity_config
from repos import entities, turns
from repos.uow import uow
from services.identity.service import IdentityService
from domain.identity import EntityRef, MentionRow

pytestmark = pytest.mark.integration

# Tables an identity write touches, read for one game.
_GAME_TABLES = (
    "characters",
    "entity_registry",
    "entity_aliases",
    "entity_mentions",
    "entity_merges",
    "relations",
    "skills",
)
# Engine rows of an entity (no game_id: read through the entity's registry row, which a
# merge keeps as a tombstone), by the column naming the entity.
_ENGINE_TABLES = (
    ("npc_fate", "character_id"),
    ("npc_d6", "character_id"),
    ("npc_narrative", "character_id"),
    ("object_fate", "object_id"),
    ("object_d6", "object_id"),
    ("object_narrative", "object_id"),
)


@pytest.fixture
async def game(test_pool, test_user) -> UUID:
    async with test_pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
            test_user["id"],
        )


@pytest.fixture
def service(game) -> IdentityService:
    return IdentityService(game, lang="fr", config=get_identity_config())


async def _character(conn, game_id: UUID, **fields) -> UUID:
    cols = ", ".join(["game_id", *fields])
    marks = ", ".join(f"${i}" for i in range(1, len(fields) + 2))
    return await conn.fetchval(
        f"INSERT INTO characters ({cols}) VALUES ({marks}) RETURNING id",
        game_id,
        *fields.values(),
    )


async def _undo(conn, turn_id: UUID) -> int:
    return await conn.fetchval("SELECT world_changes_undo($1::uuid[])", [turn_id])


async def _state(conn, game_id: UUID) -> dict[str, list[str]]:
    """Every row of the game in the tables identity writes touch, plus its fact
    participants, as sorted JSON text."""
    out = {}
    for table in _GAME_TABLES:
        rows = await conn.fetch(
            f"SELECT to_jsonb(t)::text AS j FROM {table} AS t WHERE t.game_id = $1",
            game_id,
        )
        out[table] = sorted(r["j"] for r in rows)
    rows = await conn.fetch(
        """SELECT to_jsonb(fp)::text AS j FROM fact_participants AS fp
           JOIN facts AS ft ON ft.id = fp.fact_id WHERE ft.game_id = $1""",
        game_id,
    )
    out["fact_participants"] = sorted(r["j"] for r in rows)
    for table, column in _ENGINE_TABLES:
        rows = await conn.fetch(
            f"""SELECT to_jsonb(t)::text AS j FROM {table} AS t
                JOIN entity_registry AS er ON er.id = t.{column}
                WHERE er.game_id = $1""",
            game_id,
        )
        out[table] = sorted(r["j"] for r in rows)
    return out


async def _message(conn, game_id: UUID) -> UUID:
    conversation = await conn.fetchval(
        "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, 1) RETURNING id",
        game_id,
    )
    return await conn.fetchval(
        """INSERT INTO messages (game_id, conversation_id, role, content, sequence)
           VALUES ($1, $2, 'assistant', 'Nahle sourit au docker.', 1) RETURNING id""",
        game_id,
        conversation,
    )


async def test_undo_of_a_reveal_restores_descriptor_and_aliases(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        turn_id = await turns.open_turn(conn, game)
        before = await _state(conn, game)
        async with uow(conn, turn_id):
            outcome = await service.reveal(
                conn,
                EntityRef("La Kethari âgée", "character"),
                "Nahle Irun-Sa",
                turn_id=turn_id,
                source="reveal",
            )
        revealed = await conn.fetchval(
            "SELECT true_name FROM characters WHERE id = $1", elder
        )
        await _undo(conn, turn_id)
        after = await _state(conn, game)
        row = await conn.fetchrow(
            "SELECT true_name, descriptor, known_by_protagonist FROM characters"
            " WHERE id = $1",
            elder,
        )
        aliases = {a.alias for a in await entities.list_aliases(conn, game, elder)}
    assert (outcome.kind, revealed) == ("applied", "Nahle Irun-Sa")
    assert after == before
    assert tuple(row) == (None, "La Kethari âgée", False)
    assert aliases == {"La Kethari âgée"}


async def test_undo_of_a_merge_restores_both_entities_and_their_edges(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        nahle = await _character(conn, game, true_name="Nahle Irun-Sa")
        tesk = await _character(conn, game, true_name="Tesk Vahrun")
        for source, target, kind in (
            (elder, tesk, "knows"),
            (nahle, tesk, "knows"),
            (tesk, nahle, "enemy_of"),
        ):
            await conn.execute(
                """INSERT INTO relations (game_id, type, source_id, target_id, start_cycle)
                   VALUES ($1, $2::relation_type, $3, $4, 1)""",
                game,
                kind,
                source,
                target,
            )
        await conn.fetchval(
            "SELECT create_fact($1, 1, 'action', 'Un fait', p_participants => $2::jsonb)",
            game,
            [{"entity_id": str(nahle), "role": "actor"}],
        )
        turn_id = await turns.open_turn(conn, game)
        before = await _state(conn, game)
        async with uow(conn, turn_id):
            outcome = await service.merge(
                conn, elder, nahle, reason="test", turn_id=turn_id
            )
        merged = await _state(conn, game)
        await _undo(conn, turn_id)
        after = await _state(conn, game)
        tombstone = await conn.fetchval(
            "SELECT merged_into FROM entity_registry WHERE id = $1", nahle
        )
    assert outcome.merge_id is not None and outcome.refused is None
    assert merged != before
    assert len(merged["entity_merges"]) == 1
    assert after == before
    assert tombstone is None


async def test_undo_of_a_turn_removes_its_mentions_and_learned_aliases(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        nahle = await _character(conn, game, true_name="Nahle Irun-Sa")
        message = await _message(conn, game)
        turn_id = await turns.open_turn(conn, game)
        before = await _state(conn, game)
        async with uow(conn, turn_id):
            learned = await service.add_alias(
                conn, nahle, "la marchande", "nickname", known=True, source="resolver"
            )
            written = await entities.insert_mentions(
                conn,
                game,
                message,
                turn_id,
                [MentionRow(0, 5, "Nahle", nahle, "alias")],
            )
        await _undo(conn, turn_id)
        after = await _state(conn, game)
        mentions = await entities.mentions_for_messages(conn, game, [message])
    assert (learned, written) == (True, 1)
    assert after == before
    assert mentions == {}


async def test_mentions_of_a_merged_entity_resolve_through_the_tombstone_and_again_directly_after_undo(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        nahle = await _character(conn, game, true_name="Nahle Irun-Sa")
        message = await _message(conn, game)
        await entities.insert_mentions(
            conn,
            game,
            message,
            None,
            [MentionRow(0, 5, "Nahle", nahle, "match")],
        )
        turn_id = await turns.open_turn(conn, game)
        before = await _state(conn, game)
        async with uow(conn, turn_id):
            outcome = await service.reveal(
                conn,
                EntityRef("La Kethari âgée", "character"),
                "Nahle Irun-Sa",
                turn_id=turn_id,
                source="reveal",
            )
        merged = await entities.mentions_for_messages(conn, game, [message])
        stored = await conn.fetchval(
            "SELECT entity_id FROM entity_mentions WHERE message_id = $1", message
        )
        await _undo(conn, turn_id)
        undone = await entities.mentions_for_messages(conn, game, [message])
        after = await _state(conn, game)
    assert after == before
    assert (outcome.kind, outcome.merged_into) == ("merged", elder)
    assert [m.entity_id for m in merged[message]] == [elder]
    assert stored == nahle  # never rewritten: the read follows the tombstone
    assert [m.entity_id for m in undone[message]] == [nahle]


# --- Final review fixes: engine rows and skills follow a merge (I3, M6) -----------------


async def _merge_audit(conn, merge_id: UUID) -> tuple[dict, dict]:
    row = await conn.fetchrow(
        "SELECT moved_edges, dropped_row FROM entity_merges WHERE id = $1", merge_id
    )
    return tuple(
        value if isinstance(value, dict) else json.loads(value)
        for value in (row["moved_edges"], row["dropped_row"])
    )


async def test_a_merge_moves_audits_and_undoes_the_engine_rows_and_skills(
    test_pool, game, service
):
    """I3/M6: drop's engine row moves to keep when keep has none; when both have one,
    keep's wins and drop's is recorded (moved_edges `<table>.dropped`, dropped_row
    `engine`); a skill both have active is closed on drop's side, not duplicated; the
    turn's undo restores every row exactly."""
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        nahle = await _character(conn, game, true_name="Nahle Irun-Sa")
        fates = {}
        for owner, aspect in ((elder, "Vieille routière"), (nahle, "Marchande rusée")):
            fates[owner] = await conn.fetchval(
                "INSERT INTO npc_fate (character_id, aspects) VALUES ($1, $2::jsonb)"
                " RETURNING id",
                owner,
                json.dumps([aspect]),
            )
        d6 = await conn.fetchval(
            "INSERT INTO npc_d6 (character_id, force_points) VALUES ($1, 2) RETURNING id",
            nahle,
        )
        skills = {}
        for owner, name in ((elder, "Pilotage"), (nahle, "pilotage")):
            skills[owner] = await conn.fetchval(
                "INSERT INTO skills (game_id, character_id, name, level)"
                " VALUES ($1, $2, $3, 2) RETURNING id",
                game,
                owner,
                name,
            )
        drop_fate = await conn.fetchval(
            "SELECT to_jsonb(t) FROM npc_fate AS t WHERE id = $1", fates[nahle]
        )
        turn_id = await turns.open_turn(conn, game)
        before = await _state(conn, game)
        async with uow(conn, turn_id):
            outcome = await service.merge(
                conn, elder, nahle, reason="test", turn_id=turn_id
            )
        moved, dropped = await _merge_audit(conn, outcome.merge_id)
        fate_owner = await conn.fetchval(
            "SELECT character_id FROM npc_fate WHERE id = $1", fates[elder]
        )
        d6_owner = await conn.fetchval(
            "SELECT character_id FROM npc_d6 WHERE id = $1", d6
        )
        active = await conn.fetchval(
            "SELECT count(*) FROM skills WHERE character_id = $1 AND end_cycle IS NULL",
            elder,
        )
        await _undo(conn, turn_id)
        after = await _state(conn, game)
    drop_fate = drop_fate if isinstance(drop_fate, dict) else json.loads(drop_fate)
    assert (fate_owner, d6_owner, active) == (elder, elder, 1)
    assert moved["npc_fate.dropped"] == [str(fates[nahle])]
    assert moved["npc_d6.character_id"] == [str(d6)]
    assert moved["skills.closed"] == [str(skills[nahle])]
    assert dropped["engine"] == {"npc_fate": drop_fate}
    assert after == before


async def test_a_merge_of_objects_audits_and_undoes_their_engine_rows(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        keep, drop = [
            await conn.fetchval(
                "INSERT INTO objects (game_id, name) VALUES ($1, $2) RETURNING id",
                game,
                name,
            )
            for name in ("Clé à molette", "Grosse clé")
        ]
        for owner, kind in ((keep, "outil"), (drop, "arme")):
            await conn.execute(
                "INSERT INTO object_fate (object_id, item_type) VALUES ($1, $2)",
                owner,
                kind,
            )
        narrative = await conn.fetchval(
            "INSERT INTO object_narrative (object_id, narrative_description)"
            " VALUES ($1, 'Rouillée') RETURNING id",
            drop,
        )
        turn_id = await turns.open_turn(conn, game)
        before = await _state(conn, game)
        async with uow(conn, turn_id):
            outcome = await service.merge(conn, keep, drop, reason="t", turn_id=turn_id)
        moved, dropped = await _merge_audit(conn, outcome.merge_id)
        await _undo(conn, turn_id)
        after = await _state(conn, game)
    assert len(moved["object_fate.dropped"]) == 1
    assert moved["object_narrative.object_id"] == [str(narrative)]
    assert dropped["engine"]["object_fate"]["item_type"] == "arme"
    assert after == before
