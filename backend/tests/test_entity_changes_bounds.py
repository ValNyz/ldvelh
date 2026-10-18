"""
Bounds on LLM-extracted values (#24, issue comment): an over-long or mistyped value is
bounded or dropped at the schema boundary instead of aborting the item at the SQL write.
"""

import logging

from llm.session import LLMSession
from schema import EntityType
from schema.entity_changes import bound_changes
from services.extraction.characters import CharactersExtractor
from services.game_service import GameService
from tests.test_llm_session import FakeProvider

STORY = "trente-six ans, peut-etre trente-sept"  # 37 chars, a varchar(30) column


async def _run_characters(test_pool, test_user, raw):
    game_id = await GameService(test_pool).create_game(test_user["id"])
    extractor = CharactersExtractor(test_pool, game_id,
                                    LLMSession.from_provider(FakeProvider()))

    async def fake_call(*_args, **_kwargs):
        return raw, None

    extractor._call_llm = fake_call
    return game_id, await extractor.run("texte", {}, 1)


async def _character(test_pool, game_id, name):
    async with test_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM characters WHERE game_id = $1 AND name = $2", game_id, name)


async def test_over_long_changes_are_bounded_and_the_rest_is_kept(test_pool, test_user, caplog):
    raw = {
        "entities_created": [{"name": "Voss"}],
        "entities_updated": [{"entity_ref": "Voss", "changes": {
            "age": STORY,                      # varchar(30)
            "pronouns": "il ou elle selon les jours, surtout il",  # varchar(30)
            "gender": "g" * 45 + " " + "x" * 20,  # bound min(30, varchar(50))
            "mood": "inquiet",
            "workplace_id": "Le bar du quai",  # uuid column: dropped, not sent to SQL
        }}],
    }
    with caplog.at_level(logging.INFO):
        game_id, result = await _run_characters(test_pool, test_user, raw)

    assert result["success"] is True, result["stats"]["errors"]
    assert result["stats"]["entities_updated"] == 1
    voss = await _character(test_pool, game_id, "Voss")
    assert voss["mood"] == "inquiet"
    assert 0 < len(voss["age"]) <= 30 and len(voss["pronouns"]) <= 30
    assert 0 < len(voss["gender"]) <= 30
    assert voss["workplace_id"] is None
    shown = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.INFO)
    assert "trente-six" not in shown and "Le bar du quai" not in shown


async def test_skill_level_above_the_check_is_clamped(test_pool, test_user):
    raw = {
        "entities_created": [{"name": "Zeta"}],
        "entities_updated": [{"entity_ref": "Zeta",
                              "skills_changed": [{"name": "escrime", "level": 6}]}],
    }
    game_id, result = await _run_characters(test_pool, test_user, raw)

    assert result["success"] is True, result["stats"]["errors"]
    async with test_pool.acquire() as conn:
        level = await conn.fetchval(
            "SELECT s.level FROM skills s JOIN characters c ON c.id = s.character_id"
            " WHERE c.game_id = $1 AND s.name = 'escrime'", game_id)
    assert level == 5  # skills_level_check: 1..5


def test_bound_changes_keeps_valid_fields_and_drops_invalid_ones():
    kept = bound_changes(EntityType.CHARACTER, {
        "age": STORY, "mood": "calme", "is_mandatory": "pas du tout",
        "traits": "loyal", "name": "Autre",
    })
    assert kept["mood"] == "calme" and len(kept["age"]) <= 30
    assert kept["traits"] == ["loyal"]
    assert "is_mandatory" not in kept  # not a boolean
    assert "name" not in kept          # not an updatable column
    assert bound_changes(None, {"age": STORY}) == {"age": STORY}  # type unresolved yet


async def test_fate_skill_upgrade_of_wrong_type_is_skipped_alone(test_pool, test_user):
    from services.engine.fate_core import FateCoreEngine

    game_id = await GameService(test_pool).create_game(test_user["id"])
    async with test_pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO skills_fate (game_id, name, level) VALUES ($1, $2, 1)",
            [(game_id, "Combat"), (game_id, "Tir")])
        changes = await FateCoreEngine().apply_progression(conn, game_id, {
            "skill_upgrades": [{"skill_name": "Combat", "new_level": "élevé"},
                               {"skill_name": "Tir", "new_level": 3}],
        })
        levels = dict(await conn.fetch(
            "SELECT name, level FROM skills_fate WHERE game_id = $1", game_id))
    assert levels == {"Combat": 1, "Tir": 3}
    assert changes["skill_upgrades"] == [{"skill": "Tir", "level": 3}]


