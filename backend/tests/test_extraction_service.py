"""
Tests for the specialized extraction system (services/extraction/).
Tests the orchestrator, base extractor pattern, and schema validation.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from schema.extraction import (
    ExtractionType,
    CharactersExtraction,
    LocationsExtraction,
    OrganizationsExtraction,
    InventoryExtraction,
    NarrativeArcsExtraction,
)
from domain.identity import SceneEntity, TurnResolution


SESSION = MagicMock()  # the orchestrator is fully patched in these tests
SAMPLE_GAME_ID = uuid4()
SAMPLE_MSG_ID = uuid4()
PREV_MSG_ID = uuid4()
SCENE = [
    SceneEntity("E17", "character", "Vieille au châle", False, False),
    SceneEntity("E21", "location", "Halle aux Cordiers", True, True),
]


def _resolution(scene, *, new_types=None, usage=None) -> TurnResolution:
    return TurnResolution(
        mentions=[], created=[], aliases_added=0, reveals=[], scene_entities=scene,
        new_types=new_types or set(), escalated=False, fallback=False, usage=usage or {},
    )


def _extractor_class(run):
    instance = MagicMock()
    instance.run = AsyncMock(side_effect=run)
    return MagicMock(return_value=instance)


def _mock_pool():
    """A mock asyncpg pool with a working acquire() context manager."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_conn.fetchrow = AsyncMock(return_value=None)

    pool = MagicMock()

    def _new_cm():
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    pool.acquire.side_effect = lambda: _new_cm()
    return pool, mock_conn


# =============================================================================
# EXTRACTION TYPE ENUM
# =============================================================================


class TestExtractionType:
    """Tests for ExtractionType enum."""

    def test_all_types_defined(self):
        assert ExtractionType.CHARACTERS == "characters"
        assert ExtractionType.LOCATIONS == "locations"
        assert ExtractionType.ORGANIZATIONS == "organizations"
        assert ExtractionType.INVENTORY == "inventory"
        assert ExtractionType.NARRATIVE_ARCS == "narrative_arcs"

    def test_enum_values(self):
        values = {e.value for e in ExtractionType}
        assert values == {"characters", "locations", "organizations", "inventory", "narrative_arcs", "progression"}


# =============================================================================
# SPECIALIZED EXTRACTION MODELS
# =============================================================================


class TestCharactersExtraction:
    def test_empty_defaults(self):
        ext = CharactersExtraction()
        assert ext.proposed_entities == []
        assert ext.entities_updated == []
        assert ext.entities_removed == []
        assert ext.ambient_updates == []
        assert ext.skills_changed == []
        assert ext.facts == []


class TestLocationsExtraction:
    def test_empty_defaults(self):
        ext = LocationsExtraction()
        assert ext.proposed_entities == []
        assert ext.entities_updated == []
        assert ext.ambient_updates == []
        assert ext.facts == []


class TestOrganizationsExtraction:
    def test_empty_defaults(self):
        ext = OrganizationsExtraction()
        assert ext.proposed_entities == []
        assert ext.entities_updated == []
        assert ext.ambient_updates == []
        assert ext.facts == []


class TestInventoryExtraction:
    def test_empty_defaults(self):
        ext = InventoryExtraction()
        assert ext.objects_created == []
        assert ext.inventory_changes == []
        assert ext.facts == []


class TestNarrativeArcsExtraction:
    def test_empty_defaults(self):
        ext = NarrativeArcsExtraction()
        assert ext.arcs_created == []
        assert ext.arcs_updated == []
        assert ext.arcs_resolved == []
        assert ext.relations_created == []
        assert ext.relations_updated == []
        assert ext.relations_ended == []
        assert ext.events_scheduled == []
        assert ext.facts == []
        assert ext.segment_summary == ""


# =============================================================================
# ORCHESTRATOR
# =============================================================================


