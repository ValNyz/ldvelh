"""#28: the protagonist resolves by type (PROTAGONIST_REF), not by a hardcoded name.

Every world here is the canonical example with its PC renamed "Kira", so a leftover
"Valentin" anywhere in the write path shows up as a missing participant or relation.
"""

import json
from uuid import uuid4

import pytest

from kg.populator import EntityRegistry
from schema import PROTAGONIST_REF, EntityType, WorldGeneration
from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

pytestmark = pytest.mark.integration

PC = "Kira"
ARRIVAL_WITH_PC = ("station", "incident", "mood", "need")


def kira_world() -> WorldGeneration:
    return WorldGeneration.model_validate(
        json.loads(WORLD_GENERATION_EXAMPLE.replace("Valentin", PC)))


async def populate_kira(test_pool, test_user):
    from services.game_service import GameService

    world_gen = kira_world()
    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])
    await service.process_init(game_id, world_gen)
    return game_id, world_gen


async def protagonist_relations(conn, game_id, target: str, rel_type: str):
    return await conn.fetch(
        """SELECT r.level, r.context, r.known_by_protagonist, r.end_cycle, src.name AS source
           FROM relations r
           JOIN entity_registry src ON src.id = r.source_id
           JOIN entity_registry tgt ON tgt.id = r.target_id
           WHERE r.game_id = $1 AND src.entity_type = 'protagonist'
             AND tgt.name = $2 AND r.type = $3::relation_type""",
        game_id, target, rel_type)


async def fact_participants(conn, game_id, semantic_key: str):
    return await conn.fetch(
        """SELECT er.name, er.entity_type, fp.role FROM facts f
           JOIN fact_participants fp ON fp.fact_id = f.id
           JOIN entity_registry er ON er.id = fp.entity_id
           WHERE f.game_id = $1 AND f.semantic_key = $2""",
        game_id, semantic_key)


def test_registry_resolves_the_token_to_the_protagonist_row():
    registry = EntityRegistry()
    pc_id, npc_id = uuid4(), uuid4()
    registry.register(PC, pc_id, EntityType.PROTAGONIST)
    registry.register("Marie", npc_id, EntityType.CHARACTER)

    assert registry.resolve(PROTAGONIST_REF) == pc_id
    assert registry.resolve(f"  {PROTAGONIST_REF.lower()} ") == pc_id
    assert registry.resolve(PC) == pc_id  # the real name still resolves
    assert PROTAGONIST_REF in registry
    assert EntityRegistry().resolve(PROTAGONIST_REF) is None  # no PC registered yet


def test_entity_ref_schema_tells_the_llm_about_the_token():
    from schema.extraction import RelationUpdate

    schema = RelationUpdate.model_json_schema()
    assert PROTAGONIST_REF in schema["properties"]["source_ref"]["description"]


async def test_world_with_pc_kira_has_kira_in_arrival_facts(test_pool, test_user):
    game_id, _ = await populate_kira(test_pool, test_user)
    async with test_pool.acquire() as conn:
        for part in ARRIVAL_WITH_PC:
            rows = await fact_participants(conn, game_id, f"protagonist:arrival:{part}")
            assert [(r["name"], r["entity_type"], r["role"]) for r in rows] == [
                (PC, "protagonist", "actor")], part
        legacy = await conn.fetchval(
            "SELECT COUNT(*) FROM facts WHERE game_id = $1 AND semantic_key LIKE 'valentin:%'",
            game_id)
    assert legacy == 0


async def test_arrival_event_reads_the_protagonist_keys(test_pool, test_user):
    from kg.reader import KnowledgeGraphReader

    game_id, world_gen = await populate_kira(test_pool, test_user)
    async with test_pool.acquire() as conn:
        arrival = await KnowledgeGraphReader(test_pool, game_id).get_arrival_event(conn)
    ae = world_gen.arrival_event
    assert arrival["initial_mood"] == ae.initial_mood
    assert arrival["immediate_need"] == ae.immediate_need
    assert arrival["incident"] == ae.optional_incident
    assert ae.arrival_method in arrival["arrival_description"]