async def test_process_extraction_isolates_a_failed_item(test_pool, test_user):
    """ExtractionPopulator.process_extraction: same per-item savepoints as the extractors."""
    from kg.specialized_populator import ExtractionPopulator
    from schema import NarrativeExtraction

    game_id = await GameService(test_pool).create_game(test_user["id"])
    extraction = NarrativeExtraction.model_validate({
        "cycle": 1,
        "entities_created": [{"entity_type": "character", "name": "Alpha"},
                             {"entity_type": "character", "name": "Beta"}],
        "entities_updated": [
            {"entity_ref": "Alpha", "entity_type": "character", "changes": {"mood": "las"}},
            {"entity_ref": "Beta", "entity_type": "character", "changes": {"mood": "calme"}},
        ],
        "facts": [{"cycle": 1, "fact_type": "observation", "description": "Une porte grince.",
                   "semantic_key": "porte:grince:nuit"}],
    })
    populator = ExtractionPopulator(test_pool, game_id)
    real_update = populator.update_entity

    async def colliding_update(conn, entity_type, name, changes):
        if name == "Alpha":  # rename collision: server-side unique violation
            await conn.execute("UPDATE characters SET name = 'Beta' "
                               "WHERE game_id = $1 AND name = 'Alpha'", game_id)
        return await real_update(conn, entity_type, name, changes)

    populator.update_entity = colliding_update
    stats = await populator.process_extraction(extraction)

    assert (stats["entities_created"], stats["entities_updated"], stats["facts_created"]) \
        == (2, 1, 1)
    [error] = stats["errors"]
    assert error.startswith("Entity update:")
    assert (await _character(test_pool, game_id, "Beta"))["mood"] == "calme"
    assert await _character(test_pool, game_id, "Alpha") is not None
    async with test_pool.acquire() as conn:
        logged = await conn.fetchval(
            "SELECT errors FROM extraction_logs WHERE game_id = $1", game_id)
    assert logged == [error]


def _max_length(field) -> int | None:
    """max_length of a field, looking inside `X | None` and Annotated metadata."""
    from typing import get_args

    def walk(tp):
        for m in getattr(tp, "__metadata__", ()):
            if getattr(m, "max_length", None):
                return m.max_length
        return next((w for w in map(walk, get_args(tp)) if w), None)

    direct = [m.max_length for m in field.metadata if getattr(m, "max_length", None)]
    return direct[0] if direct else walk(field.annotation)


async def test_field_bounds_fit_the_db_columns(test_pool):
    """Every bound is <= its DB column width (information_schema), same in both models."""
    from schema.entities import CharacterData, LocationData, OrganizationData
    from schema.entity_changes import CHANGES_MODELS

    creation = {EntityType.CHARACTER: CharacterData, EntityType.LOCATION: LocationData,
                EntityType.ORGANIZATION: OrganizationData}
    tables = {EntityType.CHARACTER: "characters", EntityType.LOCATION: "locations",
              EntityType.ORGANIZATION: "organizations"}
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT table_name, column_name, character_maximum_length FROM information_schema.columns"
            " WHERE table_name = ANY($1::text[]) AND data_type = 'character varying'",
            list(tables.values()))
    widths = {(r["table_name"], r["column_name"]): r["character_maximum_length"] for r in rows}

    for entity_type, changes_model in CHANGES_MODELS.items():
        table = tables[entity_type]
        for name, field in changes_model.model_fields.items():
            width = widths.get((table, name))
            if width is None:
                continue  # text / uuid / bool / int column: no width
            bound = _max_length(field)
            assert bound is not None and bound <= width, (table, name, bound, width)
            data_field = creation[entity_type].model_fields.get(name)
            if data_field is not None:
                assert _max_length(data_field) == bound, (table, name, "creation model drift")