class TestOrchestrator:
    """Tests for the extraction orchestrator (run_resolve_and_extract)."""

    @pytest.mark.asyncio
    async def test_empty_triggers_skipped(self):
        """No narrator trigger and nothing resolved: no extractor runs."""
        from services.extraction.orchestrator import run_resolve_and_extract

        pool, _ = _mock_pool()
        result = await run_resolve_and_extract(
            pool, SAMPLE_GAME_ID, trigger_cycle=3,
            triggers=[], session=SESSION,
        )

        assert result.get("extractors") == {}

    @pytest.mark.asyncio
    async def test_invalid_trigger_ignored(self):
        """Unknown trigger names are silently ignored."""
        from services.extraction.orchestrator import run_resolve_and_extract

        pool, _ = _mock_pool()
        result = await run_resolve_and_extract(
            pool, SAMPLE_GAME_ID, trigger_cycle=3,
            triggers=["nonexistent_type"], session=SESSION,
        )

        assert result["extractors"] == {}

    @pytest.mark.asyncio
    async def test_resolver_called_before_extractors(self):
        """Phase 1 resolver is called before Phase 2 extractors."""
        from services.extraction.orchestrator import EXTRACTOR_MAP, run_resolve_and_extract

        call_order = []
        pool, _ = _mock_pool()

        async def mock_resolve(*args, **kwargs):
            call_order.append("resolver")
            return None

        async def mock_extractor_run(**kwargs):
            call_order.append("extractor")
            return {"type": "characters", "skipped": True}

        mock_extractor_cls = _extractor_class(mock_extractor_run)
        with (
            patch("services.extraction.orchestrator.resolve_phase", side_effect=mock_resolve),
            patch.dict(EXTRACTOR_MAP, {"characters": mock_extractor_cls}),
        ):
            await run_resolve_and_extract(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters"], session=SESSION,
                assistant_message_id=SAMPLE_MSG_ID,
                message_content="Le docteur vous examine.",
                narrator_deltas={},
            )

        assert call_order == ["resolver", "extractor"]

    @pytest.mark.asyncio
    async def test_scene_entities_passed_to_extractors(self):
        """The scene of the turn's resolution is forwarded to each extractor."""
        from services.extraction.orchestrator import EXTRACTOR_MAP, run_resolve_and_extract

        resolution = _resolution(SCENE)
        pool, _ = _mock_pool()
        received = []

        async def mock_extractor_run(**kwargs):
            received.append(kwargs["scene_entities"])
            return {"type": "test", "success": True, "stats": {}}

        with (
            patch("services.extraction.orchestrator.resolve_phase",
                  AsyncMock(return_value=resolution)),
            patch.dict(EXTRACTOR_MAP, {"characters": _extractor_class(mock_extractor_run),
                                       "locations": _extractor_class(mock_extractor_run)}),
        ):
            await run_resolve_and_extract(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters", "locations"],
                session=SESSION,
                assistant_message_id=SAMPLE_MSG_ID,
                message_content="Le docteur vous examine.",
                narrator_deltas={},
            )

        assert received == [SCENE, SCENE]

    @pytest.mark.asyncio
    async def test_new_types_add_their_extractor(self):
        """A type the resolution created runs its extractor without a narrator trigger."""
        from services.extraction.orchestrator import EXTRACTOR_MAP, run_resolve_and_extract

        pool, _ = _mock_pool()
        ran = []

        async def mock_extractor_run(**kwargs):
            ran.append(kwargs["scene_entities"])
            return {"type": "locations", "success": True, "stats": {}}

        with (
            patch("services.extraction.orchestrator.resolve_phase",
                  AsyncMock(return_value=_resolution(SCENE, new_types={"location"}))),
            patch.dict(EXTRACTOR_MAP, {"locations": _extractor_class(mock_extractor_run)}),
        ):
            result = await run_resolve_and_extract(
                pool, SAMPLE_GAME_ID, trigger_cycle=3, triggers=[], session=SESSION,
                assistant_message_id=SAMPLE_MSG_ID, message_content="Le quai.",
            )

        assert list(result["extractors"]) == ["locations"] and ran == [SCENE]

    @pytest.mark.asyncio
    async def test_resolver_failure_does_not_block_extractors(self):
        """If Phase 1 fails, Phase 2 extractors still run, with an empty scene."""
        from services.extraction import orchestrator
        from services.extraction.orchestrator import EXTRACTOR_MAP, run_resolve_and_extract

        pool, _ = _mock_pool()
        extractor_called = []

        async def mock_extractor_run(**kwargs):
            extractor_called.append(kwargs["scene_entities"])
            return {"type": "characters", "success": True, "stats": {}}

        with (
            patch.object(orchestrator.IdentityService, "for_game",
                         AsyncMock(side_effect=RuntimeError("Haiku is down!"))),
            patch.dict(EXTRACTOR_MAP, {"characters": _extractor_class(mock_extractor_run)}),
        ):
            result = await run_resolve_and_extract(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters"], session=SESSION,
                assistant_message_id=SAMPLE_MSG_ID,
                message_content="Le docteur vous examine.",
                narrator_deltas={},
            )

        assert extractor_called == [[]]
        assert result["resolver"] is None
        assert result["extractors"]["characters"]["success"] is True

    @pytest.mark.asyncio
    async def test_resolver_cost_aggregated(self):
        """The resolution's counts and cost are in the result."""
        from services.extraction.orchestrator import (
            EXTRACTOR_MAP,
            run_resolve_and_extract,
            total_cost,
        )

        pool, _ = _mock_pool()
        usage = {"identity": {"calls": 1, "input_tokens": 1, "output_tokens": 1,
                              "cost_usd": 0.002}}

        async def mock_extractor_run(**kwargs):
            return {
                "type": "characters", "success": True, "stats": {},
                "cost": {"cost_usd": 0.01},
            }

        with (
            patch("services.extraction.orchestrator.resolve_phase",
                  AsyncMock(return_value=_resolution([], usage=usage))),
            patch.dict(EXTRACTOR_MAP, {"characters": _extractor_class(mock_extractor_run)}),
        ):
            result = await run_resolve_and_extract(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters"], session=SESSION,
                assistant_message_id=SAMPLE_MSG_ID,
                message_content="Le docteur vous examine.",
                narrator_deltas={},
            )

        assert result["resolver"]["cost_usd"] == 0.002
        assert {k: result["resolver"][k] for k in
                ("mentions", "deterministic", "escalated", "fallback", "unsure")} == {
            "mentions": 0, "deterministic": 0, "escalated": False, "fallback": False,
            "unsure": 0}
        assert total_cost(result) == pytest.approx(0.012)