async def test_item_use_fact_has_the_protagonist(test_pool, test_user):
    from kg.specialized_populator import ExtractionPopulator
    from schema import NarrativeExtraction

    game_id, _ = await populate_kira(test_pool, test_user)
    extraction = NarrativeExtraction.model_validate({"cycle": 2, "inventory_changes": [
        {"action": "use", "object_ref": "Terminal personnel", "quantity_delta": 1}]})
    await ExtractionPopulator(test_pool, game_id).process_extraction(extraction)
    async with test_pool.acquire() as conn:
        rows = await fact_participants(conn, game_id, "protagonist:use:terminal_personnel")
    assert [(r["name"], r["role"]) for r in rows] == [(PC, "actor")]


async def run_narrative_arcs(test_pool, game_id, raw: dict, cycle: int = 2) -> dict:
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    extractor = NarrativeArcsExtractor(test_pool, game_id, session=None)
    stats, error = await extractor._populate_committed(raw, cycle)
    assert error is None and not stats["errors"], stats
    return stats


@pytest.mark.parametrize("source_ref", [PROTAGONIST_REF, PC, PC.upper()])
async def test_extracted_relation_from_protagonist_is_created(test_pool, test_user,
                                                              source_ref):
    """The token and the real PC name both create the relation from the protagonist."""
    game_id, world_gen = await populate_kira(test_pool, test_user)
    npc = world_gen.characters[0].name
    stats = await run_narrative_arcs(test_pool, game_id, {"relations_created": [
        {"cycle": 2, "relation": {"source_ref": source_ref, "target_ref": npc,
                                  "relation_type": "friend_of", "level": 4}}]})
    assert stats["relations_created"] == 1
    async with test_pool.acquire() as conn:
        rows = await protagonist_relations(conn, game_id, npc, "friend_of")
    assert [(r["source"], r["level"]) for r in rows] == [(PC, 4)]


async def test_extracted_update_end_and_fact_with_the_token(test_pool, test_user):
    """relations_updated (raw SQL), relations_ended and fact participants (SQL find_entity)."""
    game_id, world_gen = await populate_kira(test_pool, test_user)
    npc = world_gen.characters[0].name
    await run_narrative_arcs(test_pool, game_id, {"relations_created": [
        {"cycle": 2, "relation": {"source_ref": PROTAGONIST_REF, "target_ref": npc,
                                  "relation_type": "colleague_of", "level": 2}}]})
    await run_narrative_arcs(test_pool, game_id, {
        "relations_updated": [{"source_ref": PROTAGONIST_REF, "target_ref": npc,
                               "relation_type": "colleague_of", "new_level": 6}],
        "facts": [{"fact_type": "decision", "description": f"{PC} décide d'aider {npc}",
                   "semantic_key": "kira:decide:aider", "importance": 3,
                   "participants": [{"entity_ref": PROTAGONIST_REF, "role": "actor"},
                                    {"entity_ref": npc, "role": "target"}]}],
    })
    async with test_pool.acquire() as conn:
        assert [r["level"] for r in await protagonist_relations(
            conn, game_id, npc, "colleague_of")] == [6]
        rows = await fact_participants(conn, game_id, "kira:decide:aider")
        assert sorted((r["name"], r["role"]) for r in rows) == sorted(
            [(PC, "actor"), (npc, "target")])

    await run_narrative_arcs(test_pool, game_id, {"relations_ended": [
        {"source_ref": PROTAGONIST_REF, "target_ref": npc, "relation_type": "colleague_of",
         "cycle": 3, "reason": "Départ"}]}, cycle=3)
    async with test_pool.acquire() as conn:
        assert [r["end_cycle"] for r in await protagonist_relations(
            conn, game_id, npc, "colleague_of")] == [3]


async def test_sql_find_entity_maps_the_token(test_pool, test_user):
    """The SQL side uses the same spelling as schema.core.PROTAGONIST_REF."""
    game_id, _ = await populate_kira(test_pool, test_user)
    async with test_pool.acquire() as conn:
        pc_id = await conn.fetchval(
            "SELECT id FROM entity_registry WHERE game_id = $1 AND entity_type = 'protagonist'",
            game_id)
        assert await conn.fetchval("SELECT find_entity($1, $2)", game_id, PROTAGONIST_REF) == pc_id
        assert await conn.fetchval("SELECT find_entity($1, $2)", game_id,
                                   f" {PROTAGONIST_REF.lower()}") == pc_id
        assert await conn.fetchval("SELECT find_entity($1, $2)", game_id, PC) == pc_id
        assert await conn.fetchval(
            "SELECT find_entity($1, $2, 'character')", game_id, PROTAGONIST_REF) is None


