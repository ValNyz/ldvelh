"""The knowledge graph written by entity id (#153, spec §4.6 C1-C14, §4.10, §4.11): every
creation goes through IdentityService, every reference is resolved before the write, and
an unresolved one is counted (`ref_dropped`), never dropped silently nor guessed."""

import json
from uuid import UUID

import pytest

from llm.session import LLMSession
from tests.prompt_examples import WORLD_GENERATION_EXAMPLE
from tests.test_llm_session import FakeProvider

pytestmark = pytest.mark.integration


async def _world(test_pool, test_user, edit=None) -> UUID:
    """A game populated from the canonical world example (`edit` changes its data)."""
    from schema import WorldGeneration
    from services.game_service import GameService

    data = json.loads(WORLD_GENERATION_EXAMPLE)
    if edit:
        edit(data)
    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])
    await service.process_init(game_id, WorldGeneration.model_validate(data))
    return game_id


async def _run(extractor_cls, test_pool, game_id, raw_result, cycle=2) -> dict:
    """One extractor through its real write path, answering `raw_result`; its stats."""
    extractor = extractor_cls(
        test_pool, game_id, LLMSession.from_provider(FakeProvider())
    )

    async def fake_call(*_, **__):
        return raw_result, {"cost_usd": 0.0}

    extractor._call_llm = fake_call
    result = await extractor.run("texte", {}, cycle)
    return result["stats"]


async def _events(conn, game_id, kind) -> list[dict]:
    rows = await conn.fetch(
        "SELECT payload FROM identity_events WHERE game_id = $1 AND kind = $2",
        game_id,
        kind,
    )
    return [
        json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
        for r in rows
    ]


def _fact(*refs, key="pnj:parle:quai"):
    return {
        "fact_type": "dialogue",
        "description": "Une conversation sur le quai",
        "semantic_key": key,
        "importance": 3,
        "participants": [{"entity_ref": ref, "role": "actor"} for ref in refs],
    }


async def test_unresolved_fact_participant_is_counted_not_dropped_silently(
    test_pool, test_user
):
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    stats = await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {"facts": [_fact("PROTAGONIST", "Personne Inconnue")]},
    )
    async with test_pool.acquire() as conn:
        facts = await conn.fetchval(
            "SELECT count(*) FROM facts WHERE game_id = $1 AND semantic_key = $2",
            game_id,
            "pnj:parle:quai",
        )
        dropped = await _events(conn, game_id, "ref_dropped")
    assert stats["errors"] == [{"code": "ref_dropped", "item": "fact"}]
    assert stats["facts_created"] == 0
    # Never written without the participant it names.
    assert facts == 0
    assert dropped == [{"item": "fact", "entity_type": "any", "candidates": 0}]


async def test_unresolved_relation_end_is_an_error(test_pool, test_user):
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    game_id = await _world(test_pool, test_user)
    async with test_pool.acquire() as conn:
        before = await conn.fetchval(
            "SELECT count(*) FROM relations WHERE game_id = $1", game_id
        )
    stats = await _run(
        NarrativeArcsExtractor,
        test_pool,
        game_id,
        {
            "relations_created": [
                {
                    "cycle": 2,
                    "relation": {
                        "source_ref": "Ossek",
                        "target_ref": "Personne Inconnue",
                        "relation_type": "knows",
                        "level": 3,
                    },
                }
            ],
            "relations_ended": [
                {
                    "source_ref": "Personne Inconnue",
                    "target_ref": "Ossek",
                    "relation_type": "knows",
                    "cycle": 2,
                }
            ],
        },
    )
    async with test_pool.acquire() as conn:
        after = await conn.fetchval(
            "SELECT count(*) FROM relations WHERE game_id = $1", game_id
        )
        dropped = await _events(conn, game_id, "ref_dropped")
    assert stats["errors"] == [
        {"code": "ref_dropped", "item": "rel_create"},
        {"code": "ref_dropped", "item": "rel_end"},
    ]
    assert (stats["relations_created"], stats["relations_ended"]) == (0, 0)
    assert after == before
    assert sorted(d["item"] for d in dropped) == ["rel_create", "rel_end"]


