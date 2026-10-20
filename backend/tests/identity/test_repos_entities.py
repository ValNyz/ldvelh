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


async def _named(conn, table: str, game_id: UUID, name: str) -> UUID:
    return await conn.fetchval(
        f"INSERT INTO {table} (game_id, name) VALUES ($1, $2) RETURNING id",
        game_id,
        name,
    )


async def _alias(conn, game_id: UUID, entity_id: UUID, entity_type: str, alias: str):
    await entities.insert_alias(
        conn,
        game_id,
        entity_id,
        entity_type,
        alias,
        "short",
        known=True,
        source="extractor",
    )


async def test_find_any_needs_exactly_one_type_and_one_candidate(test_pool, game):
    async with test_pool.acquire() as conn:
        bureau_loc = await _named(conn, "locations", game, "Bureau des Résidences")
        bureau_org = await _named(conn, "organizations", game, "Bureau des Résidences")
        ana = await _character(conn, game, true_name="Ana", descriptor="Garde du sas")
        await _character(conn, game, true_name="Bo", descriptor="Garde du sas")
        await _named(conn, "locations", game, "Garde du sas")
        pc = await _named(conn, "protagonists", game, "Rafe")
        ana_handle = await entities.handle_of(conn, ana)
        results = {
            "cross-type homonym": await entities.find_any(
                conn, game, "le Bureau des Résidences"
            ),
            "typed location": await entities.find_entity(
                conn, game, "Bureau des Résidences", "location"
            ),
            "typed organization": await entities.find_entity(
                conn, game, "Bureau des Résidences", "organization"
            ),
            # Ambiguous among characters: never falls through to the location.
            "ambiguous in a type": await entities.find_any(
                conn, game, "le garde du sas"
            ),
            "unique": await entities.find_any(conn, game, "ana"),
            "handle": await entities.find_any(conn, game, f"e{ana_handle}"),
            "token": await entities.find_any(conn, game, " PROTAGONIST "),
            "unknown": await entities.find_any(conn, game, "Personne"),
        }
    assert results == {
        "cross-type homonym": None,
        "typed location": bureau_loc,
        "typed organization": bureau_org,
        "ambiguous in a type": None,
        "unique": (ana, "character"),
        "handle": (ana, "character"),
        "token": (pc, "protagonist"),
        "unknown": None,
    }


async def test_find_for_upsert_branches(test_pool, game):
    async with test_pool.acquire() as conn:
        hangar = await _named(conn, "locations", game, "Hangar")
        other = await _named(conn, "locations", game, "Quai 9")
        await _alias(conn, game, other, "location", "Hangar")
        dock_a = await _named(conn, "locations", game, "Dock Est")
        dock_b = await _named(conn, "locations", game, "Dock Ouest")
        await _alias(conn, game, dock_a, "location", "Dock")
        await _alias(conn, game, dock_b, "location", "Dock")
        tesk = await _character(
            conn, game, true_name="Tesk", descriptor="Le Kethari au tablier"
        )
        targets = {
            "label owner, contested": await entities.find_for_upsert(
                conn, game, "le hangar", "location"
            ),
            "aliases only": await entities.find_for_upsert(
                conn, game, "Dock", "location"
            ),
            "by alias": await entities.find_for_upsert(
                conn, game, "Kethari au tablier", "character"
            ),
            "by label": await entities.find_for_upsert(conn, game, "TESK", "character"),
            "new": await entities.find_for_upsert(conn, game, "Serres", "location"),
        }
    assert targets == {
        "label owner, contested": entities.UpsertTarget(
            hangar, True, False, contested=True
        ),
        "aliases only": entities.UpsertTarget(None, False, True),
        "by alias": entities.UpsertTarget(tesk, False, False),
        "by label": entities.UpsertTarget(tesk, True, False),
        "new": entities.UpsertTarget(None, False, False),
    }


async def test_an_ambiguous_name_creates_no_location(test_pool, game):
    from kg.populator import KnowledgeGraphPopulator
    from kg.specialized_populator import ExtractionPopulator
    from services.turn_effects import _resolve_location
    from schema import EntityCreation
    from domain.identity import AmbiguousLabel

    async with test_pool.acquire() as conn:
        for name in ("Dock Est", "Dock Ouest"):
            await _alias(
                conn,
                game,
                await _named(conn, "locations", game, name),
                "location",
                "Dock",
            )
        with pytest.raises(AmbiguousLabel):
            await ExtractionPopulator(None, game).create_extracted_entity(
                conn, [], EntityCreation(entity_type="location", name="Dock"), 1
            )
        stub = await _resolve_location(
            conn, KnowledgeGraphPopulator(None, game), "le Dock", 2
        )
        count = await conn.fetchval(
            "SELECT count(*) FROM locations WHERE game_id = $1", game
        )
    assert (stub, count) == (None, 2)