# ---------------------------------------------------------------------------
# Prompts and defaults
# ---------------------------------------------------------------------------


def test_extraction_prompts_teach_the_token_not_a_name():
    from prompts.extraction import (characters_prompt, inventory_prompt, locations_prompt,
                                    narrative_arcs_prompt, organizations_prompt)
    from prompts.extraction.shared import ENTITY_MATCHING_RULE

    assert f'"{PROTAGONIST_REF}"' in ENTITY_MATCHING_RULE
    for module in (characters_prompt, inventory_prompt, locations_prompt,
                   narrative_arcs_prompt, organizations_prompt):
        assert "valentin" not in module.SYSTEM_PROMPT.lower(), module.__name__
        assert ENTITY_MATCHING_RULE in module.SYSTEM_PROMPT, module.__name__
    assert f'"source_ref": "{PROTAGONIST_REF}"' in narrative_arcs_prompt.SYSTEM_PROMPT
    assert f'"entity_ref": "{PROTAGONIST_REF}"' in inventory_prompt.SYSTEM_PROMPT


def test_protagonist_section_injects_the_real_name():
    from prompts.extraction.shared import protagonist_section

    section = protagonist_section(PC)
    assert PC in section and f'"{PROTAGONIST_REF}"' in section
    assert protagonist_section(None) == ""


async def test_extractor_user_prompt_names_the_protagonist(test_pool, test_user):
    from services.extraction.characters import CharactersExtractor

    game_id, _ = await populate_kira(test_pool, test_user)
    extractor = CharactersExtractor(test_pool, game_id, session=None)
    seen = {}

    async def fake_call(system_prompt, user_prompt, schema):
        seen["user"] = user_prompt
        return {}, None

    extractor._call_llm = fake_call
    await extractor.run("Kira salue Marie.", {}, 2)
    assert f"{PC}" in seen["user"] and f'"{PROTAGONIST_REF}"' in seen["user"]


def test_protagonist_name_is_required():
    from pydantic import ValidationError

    from schema import ProtagonistData

    with pytest.raises(ValidationError):
        ProtagonistData.model_validate({"skills": [{"name": "a", "level": 1},
                                                   {"name": "b", "level": 2}]})


def test_world_prompt_without_a_chosen_name_asks_the_model_to_invent_one():
    from prompts.world_generation_prompt import build_world_generation_user_prompt

    blank = build_world_generation_user_prompt()
    assert "valentin" not in blank.lower()
    assert "Nom : à inventer" in blank
    assert "Nom : Kira" in build_world_generation_user_prompt(protagonist_name=PC)


def test_init_prompt_uses_the_wizard_name_or_none():
    from pipeline.context import InitParams
    from pipeline.init_flow import _build_prompt

    def params(character):
        return InitParams(engine=None, world_config=None, character_data=character,
                          manual_entities=None)

    assert "Nom : Kira" in _build_prompt("", params({"name": PC}), "none", None)["user"]
    blank = _build_prompt("", params({"name": "  "}), "none", None)["user"]
    assert "Nom : à inventer" in blank and "valentin" not in blank.lower()


def test_init_fills_a_missing_protagonist_name_from_the_wizard():
    from pipeline.init_flow import with_chosen_name

    parsed = json.loads(WORLD_GENERATION_EXAMPLE)
    del parsed["protagonist"]["name"]
    assert with_chosen_name(parsed, {"name": PC})["protagonist"]["name"] == PC
    named = json.loads(WORLD_GENERATION_EXAMPLE)
    assert with_chosen_name(named, {"name": PC})["protagonist"]["name"] == "Valentin"
    assert with_chosen_name({"protagonist": {}}, None) == {"protagonist": {}}


def test_world_generation_accepts_the_token_in_initial_relations():
    parsed = json.loads(WORLD_GENERATION_EXAMPLE)
    for rel in parsed["initial_relations"]:
        if rel["source_ref"] == "Valentin":
            rel["source_ref"] = PROTAGONIST_REF
    kept = WorldGeneration.model_validate(parsed).initial_relations
    assert len(kept) == len(parsed["initial_relations"])