async def test_companion_can_be_a_fact_participant(test_pool, test_user):
    """F17: the companion is in the registry, so a fact or a relation can name it (by its
    name or the reserved COMPANION)."""
    from services.extraction.characters import CharactersExtractor
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    game_id = await _world(test_pool, test_user)
    stats = await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {"facts": [_fact("Célimène", "PROTAGONIST", key="ia:conseille:pc")]},
    )
    rel = await _run(
        NarrativeArcsExtractor,
        test_pool,
        game_id,
        {
            "relations_created": [
                {
                    "cycle": 2,
                    "relation": {
                        "source_ref": "COMPANION",
                        "target_ref": "Ossek",
                        "relation_type": "knows",
                        "level": 2,
                    },
                }
            ]
        },
    )
    async with test_pool.acquire() as conn:
        types = await conn.fetch(
            """SELECT er.entity_type FROM fact_participants fp
               JOIN facts f ON f.id = fp.fact_id
               JOIN entity_registry er ON er.id = fp.entity_id
               WHERE f.game_id = $1 AND f.semantic_key = $2""",
            game_id,
            "ia:conseille:pc",
        )
        companion_relations = await conn.fetchval(
            """SELECT count(*) FROM relations r
               JOIN entity_registry er ON er.id = r.source_id
               WHERE r.game_id = $1 AND er.entity_type = 'companion'""",
            game_id,
        )
    assert (stats["errors"], rel["errors"]) == ([], [])
    assert sorted(r["entity_type"] for r in types) == ["companion", "protagonist"]
    assert companion_relations == 1


async def test_world_gen_registers_every_entity_with_true_name_and_descriptor(
    test_pool, test_user
):
    from repos import entities

    def describe(data):
        data["characters"][0]["descriptor"] = "la femme au manteau gris"

    game_id = await _world(test_pool, test_user, describe)
    data = json.loads(WORLD_GENERATION_EXAMPLE)
    async with test_pool.acquire() as conn:
        registry = {
            (r["entity_type"], r["name"])
            for r in await conn.fetch(
                "SELECT entity_type, identity_bare_label(id) AS name FROM entity_registry"
                " WHERE game_id = $1 AND merged_into IS NULL",
                game_id,
            )
        }
        justine = await conn.fetchrow(
            "SELECT id, true_name, descriptor, known_by_protagonist FROM characters"
            " WHERE game_id = $1 AND true_name = $2",
            game_id,
            "Justine Lépicier",
        )
        aliases = {
            (a.alias, a.kind, a.source)
            for a in await entities.list_aliases(conn, game_id, justine["id"])
        }
        by_descriptor = await entities.find_entity(
            conn, game_id, "la femme au manteau gris", "character"
        )
        log = await conn.fetchrow(
            "SELECT entities_modified, errors FROM extraction_logs"
            " WHERE game_id = $1 AND cycle = 0",
            game_id,
        )
        station = await conn.fetchrow(
            "SELECT parent_id, location_type FROM locations WHERE game_id = $1 AND name = $2",
            game_id,
            data["world"]["name"],
        )
        parents = {
            r["name"]: r["parent"]
            for r in await conn.fetch(
                """SELECT l.name, p.name AS parent FROM locations l
                   LEFT JOIN locations p ON p.id = l.parent_id WHERE l.game_id = $1""",
                game_id,
            )
        }
        seats = {
            r["name"]: r["seat"]
            for r in await conn.fetch(
                """SELECT o.name, l.name AS seat FROM organizations o
                   LEFT JOIN locations l ON l.id = o.headquarters_id WHERE o.game_id = $1""",
                game_id,
            )
        }
        secret = await conn.fetchval(
            "SELECT count(*) FROM entity_aliases WHERE game_id = $1 AND secret", game_id
        )
    expected = {
        ("location", data["world"]["name"]),
        ("protagonist", data["protagonist"]["name"]),
        ("companion", data["companion"]["name"]),
    }
    expected |= {("character", c["name"]) for c in data["characters"]}
    expected |= {("location", loc["name"]) for loc in data["locations"]}
    expected |= {("organization", o["name"]) for o in data["organizations"]}
    expected |= {("object", o["name"]) for o in data["inventory"]}
    assert registry == expected
    assert (
        justine["true_name"],
        justine["descriptor"],
        justine["known_by_protagonist"],
    ) == ("Justine Lépicier", "la femme au manteau gris", False)
    # The derived aliases of the true name, written by the world generation.
    assert {
        ("Lépicier", "short", "world_gen"),
        ("Justine", "short", "world_gen"),
    } <= aliases
    assert by_descriptor == justine["id"]
    assert log["entities_modified"] == len(expected)
    # The station is the root location; parents and seats are linked by id.
    assert tuple(station) == (None, "station")
    for loc in data["locations"]:
        assert parents[loc["name"]] == loc.get("parent_location_ref"), loc["name"]
    for org in data["organizations"]:
        assert seats[org["name"]] == org.get("headquarters_ref"), org["name"]
    assert secret == 0
    errors = log["errors"]
    assert (json.loads(errors) if isinstance(errors, str) else errors) == []