async def test_a_contested_character_name_leaves_the_label_holder_untouched(
    test_pool, game
):
    """The old code skipped a name matching another character's descriptor: the holder of
    the label is not rewritten with data that may describe the other one."""
    from kg.specialized_populator import ExtractionPopulator
    from schema import EntityCreation

    async with test_pool.acquire() as conn:
        holder = await _character(conn, game, true_name="Marek", mood="calme")
        other = await _character(conn, game, true_name="Ilya")
        await _alias(conn, game, other, "character", "Marek")
        result = await ExtractionPopulator(None, game).create_extracted_entity(
            conn,
            [],
            EntityCreation(
                entity_type="character", name="Marek", data={"mood": "furieux"}
            ),
            1,
        )
        mood = await conn.fetchval("SELECT mood FROM characters WHERE id = $1", holder)
        count = await conn.fetchval(
            "SELECT count(*) FROM characters WHERE game_id = $1", game
        )
    assert (result, mood, count) == (holder, "calme", 2)


async def test_a_reveal_never_deletes_through_another_characters_alias(test_pool, game):
    """A revealed name that is only another character's descriptor designates no other
    entity (spec §4.7: labels, true-name and label aliases): nothing is merged nor
    deleted, the other character is untouched."""
    from services.identity.service import IdentityService
    from domain.identity import EntityRef

    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        tesk = await _character(
            conn, game, true_name="Tesk", descriptor="Le Kethari au tablier"
        )
        identity = await IdentityService.for_game(conn, game)
        revealed = await identity.reveal(
            conn,
            EntityRef("la Kethari âgée", "character"),
            "Kethari au tablier",
            turn_id=None,
            source="reveal",
        )
        rows = await conn.fetch(
            "SELECT id, known_by_protagonist, true_name FROM characters WHERE game_id = $1"
            " ORDER BY created_at",
            game,
        )
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
    assert revealed.kind == "applied"
    assert merges == 0
    assert [tuple(r) for r in rows] == [
        (elder, True, "Kethari au tablier"),
        (tesk, False, "Tesk"),
    ]


async def test_a_descriptive_extracted_name_is_never_a_true_name(test_pool, game):
    from kg.specialized_populator import ExtractionPopulator
    from schema import EntityCreation

    async with test_pool.acquire() as conn:
        guard = await ExtractionPopulator(None, game).create_extracted_entity(
            conn,
            [],
            EntityCreation(
                entity_type="character", name="Le garde", descriptor="Garde en armure"
            ),
            1,
        )
        row = await conn.fetchrow(
            "SELECT true_name, descriptor FROM characters WHERE id = $1", guard
        )
        kinds = {
            a.alias: (a.kind, a.known)
            for a in await entities.list_aliases(conn, game, guard)
        }
        by_name = await entities.find_entity(conn, game, "le garde", "character")
    assert tuple(row) == (None, "Garde en armure")
    assert kinds == {
        "Garde en armure": ("descriptor", True),
        "Le garde": ("descriptor", True),
    }
    assert by_name == guard


async def test_a_reveal_without_real_name_marks_the_true_name_alias_known(
    test_pool, game
):
    from services.identity.service import IdentityService
    from domain.identity import EntityRef

    async with test_pool.acquire() as conn:
        tesk = await _character(
            conn, game, true_name="Tesk", descriptor="Le Kethari au tablier"
        )
        identity = await IdentityService.for_game(conn, game)
        revealed = await identity.reveal(
            conn,
            EntityRef("le Kethari au tablier", "character"),
            None,
            turn_id=None,
            source="reveal",
        )
        assert revealed.kind == "known_only"
        kinds = {
            a.alias: a.known for a in await entities.list_aliases(conn, game, tesk)
        }
    assert kinds == {"Tesk": True, "Le Kethari au tablier": True}


async def test_an_extractor_descriptor_alias_carries_its_turn(test_pool, game):
    from kg.specialized_populator import ExtractionPopulator
    from schema import EntityCreation

    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            guard = await ExtractionPopulator(None, game).create_extracted_entity(
                conn,
                [],
                EntityCreation(
                    entity_type="character",
                    name="Le garde",
                    descriptor="Garde en armure",
                ),
                1,
            )
        aliases = {
            a.alias: (a.source, a.turn_id)
            for a in await entities.list_aliases(conn, game, guard)
        }
    assert aliases == {
        "Garde en armure": ("system", turn_id),
        "Le garde": ("extractor", turn_id),
    }