# =============================================================================
# SCENE SECTION OF THE EXTRACTION PROMPTS
# =============================================================================


class TestSceneEntitiesSection:
    """The extractors see the scene by handle; examples come from the packs (#154)."""

    def test_lines_list_handles_types_labels_and_flags(self):
        from prompts.extraction.shared import SCENE_ENTITIES_HEADER, scene_entities_section
        from services.identity.lexicon import for_game

        section = scene_entities_section(SCENE, for_game("fr", None))
        assert SCENE_ENTITIES_HEADER in section
        assert "- E17 · character · Vieille au châle · unknown · existing" in section
        assert "- E21 · location · Halle aux Cordiers · known · new" in section
        assert "proposed_entities" in section

    def test_examples_come_from_the_game_language(self):
        from prompts.extraction.shared import scene_entities_section
        from services.identity.lexicon import for_game

        fr, en = for_game("fr", None), for_game("en", None)
        assert fr.extraction_examples[0].input in scene_entities_section([], fr)
        assert en.extraction_examples[0].input in scene_entities_section([], en)
        assert fr.extraction_examples[0].input not in scene_entities_section([], en)

    def test_genre_words_and_examples_replace_the_language_ones(self):
        from packs.loader import Example, GenreIdentity, GenrePack, load_lang
        from prompts.extraction.shared import scene_entities_section
        from services.identity.lexicon import Lexicon

        genre = GenrePack(slug="test", identity=GenreIdentity(
            entity_type_vocab={"location": ["comptoir", "relais"]},
            prompt_examples={"extraction": [Example(input="genre input", output="out")]},
        ))
        section = scene_entities_section([], Lexicon(load_lang("fr"), genre))
        assert "- location: comptoir, relais" in section
        assert "genre input" in section
        assert load_lang("fr").prompt_examples.extraction[0].input not in section

    def test_no_universe_example_in_the_extraction_prompts(self):
        """No name of a test world (world generation fixtures, the corpus-free examples
        of the tests) in any extraction system prompt, as a whole word, whatever the
        case: an example taken from a world is a universe rule."""
        import importlib
        import json
        import re
        from pathlib import Path

        from tests.characterization import payloads
        from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

        names = {payloads.NEW_CHARACTER_NAME}
        for world in (json.loads(payloads.WORLD_GEN), json.loads(WORLD_GENERATION_EXAMPLE)):
            names.add(world["world"]["name"])
            names |= {world["protagonist"]["name"], world["companion"]["name"]}
            for key in ("characters", "locations", "organizations", "inventory"):
                names |= {item["name"] for item in world.get(key, [])}
        assert len(names) > 10
        for module in ("characters_prompt", "locations_prompt", "organizations_prompt",
                       "inventory_prompt", "narrative_arcs_prompt"):
            prompt = importlib.import_module(f"prompts.extraction.{module}").SYSTEM_PROMPT
            found = {n for n in names
                     if re.search(rf"(?<!\w){re.escape(n.casefold())}(?!\w)",
                                  prompt.casefold())}
            assert found == set(), (module, found)
            assert "station spatiale" not in prompt and "IA de bord" not in prompt
            assert not prompt.startswith("Tu es")  # English instructions
            assert "entities_created" not in prompt
            assert "ENTITY RESOLUTION MAP" not in prompt and "MANDATORY" not in prompt

    async def test_an_extractor_prompt_lists_the_scene(self, test_pool, test_user):
        from tests.helpers import extractor_for

        extractor, _ = await extractor_for(test_pool, test_user, {})
        prompts = []

        async def fake_call(system_prompt, user_prompt, schema):
            prompts.append(user_prompt)
            return {}, None

        extractor._call_llm = fake_call
        await extractor.run("texte", {}, 1, scene_entities=SCENE)
        assert "- E17 · character · Vieille au châle · unknown · existing" in prompts[0]