async def test_seen_object_is_not_added_to_inventory_unless_acquired(
    test_pool, test_user
):
    """F18: an object an extractor lists in entities_created exists, but only `acquired`
    puts it in the inventory. No extractor routes an object through entities_created (the
    inventory extractor only has objects_created, which are acquired), so the routing
    entry point is called directly."""
    from kg.specialized_populator import ExtractionPopulator
    from schema import EntityCreation
    from services.extraction.inventory import InventoryExtractor

    game_id = await _world(test_pool, test_user)
    populator = ExtractionPopulator(test_pool, game_id)

    async def owned(conn):
        return await conn.fetchval(
            """SELECT count(*) FROM inventory i JOIN objects o ON o.id = i.object_id
               WHERE i.game_id = $1 AND o.name = 'Clé à molette'""",
            game_id,
        )

    async with test_pool.acquire() as conn:
        seen = await populator.create_extracted_entity(
            conn, [], EntityCreation(entity_type="object", name="Clé à molette"), 2
        )
        assert seen is not None
        assert await owned(conn) == 0
    stats = await _run(
        InventoryExtractor,
        test_pool,
        game_id,
        {
            "inventory_changes": [
                {
                    "action": "acquire",
                    "object_ref": "Clé à molette",
                    "quantity_delta": 1,
                }
            ]
        },
    )
    async with test_pool.acquire() as conn:
        assert await owned(conn) == 1
    assert stats["errors"] == []


async def test_extractor_update_by_descriptor_hits_the_entity(test_pool, test_user):
    """F12: an update naming a character by its descriptor writes that character."""
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    created = await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {
            "entities_created": [
                {
                    "name": "Mara Ilen",
                    "descriptor": "la docker balafrée",
                    "data": {"mood": "calme"},
                }
            ]
        },
    )
    async with test_pool.acquire() as conn:
        created_at = await conn.fetchval(
            "SELECT updated_at FROM characters WHERE game_id = $1 AND descriptor = $2",
            game_id,
            "la docker balafrée",
        )
    updated = await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {
            "entities_updated": [
                {"entity_ref": "La docker balafrée", "changes": {"mood": "furieuse"}}
            ]
        },
        cycle=3,
    )
    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT true_name, mood, known_by_protagonist FROM characters"
            " WHERE game_id = $1 AND descriptor = $2",
            game_id,
            "la docker balafrée",
        )
        updated_at = await conn.fetchval(
            "SELECT updated_at FROM characters WHERE game_id = $1 AND descriptor = $2",
            game_id,
            "la docker balafrée",
        )
    # The update dates the row (M1).
    assert updated_at > created_at
    assert (created["errors"], updated["errors"]) == ([], [])
    assert updated["entities_updated"] == 1
    assert tuple(row) == ("Mara Ilen", "furieuse", False)


