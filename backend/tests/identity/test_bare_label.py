"""Prompts read labels without their internal homonym suffix (#153, ruling R14): the
narrator, the Director and the extraction contexts never see « Garde du sas (Quai 9) »."""

from uuid import UUID

import pytest

from config import get_identity_config
from kg.reader import KnowledgeGraphReader
from services.identity.service import IdentityService
from services.identity.types import NewEntitySpec

pytestmark = pytest.mark.integration

GUARD = "Garde du sas"


@pytest.fixture
async def world(test_pool, test_user) -> dict:
    """Two guards and two bars, the second of each with an internal suffix; the suffixed
    guard owns an arc and works at the suffixed bar; the protagonist knows both guards."""
    async with test_pool.acquire() as conn:
        game = await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
            test_user["id"],
        )
        service = IdentityService(game, lang="fr", config=get_identity_config())
        pc = await conn.fetchval(
            "INSERT INTO protagonists (game_id, name) VALUES ($1, 'Rafe') RETURNING id",
            game,
        )

        async def create(entity_type, label, **kwargs):
            return await service.create_entity(
                conn,
                NewEntitySpec(entity_type, label, "descriptor"),
                turn_id=None,
                source="extractor",
                **kwargs,
            )

        quay = await create("location", "Quai 9")
        first_guard = await create("character", GUARD)
        guard = await create("character", GUARD, scene_location_id=quay, trap=True)
        await create("location", "Le Bar du coin")
        bar = await create("location", "Le Bar du coin", trap=True)
        await conn.execute(
            """INSERT INTO narrative_arcs (game_id, title, domain, description, intensity,
                                           owner_id, created_cycle)
               VALUES ($1, 'Relève', 'personal', 'Une relève tendue.', 3, $2, 1)""",
            game,
            guard,
        )
        await conn.execute(
            """INSERT INTO relations (game_id, type, source_id, target_id, level)
               VALUES ($1, 'knows', $2, $3, 5), ($1, 'works_at', $3, $4, NULL),
                      ($1, 'knows', $2, $5, 2)""",
            game,
            pc,
            guard,
            bar,
            first_guard,
        )
        labels = {
            r["id"]: r["name"]
            for r in await conn.fetch(
                "SELECT id, name FROM entity_registry WHERE id = ANY($1::uuid[])",
                [guard, bar],
            )
        }
    assert labels == {guard: f"{GUARD} (Quai 9)", bar: "Le Bar du coin (2)"}
    return {"game": game, "guard": guard, "first_guard": first_guard, "bar": bar}


async def test_identity_bare_label_drops_the_internal_suffix(test_pool, world):
    async with test_pool.acquire() as conn:
        bare = {
            entity_id: await conn.fetchval("SELECT identity_bare_label($1)", entity_id)
            for entity_id in (world["guard"], world["bar"])
        }
    assert bare == {world["guard"]: GUARD, world["bar"]: "Le Bar du coin"}


async def test_prompt_reads_carry_the_bare_label(test_pool, world):
    from services.context_builder import ContextBuilder

    game: UUID = world["game"]
    reader = KnowledgeGraphReader(None, game)
    builder = ContextBuilder(test_pool, game)
    async with test_pool.acquire() as conn:
        arcs = await reader.get_active_arcs(conn)
        active_arcs = builder._build_active_arcs(arcs)
        characters = await reader.get_all_characters(conn)
        at_bar = await reader.get_npcs_at_location(
            conn,
            "E"
            + str(
                await conn.fetchval(
                    "SELECT handle FROM entity_registry WHERE id = $1", world["bar"]
                )
            ),
        )
        relations = await reader.get_relations(conn)
        entities = await reader.get_entities(conn)
        details = await reader.get_entity_details(conn, world["guard"])
    assert [a.owner for a in active_arcs] == [GUARD]
    assert sorted(c["name"] for c in characters) == [GUARD, GUARD]
    assert [c["name"] for c in at_bar] == [GUARD]
    assert {(r["source_name"], r["target_name"]) for r in relations} == {
        ("Rafe", GUARD),
        (GUARD, "Le Bar du coin"),
    }
    names = {e["name"] for e in entities}
    assert not any("(" in name for name in names)
    assert details["name"] == GUARD


async def test_first_turn_resolver_reference_carries_the_bare_label(test_pool, world):
    from services.extraction.orchestrator import _build_first_turn_reference

    text, _ = await _build_first_turn_reference(test_pool, world["game"])
    assert f"{GUARD} [= {GUARD}]" in text
    assert "(Quai 9)" not in text and "(2)" not in text


async def test_name_lookups_of_relations_answer_nothing_for_homonyms(test_pool, world):
    """A name two homonyms share names neither (find_entity: NULL): no arbitrary row; a
    handle names one."""
    reader = KnowledgeGraphReader(None, world["game"])
    async with test_pool.acquire() as conn:
        handle = await conn.fetchval(
            "SELECT 'E' || handle FROM entity_registry WHERE id = $1", world["guard"]
        )
        by_name = await reader.get_protagonist_relation_to(conn, GUARD)
        by_handle = await reader.get_protagonist_relation_to(conn, handle)
        relations_by_name = await reader.get_relations(conn, entity_name=GUARD)
        relations_by_handle = await reader.get_relations(conn, entity_name=handle)
        bar_relations = await reader.get_relations(conn, entity_name="Le Bar du coin")
        unknown = await reader.get_relations(conn, entity_name="Personne")
    assert by_name is None
    assert by_handle["level"] == 5
    assert relations_by_name == []
    assert {r["relation_type"] for r in relations_by_handle} == {"knows", "works_at"}
    # The bare bar name is shared too (both bars hold it as an alias).
    assert bar_relations == [] and unknown == []