class _CountingPool:
    """Real pool whose acquired connections are counted (`in_use`)."""

    def __init__(self, pool):
        self._pool = pool
        self.in_use = 0

    def acquire(self):
        outer = self

        class _Acquire:
            async def __aenter__(self):
                self._cm = outer._pool.acquire()
                conn = await self._cm.__aenter__()
                outer.in_use += 1
                return conn

            async def __aexit__(self, *exc):
                outer.in_use -= 1
                return await self._cm.__aexit__(*exc)

        return _Acquire()

    def __getattr__(self, name):
        return getattr(self._pool, name)


class TestExtractorConnections:
    """#94: an extractor holds no pool connection while the LLM call runs."""

    async def test_no_connection_is_held_across_the_llm_call(self, test_pool, test_user):
        from llm.session import LLMCall
        from services.extraction.characters import CharactersExtractor
        from services.game_service import GameService

        game_id = await GameService(test_pool).create_game(test_user["id"])
        pool = _CountingPool(test_pool)
        seen = []

        class _Session:
            async def extract_structured(self, **kwargs):
                seen.append(pool.in_use)
                assert pool.in_use == 0
                return LLMCall(value={"proposed_entities": []}, cost=None)

        result = await CharactersExtractor(pool, game_id, _Session()).run("texte", {}, 1)

        assert seen == [0]
        assert result["success"] is True