async def test_stale_cache_cannot_drop_reveal_fact_participants(test_pool, test_user):
    """F11: a reveal and a fact naming the revealed name, in the same run: the fact's
    participant is the revealed character (resolution reads the transaction, no cache)."""
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {
            "entities_created": [
                {"name": "La Kethari âgée", "known_by_protagonist": False}
            ]
        },
    )
    stats = await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {
            "entities_updated": [
                {
                    "entity_ref": "la Kethari âgée",
                    "now_known": True,
                    "real_name": "Nahle Irun-Sa",
                }
            ],
            "facts": [_fact("Nahle Irun-Sa", key="nahle:se:presente")],
        },
        cycle=3,
    )
    async with test_pool.acquire() as conn:
        kethari = await conn.fetchval(
            "SELECT id FROM characters WHERE game_id = $1 AND descriptor = $2",
            game_id,
            "La Kethari âgée",
        )
        participants = await conn.fetch(
            """SELECT fp.entity_id FROM fact_participants fp JOIN facts f ON f.id = fp.fact_id
               WHERE f.game_id = $1 AND f.semantic_key = $2""",
            game_id,
            "nahle:se:presente",
        )
    assert stats["errors"] == []
    assert [r["entity_id"] for r in participants] == [kethari]


async def test_director_participant_unresolved_is_counted(test_pool, test_user):
    from schema.director import ArcUpdate, DirectorOutput
    from services.director_apply import apply_director_plan

    game_id = await _world(test_pool, test_user)
    plan = DirectorOutput(
        tension_level=3,
        narrator_guidance="g",
        arc_updates=[
            ArcUpdate(
                action="create",
                title="La dette d'Ossek",
                description="Une dette",
                intensity=2,
                involved_entities=["Ossek", "Personne Inconnue"],
            )
        ],
    )
    async with test_pool.acquire() as conn:
        assert await apply_director_plan(
            conn,
            game_id,
            plan,
            cycle=1,
            ig_time="10h00",
            source_message_id=None,
            turn_id=None,
        )
        participants = await conn.fetch(
            """SELECT identity_bare_label(ap.entity_id) AS name FROM arc_participants ap
               JOIN narrative_arcs a ON a.id = ap.arc_id
               WHERE a.game_id = $1 AND a.title = $2""",
            game_id,
            "La dette d'Ossek",
        )
        dropped = await _events(conn, game_id, "ref_dropped")
    assert [r["name"] for r in participants] == ["Ossek"]
    assert dropped == [
        {"item": "arc participant", "entity_type": "any", "candidates": 0}
    ]


# --- Fix round 1 -------------------------------------------------------------------------


def _narration(location: str, **extra):
    from schema.narration import NarrationOutput

    return NarrationOutput.model_validate(
        {
            "narrative_text": (
                "Valentin pousse la porte et observe les alentours. L'air recyclé"
                " sent le métal et le café tiède. Personne ne lève les yeux."
            ),
            "time": {"new_time": "09h15", "ellipse": False},
            "current_location": location,
            "npcs_present": [],
            "inventory_hints": [],
            "entity_reveals": [],
            "events_mentioned": [],
            "info_requests": [],
            "extraction_triggers": [],
            **extra,
        }
    )


async def _remove(conn, table, game_id, name):
    return await conn.fetchval(
        f"UPDATE {table} SET removed_cycle = 1 WHERE game_id = $1 AND name = $2 RETURNING id",
        game_id,
        name,
    )


