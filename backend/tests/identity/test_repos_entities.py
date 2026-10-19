"""repos.entities (#152): typed references, aliases, mentions on the live entity, telemetry."""

from uuid import UUID

import pytest

from repos import entities, turns
from repos.uow import uow

pytestmark = pytest.mark.integration


@pytest.fixture
async def game(test_pool, test_user) -> UUID:
    async with test_pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
            test_user["id"],
        )


async def _character(conn, game_id: UUID, **fields) -> UUID:
    cols = ", ".join(["game_id", *fields])
    marks = ", ".join(f"${i}" for i in range(1, len(fields) + 2))
    return await conn.fetchval(
        f"INSERT INTO characters ({cols}) VALUES ({marks}) RETURNING id",
        game_id,
        *fields.values(),
    )


async def _message(conn, game_id: UUID) -> UUID:
    conversation = await conn.fetchval(
        "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, 1) RETURNING id",
        game_id,
    )
    return await conn.fetchval(
        """INSERT INTO messages (game_id, conversation_id, role, content, sequence)
           VALUES ($1, $2, 'assistant', 'La Kethari âgée sourit.', 1) RETURNING id""",
        game_id,
        conversation,
    )


async def test_find_entity_by_handle_alias_and_label(test_pool, game):
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        tesk = await _character(
            conn, game, true_name="Tesk Vahrun-Oo", descriptor="Le Kethari au tablier"
        )
        quay = await conn.fetchval(
            "INSERT INTO locations (game_id, name) VALUES ($1, 'Quai 9') RETURNING id",
            game,
        )
        handle = await entities.handle_of(conn, tesk)
        found = {
            "label, article dropped": await entities.find_entity(
                conn, game, "kethari âgée", "character"
            ),
            "descriptor alias": await entities.find_entity(
                conn, game, "le kethari au tablier", "character"
            ),
            "handle": await entities.find_entity(conn, game, f"E{handle}", "character"),
            "id": await entities.find_entity(conn, game, str(quay), "location"),
            "wrong type": await entities.find_entity(
                conn, game, "Quai 9", "organization"
            ),
            "blank": await entities.find_entity(conn, game, "  ", "character"),
        }
        by_handle = await entities.entity_by_handle(conn, game, handle)
        any_type = await entities.find_any(conn, game, "le quai 9")
        registry = await entities.get_registry(conn, game, tesk)
        with pytest.raises(ValueError):
            await entities.find_entity(conn, game, "Quai 9", "")
    assert found == {
        "label, article dropped": elder,
        "descriptor alias": tesk,
        "handle": tesk,
        "id": quay,
        "wrong type": None,
        "blank": None,
    }
    assert by_handle == tesk
    assert any_type == (quay, "location")
    assert (
        registry.entity_type,
        registry.name,
        registry.handle,
        registry.merged_into,
    ) == ("character", "Tesk Vahrun-Oo", handle, None)


async def test_insert_alias_is_idempotent(test_pool, game):
    async with test_pool.acquire() as conn:
        voss = await _character(
            conn, game, true_name="Elara Voss", known_by_protagonist=True
        )
        first = await entities.insert_alias(
            conn,
            game,
            voss,
            "character",
            "Voss",
            "short",
            known=True,
            source="extractor",
        )
        again = await entities.insert_alias(
            conn,
            game,
            voss,
            "character",
            "voss",
            "short",
            known=True,
            source="extractor",
        )
        aliases = await entities.list_aliases(conn, game, voss)
    assert (first, again) == (True, False)
    assert [(a.alias, a.kind, a.known, a.source) for a in aliases] == [
        ("Elara Voss", "true_name", True, "system"),
        ("Voss", "short", True, "extractor"),
    ]


async def test_mentions_follow_the_tombstone(test_pool, game):
    async with test_pool.acquire() as conn:
        keep = await _character(conn, game, descriptor="La Kethari âgée")
        drop = await _character(conn, game, true_name="Nahle Irun-Sa")
        message = await _message(conn, game)
        written = await entities.insert_mentions(
            conn,
            game,
            message,
            None,
            [
                entities.MentionRow(0, 15, "La Kethari âgée", drop, "match"),
            ],
        )
        await conn.fetchval("SELECT merge_entities($1, $2, 'reveal', NULL)", keep, drop)
        mentions = await entities.mentions_for_messages(conn, game, [message])
        live = await entities.follow_merge(conn, drop)
        label = await entities.display_for_player(conn, drop)
    assert written == 1
    [mention] = mentions[message]
    assert (mention.entity_id, mention.entity_type, mention.surface) == (
        keep,
        "character",
        "La Kethari âgée",
    )
    assert live == keep
    # The PC does not know the true name the kept entity adopted: the descriptor is shown.
    assert mention.label == label == "La Kethari âgée"


async def test_insert_event_is_not_journaled(test_pool, game):
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            await entities.insert_event(
                conn, game, "ambiguous_ref", turn_id=turn_id, payload={"candidates": 2}
            )
        journaled = await conn.fetchval(
            "SELECT count(*) FROM world_changes WHERE table_name = 'identity_events'"
        )
        event = await conn.fetchrow(
            "SELECT kind, turn_id, payload FROM identity_events WHERE game_id = $1",
            game,
        )
    assert journaled == 0
    assert (event["kind"], event["turn_id"], event["payload"]) == (
        "ambiguous_ref",
        turn_id,
        {"candidates": 2},
    )