class TestExtractorErrorsDoNotLeakStory:
    """A pydantic error from an invalid item keeps its input_value out of logs and stats."""

    async def test_invalid_item_error_has_no_story_fragment(self, test_pool, test_user, caplog):
        import logging

        from services.extraction.characters import CharactersExtractor
        from services.game_service import GameService
        from tests.test_llm_session import FakeProvider
        from llm.session import LLMSession

        fragment = "Le dragon de verre murmure"
        game_id = await GameService(test_pool).create_game(test_user["id"])
        extractor = CharactersExtractor(test_pool, game_id,
                                        LLMSession.from_provider(FakeProvider()))

        async def fake_call(*args, **kwargs):
            return {"proposed_entities": [{"label": "Voss", "fields": fragment}]}, None

        extractor._call_llm = fake_call
        with caplog.at_level(logging.DEBUG):
            result = await extractor.run("texte", {}, 1)
        assert result["success"] is False and result["partial"] is True
        errors = result["stats"]["errors"]
        assert errors and "create:" in errors[0] and fragment not in errors[0]
        formatter = logging.Formatter()
        info_up = [r for r in caplog.records if r.levelno >= logging.INFO]
        assert fragment not in "\n".join(formatter.format(r) for r in info_up)
        async with test_pool.acquire() as conn:
            stored = await conn.fetchval(
                "SELECT errors FROM extraction_logs WHERE game_id = $1", game_id)
        assert stored and fragment not in " ".join(stored)


async def test_progression_failure_keeps_story_out_of_stats_and_logs(caplog):
    import logging

    from pydantic import BaseModel, ValidationError

    from services.extraction.progression import ProgressionExtractor

    fragment = "Le dragon de verre murmure"

    class _M(BaseModel):
        x: int

    class _Engine:
        async def apply_progression(self, conn, game_id, raw):
            _M.model_validate({"x": fragment})

    conn = MagicMock()  # savepoint start/rollback/commit and the probe statement
    conn.transaction.return_value = AsyncMock()
    conn.execute = AsyncMock()
    extractor = ProgressionExtractor.__new__(ProgressionExtractor)
    extractor._engine, extractor._engine_type, extractor.game_id = _Engine(), "fate_core", uuid4()
    extractor.extraction_type = "progression"
    with caplog.at_level(logging.INFO):
        stats = await extractor._populate(conn, {}, 1)
    assert stats["changes"] == {}
    [error] = stats["errors"]
    assert error.startswith("progression:") and "x: int_parsing" in error
    formatter = logging.Formatter()
    assert fragment not in error
    assert fragment not in "\n".join(formatter.format(r) for r in caplog.records)


def test_every_extractor_accepts_the_orchestrator_call():
    """A run() override missing a keyword the orchestrator passes would raise a TypeError
    that gather() swallows: that extraction would silently never run (#105)."""
    import inspect

    from services.extraction.orchestrator import EXTRACTOR_MAP

    for name, cls in EXTRACTOR_MAP.items():
        try:
            inspect.signature(cls.run).bind(
                None, message_content="m", narrator_deltas={}, trigger_cycle=1,
                scene_entities=[], source_message_id=None, turn_id=None)
        except TypeError as exc:
            pytest.fail(f"{name}: {exc}")


async def test_known_entities_are_listed_by_handle(test_pool, test_user):
    """The context lists of an extractor name each known entity by its handle first."""
    from config import get_identity_config
    from domain.identity import NewEntitySpec
    from services.identity.service import IdentityService
    from tests.helpers import extractor_for

    extractor, game_id = await extractor_for(test_pool, test_user, {})
    service = IdentityService(game_id, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        smith = await service.create_entity(
            conn, NewEntitySpec("character", "Maëlle Corvin", "proper_name"),
            turn_id=None, source="world_gen")
        handle = await conn.fetchval(
            "SELECT 'E' || handle FROM entity_registry WHERE id = $1", smith)
    prompts = []

    async def fake_call(system_prompt, user_prompt, schema):
        prompts.append(user_prompt)
        return {}, None

    extractor._call_llm = fake_call
    await extractor.run("texte", {}, 1)
    assert f"- {handle} · Maëlle Corvin" in prompts[0]