async def test_a_turn_at_a_removed_location_is_never_stamped_with_it(
    test_pool, test_user
):
    """I1: the narrated place of a turn is a live location: a removed one is replaced by a
    fresh location of the same name (internal suffix), which the game and the messages
    carry; a fact naming the removed place is kept without it, counted."""
    from repos import turns
    from repos.uow import uow
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    async with test_pool.acquire() as conn:
        removed = await _remove(conn, "locations", game_id, "Le Quart de Cycle")
        turn_id = await turns.open_turn(conn, game_id)
        async with uow(conn, turn_id):
            state = await turns.apply_narration_state(
                conn, game_id, _narration("Le Quart de Cycle"), 1
            )
            _, assistant_id = await turns.save_turn_messages(
                conn,
                game_id,
                user_message="J'entre.",
                assistant_message="Tu entres.",
                state=state,
                narrator_deltas={},
                engine_snapshot=None,
                turn_id=turn_id,
            )
        current = await conn.fetchval(
            "SELECT current_location_id FROM games WHERE id = $1", game_id
        )
        stamped = await conn.fetchval(
            "SELECT location_id FROM messages WHERE id = $1", assistant_id
        )
        live = await conn.fetchrow(
            "SELECT name, removed_cycle FROM locations WHERE id = $1", current
        )
    assert current != removed
    assert tuple(live) == ("Le Quart de Cycle", None)
    assert stamped == current

    stats = await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {
            "facts": [
                {**_fact("PROTAGONIST", key="pc:boit:cafe"), "location_ref": "E999999"}
            ]
        },
    )
    assert stats["errors"] == [{"code": "ref_dropped", "item": "fact location"}]


async def test_a_reference_to_a_removed_place_is_counted(test_pool, test_user):
    """I1: a fact place naming a removed location is not attached, it is counted."""
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    async with test_pool.acquire() as conn:
        await _remove(conn, "locations", game_id, "Bloc Tournesol")
    stats = await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {
            "facts": [
                {
                    **_fact("PROTAGONIST", key="pc:visite:bloc"),
                    "location_ref": "Bloc Tournesol",
                }
            ]
        },
    )
    async with test_pool.acquire() as conn:
        place = await conn.fetchval(
            "SELECT location_id FROM facts WHERE game_id = $1 AND semantic_key = $2",
            game_id,
            "pc:visite:bloc",
        )
    assert stats["errors"] == [{"code": "ref_dropped", "item": "fact location"}]
    assert place is None


async def test_acquiring_a_removed_object_is_counted_not_added(test_pool, test_user):
    from services.extraction.inventory import InventoryExtractor

    game_id = await _world(test_pool, test_user)
    async with test_pool.acquire() as conn:
        valise = await _remove(conn, "objects", game_id, "Valise cabine")
        before = await conn.fetchval(
            "SELECT quantity FROM inventory WHERE object_id = $1", valise
        )
    stats = await _run(
        InventoryExtractor,
        test_pool,
        game_id,
        {
            "inventory_changes": [
                {
                    "action": "acquire",
                    "object_ref": "Valise cabine",
                    "quantity_delta": 1,
                }
            ]
        },
    )
    async with test_pool.acquire() as conn:
        after = await conn.fetchval(
            "SELECT quantity FROM inventory WHERE object_id = $1", valise
        )
    assert stats["errors"] == [{"code": "ref_dropped", "item": "inv_change"}]
    assert after == before


async def test_world_gen_never_folds_an_entity_into_another_through_an_alias(
    test_pool, test_user
):
    """I2: « Ossek » listed after « Ossek Varn » (whose short alias is « Ossek ») and
    « Serres » after « Serres Hydro-7 » are distinct entities, linked by the ids made."""

    def homonyms(data):
        ossek = next(c for c in data["characters"] if c["name"] == "Ossek")
        data["characters"].insert(
            0, {**ossek, "name": "Ossek Varn", "workplace_ref": "Serres Hydro-7"}
        )
        data["locations"].append(
            {"name": "Serres", "parent_location_ref": "Bloc Tournesol"}
        )

    game_id = await _world(test_pool, test_user, homonyms)
    async with test_pool.acquire() as conn:
        characters = {
            r["true_name"]: r["workplace"]
            for r in await conn.fetch(
                """SELECT c.true_name, w.name AS workplace FROM characters c
                   LEFT JOIN locations w ON w.id = c.workplace_id
                   WHERE c.game_id = $1 AND c.true_name LIKE 'Ossek%'""",
                game_id,
            )
        }
        serres = await conn.fetchrow(
            """SELECT l.id, p.name AS parent FROM locations l
               LEFT JOIN locations p ON p.id = l.parent_id
               WHERE l.game_id = $1 AND l.name = 'Serres'""",
            game_id,
        )
        owner = await conn.fetchval(
            """SELECT c.true_name FROM relations r JOIN characters c ON c.id = r.source_id
               JOIN locations l ON l.id = r.target_id
               WHERE r.game_id = $1 AND r.type = 'owns' AND l.name = 'Le Quart de Cycle'""",
            game_id,
        )
    assert characters == {"Ossek": "Le Quart de Cycle", "Ossek Varn": "Serres Hydro-7"}
    assert serres is not None and serres["parent"] == "Bloc Tournesol"
    assert owner == "Ossek"


@pytest.mark.parametrize(
    ("flag", "reveals"), [(True, True), (False, False), ("false", False)]
)
async def test_a_known_flag_among_changes_reveals_only_when_true(
    test_pool, test_user, flag, reveals
):
    """I4: the coerced boolean is read: a string « false » never reveals."""
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    update = {
        "entities_updated": [
            {
                "entity_ref": "Justine Lépicier",
                "changes": {"known_by_protagonist": flag},
            }
        ]
    }
    first = await _run(CharactersExtractor, test_pool, game_id, update)
    async with test_pool.acquire() as conn:
        known = await conn.fetchval(
            "SELECT known_by_protagonist FROM characters WHERE game_id = $1"
            " AND true_name = 'Justine Lépicier'",
            game_id,
        )
        events = len(await _events(conn, game_id, "reveal_applied"))
    await _run(CharactersExtractor, test_pool, game_id, update, cycle=3)
    async with test_pool.acquire() as conn:
        again = len(await _events(conn, game_id, "reveal_applied"))
    assert first["errors"] == []
    assert known is reveals
    assert (events, again) == ((1, 1) if reveals else (0, 0))


async def test_a_narrator_event_with_an_unknown_place_is_counted(test_pool, test_user):
    """I3 (C12): the stub event is written without its place, and the place is counted."""
    from repos import turns
    from repos.uow import uow

    game_id = await _world(test_pool, test_user)
    narration = _narration(
        "Le Quart de Cycle",
        events_mentioned=[
            {"title": "Livraison au quai", "planned_cycle": 3, "location": "Nulle Part"}
        ],
    )
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game_id)
        async with uow(conn, turn_id):
            await turns.apply_narration_state(conn, game_id, narration, 1)
        place = await conn.fetchval(
            "SELECT location_id FROM events WHERE game_id = $1 AND title = $2",
            game_id,
            "Livraison au quai",
        )
        dropped = await _events(conn, game_id, "ref_dropped")
    assert place is None
    assert dropped == [
        {"item": "stub event location", "entity_type": "location", "candidates": 0}
    ]


async def test_an_update_of_the_companion_is_refused_with_a_code(test_pool, test_user):
    """M5: extractors never update the companion (spec §4.10): a coded refusal."""
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    stats = await _run(
        CharactersExtractor,
        test_pool,
        game_id,
        {
            "entities_updated": [
                {
                    "entity_ref": "COMPANION",
                    "entity_type": None,
                    "changes": {"mood": "joueuse"},
                }
            ]
        },
    )
    assert stats["errors"] == [{"code": "update_refused", "item": "update"}]
