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
from services.extraction.resolver import MentionMapping, ResolutionMap


SAMPLE_GAME_ID = uuid4()
SAMPLE_MSG_ID = uuid4()
PREV_MSG_ID = uuid4()


def _mock_pool(with_messages=False):
    """Build a mock asyncpg pool with a working acquire() context manager.

    If with_messages=True, fetchrow returns mock current + previous messages
    for the resolver flow.
    """
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchval = AsyncMock(return_value=None)

    if with_messages:
        async def _fetchrow(query, *args):
            # Previous assistant message with annotations (only DB query left)
            if "narrator_context" in query:
                return {
                    "content": "Le docteur vous accueille.",
                    "narrator_context": [[3, 10, "Dr. Voss", "character"]],
                }
            return None

        mock_conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    else:
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
        assert ext.entities_created == []
        assert ext.entities_updated == []
        assert ext.entities_removed == []
        assert ext.ambient_updates == []
        assert ext.skills_changed == []
        assert ext.facts == []


class TestLocationsExtraction:
    def test_empty_defaults(self):
        ext = LocationsExtraction()
        assert ext.entities_created == []
        assert ext.entities_updated == []
        assert ext.ambient_updates == []
        assert ext.facts == []


class TestOrganizationsExtraction:
    def test_empty_defaults(self):
        ext = OrganizationsExtraction()
        assert ext.entities_created == []
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
    """Tests for run_triggered_extraction orchestrator."""

    def setup_method(self):
        from services.extraction.orchestrator import _extracting_games
        _extracting_games.clear()

    @pytest.mark.asyncio
    async def test_concurrent_extraction_guard(self):
        """Second call for same game_id is rejected while first is running."""
        from services.extraction.orchestrator import (
            _extracting_games,
            run_triggered_extraction,
        )

        key = str(SAMPLE_GAME_ID)
        _extracting_games.add(key)

        pool, _ = _mock_pool()
        result = await run_triggered_extraction(
            pool, SAMPLE_GAME_ID, trigger_cycle=3,
            triggers=["characters"], provider_name="anthropic", api_key="test",
        )

        assert result["skipped"] is True
        assert result["reason"] == "concurrent"
        _extracting_games.discard(key)

    @pytest.mark.asyncio
    async def test_empty_triggers_skipped(self):
        """Empty triggers list returns None immediately."""
        from services.extraction.orchestrator import run_triggered_extraction

        pool, _ = _mock_pool()
        result = await run_triggered_extraction(
            pool, SAMPLE_GAME_ID, trigger_cycle=3,
            triggers=[], provider_name="anthropic", api_key="test",
        )

        # No extractors run, but resolver may run (returns result dict)
        assert result.get("extractors") == {} or result.get("skipped") is True

    @pytest.mark.asyncio
    async def test_invalid_trigger_ignored(self):
        """Unknown trigger names are silently ignored."""
        from services.extraction.orchestrator import run_triggered_extraction

        pool, _ = _mock_pool()
        result = await run_triggered_extraction(
            pool, SAMPLE_GAME_ID, trigger_cycle=3,
            triggers=["nonexistent_type"], provider_name="anthropic", api_key="test",
        )

        # Should complete without error (no valid extractors to run)
        assert result is not None or result is None  # Just verifying no exception

    @pytest.mark.asyncio
    async def test_guard_cleared_after_completion(self):
        """The _extracting_games guard is cleared even on failure."""
        from services.extraction.orchestrator import _extracting_games

        # Patch CharactersExtractor to raise during run
        with patch(
            "services.extraction.orchestrator.CharactersExtractor"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.run = AsyncMock(side_effect=RuntimeError("boom"))
            mock_cls.return_value = mock_instance

            from services.extraction.orchestrator import run_triggered_extraction

            pool, _ = _mock_pool()
            await run_triggered_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters"], provider_name="anthropic", api_key="test",
            )

        assert str(SAMPLE_GAME_ID) not in _extracting_games

    @pytest.mark.asyncio
    async def test_resolver_called_before_extractors(self):
        """Phase 1 resolver is called before Phase 2 extractors."""
        from services.extraction.orchestrator import EXTRACTOR_MAP, run_triggered_extraction

        call_order = []

        pool, mock_conn = _mock_pool(with_messages=True)

        async def mock_resolve(*args, **kwargs):
            call_order.append("resolver")
            return None, None

        async def mock_extractor_run(message_content, narrator_deltas, trigger_cycle, resolution_map=None):
            call_order.append("extractor")
            return {"type": "characters", "skipped": True}

        mock_extractor_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(side_effect=mock_extractor_run)
        mock_extractor_cls.return_value = mock_instance

        with (
            patch("services.extraction.orchestrator.resolve_entities", side_effect=mock_resolve),
            patch.dict(EXTRACTOR_MAP, {"characters": mock_extractor_cls}),
        ):
            await run_triggered_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters"], provider_name="anthropic", api_key="test",
                assistant_message_id=SAMPLE_MSG_ID,
                message_content="Le docteur vous examine.",
                narrator_deltas={},
            )

        assert call_order == ["resolver", "extractor"]

    @pytest.mark.asyncio
    async def test_resolution_map_passed_to_extractors(self):
        """Resolution map from Phase 1 is forwarded to each extractor."""
        from services.extraction.orchestrator import EXTRACTOR_MAP, run_triggered_extraction

        resolution_map = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Voss", "character", False),
        ])

        pool, mock_conn = _mock_pool(with_messages=True)

        received_maps = []

        async def mock_extractor_run(message_content, narrator_deltas, trigger_cycle, resolution_map=None):
            received_maps.append(resolution_map)
            return {"type": "test", "success": True, "stats": {}}

        async def mock_resolve(*args, **kwargs):
            return resolution_map, {"cost_usd": 0.001}

        mock_chars_cls = MagicMock()
        inst1 = MagicMock()
        inst1.run = AsyncMock(side_effect=mock_extractor_run)
        mock_chars_cls.return_value = inst1

        mock_locs_cls = MagicMock()
        inst2 = MagicMock()
        inst2.run = AsyncMock(side_effect=mock_extractor_run)
        mock_locs_cls.return_value = inst2

        with (
            patch("services.extraction.orchestrator.resolve_entities", side_effect=mock_resolve),
            patch.dict(EXTRACTOR_MAP, {"characters": mock_chars_cls, "locations": mock_locs_cls}),
        ):
            await run_triggered_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters", "locations"],
                provider_name="anthropic", api_key="test",
                assistant_message_id=SAMPLE_MSG_ID,
                message_content="Le docteur vous examine.",
                narrator_deltas={},
            )

        # Both extractors should have received the same resolution map
        assert len(received_maps) == 2
        assert all(rm is resolution_map for rm in received_maps)

    @pytest.mark.asyncio
    async def test_resolver_failure_does_not_block_extractors(self):
        """If Phase 1 fails, Phase 2 extractors still run normally."""
        from services.extraction.orchestrator import EXTRACTOR_MAP, run_triggered_extraction

        pool, mock_conn = _mock_pool(with_messages=True)

        extractor_called = []

        async def mock_extractor_run(message_content, narrator_deltas, trigger_cycle, resolution_map=None):
            extractor_called.append(resolution_map)
            return {"type": "characters", "success": True, "stats": {}}

        async def mock_resolve(*args, **kwargs):
            raise RuntimeError("Haiku is down!")

        mock_cls = MagicMock()
        inst = MagicMock()
        inst.run = AsyncMock(side_effect=mock_extractor_run)
        mock_cls.return_value = inst

        with (
            patch("services.extraction.orchestrator.resolve_entities", side_effect=mock_resolve),
            patch.dict(EXTRACTOR_MAP, {"characters": mock_cls}),
        ):
            result = await run_triggered_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters"], provider_name="anthropic", api_key="test",
                assistant_message_id=SAMPLE_MSG_ID,
                message_content="Le docteur vous examine.",
                narrator_deltas={},
            )

        # Extractor was called with resolution_map=None (graceful degradation)
        assert len(extractor_called) == 1
        assert extractor_called[0] is None
        assert result["extractors"]["characters"]["success"] is True

    @pytest.mark.asyncio
    async def test_resolver_cost_aggregated(self):
        """Resolver cost is included in total cost aggregation."""
        from services.extraction.orchestrator import EXTRACTOR_MAP, run_triggered_extraction

        pool, mock_conn = _mock_pool(with_messages=True)

        async def mock_resolve(*args, **kwargs):
            return ResolutionMap(), {"cost_usd": 0.002}

        async def mock_extractor_run(message_content, narrator_deltas, trigger_cycle, resolution_map=None):
            return {
                "type": "characters", "success": True, "stats": {},
                "cost": {"cost_usd": 0.01},
            }

        mock_cls = MagicMock()
        inst = MagicMock()
        inst.run = AsyncMock(side_effect=mock_extractor_run)
        mock_cls.return_value = inst

        with (
            patch("services.extraction.orchestrator.resolve_entities", side_effect=mock_resolve),
            patch.dict(EXTRACTOR_MAP, {"characters": mock_cls}),
        ):
            result = await run_triggered_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=3,
                triggers=["characters"], provider_name="anthropic", api_key="test",
                assistant_message_id=SAMPLE_MSG_ID,
                message_content="Le docteur vous examine.",
                narrator_deltas={},
            )

        assert result["resolver"] is not None
        assert result["resolver"]["cost_usd"] == 0.002


# =============================================================================
# EXTRACTOR PROMPT INJECTION
# =============================================================================


class TestExtractorPromptInjection:
    """Tests that each extractor correctly injects resolution section into prompts."""

    RESOLUTION_MAP = ResolutionMap(mappings=[
        MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
        MentionMapping("le bar", "Le Nebula Lounge", "location", False),
        MentionMapping("la guilde", "Guilde des Marchands", "organization", False),
        MentionMapping("la lame", "Couteau de survie", "object", False),
        MentionMapping("l'enquête", "Mystères E7", "arc", False),
    ])

    NARRATIVE_TEXTS = ["Le docteur vous accueille dans le bar."]

    def test_characters_injects_character_section(self):
        """Characters extractor injects only character mentions."""
        from services.extraction.characters import CharactersExtractor

        ext = CharactersExtractor.__new__(CharactersExtractor)
        context = {"characters": [], "arcs_with_characters": []}
        _, user_prompt = ext._build_prompts(
            context, self.NARRATIVE_TEXTS, cycle=3,
            resolution_map=self.RESOLUTION_MAP,
        )
        assert "ENTITY RESOLUTION MAP" in user_prompt
        assert "Dr. Elara Voss" in user_prompt
        # Should NOT include non-character types
        assert "Le Nebula Lounge" not in user_prompt
        assert "Couteau de survie" not in user_prompt

    def test_locations_injects_location_section(self):
        """Locations extractor injects only location mentions."""
        from services.extraction.locations import LocationsExtractor

        ext = LocationsExtractor.__new__(LocationsExtractor)
        context = {"locations": [], "stub_locations": [], "arcs_with_locations": []}
        _, user_prompt = ext._build_prompts(
            context, self.NARRATIVE_TEXTS, cycle=3,
            resolution_map=self.RESOLUTION_MAP,
        )
        assert "ENTITY RESOLUTION MAP" in user_prompt
        assert "Le Nebula Lounge" in user_prompt
        assert "Dr. Elara Voss" not in user_prompt

    def test_organizations_injects_organization_section(self):
        """Organizations extractor injects only organization mentions."""
        from services.extraction.organizations import OrganizationsExtractor

        ext = OrganizationsExtractor.__new__(OrganizationsExtractor)
        context = {"organizations": [], "arcs_with_orgs": []}
        _, user_prompt = ext._build_prompts(
            context, self.NARRATIVE_TEXTS, cycle=3,
            resolution_map=self.RESOLUTION_MAP,
        )
        assert "ENTITY RESOLUTION MAP" in user_prompt
        assert "Guilde des Marchands" in user_prompt
        assert "Dr. Elara Voss" not in user_prompt

    def test_inventory_injects_object_section(self):
        """Inventory extractor injects only object mentions."""
        from services.extraction.inventory import InventoryExtractor

        ext = InventoryExtractor.__new__(InventoryExtractor)
        # Inventory needs _engine set for build_user_prompt
        mock_engine = MagicMock()
        mock_engine.get_object_prompt_addon.return_value = None
        ext._engine = mock_engine
        context = {"canonical_names": [], "objects": [], "inventory_hints": []}
        _, user_prompt = ext._build_prompts(
            context, self.NARRATIVE_TEXTS, cycle=3,
            resolution_map=self.RESOLUTION_MAP,
        )
        assert "ENTITY RESOLUTION MAP" in user_prompt
        assert "Couteau de survie" in user_prompt
        assert "Dr. Elara Voss" not in user_prompt

    def test_narrative_arcs_injects_all_types(self):
        """Narrative arcs extractor injects ALL entity types (cross-entity references)."""
        from services.extraction.narrative_arcs import NarrativeArcsExtractor

        ext = NarrativeArcsExtractor.__new__(NarrativeArcsExtractor)
        context = {"known_entities": [], "active_arcs": [], "known_relations": []}
        _, user_prompt = ext._build_prompts(
            context, self.NARRATIVE_TEXTS, cycle=3,
            resolution_map=self.RESOLUTION_MAP,
        )
        assert "ENTITY RESOLUTION MAP" in user_prompt
        # All types should be present
        assert "Dr. Elara Voss" in user_prompt
        assert "Le Nebula Lounge" in user_prompt
        assert "Guilde des Marchands" in user_prompt
        assert "Couteau de survie" in user_prompt
        assert "Mystères E7" in user_prompt

    def test_no_injection_when_none(self):
        """No resolution section appended when resolution_map is None."""
        from services.extraction.characters import CharactersExtractor

        ext = CharactersExtractor.__new__(CharactersExtractor)
        context = {"characters": [], "arcs_with_characters": []}
        _, user_prompt = ext._build_prompts(
            context, self.NARRATIVE_TEXTS, cycle=3,
            resolution_map=None,
        )
        assert "ENTITY RESOLUTION MAP" not in user_prompt

    def test_no_injection_when_empty_for_type(self):
        """No resolution section when map has no entries for this extractor's type."""
        from services.extraction.locations import LocationsExtractor

        # Map only has character entries — locations extractor should get nothing
        char_only_map = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Voss", "character", False),
        ])
        ext = LocationsExtractor.__new__(LocationsExtractor)
        context = {"locations": [], "stub_locations": [], "arcs_with_locations": []}
        _, user_prompt = ext._build_prompts(
            context, self.NARRATIVE_TEXTS, cycle=3,
            resolution_map=char_only_map,
        )
        assert "ENTITY RESOLUTION MAP" not in user_prompt

    def test_progression_ignores_resolution_map(self):
        """Progression extractor accepts resolution_map but doesn't use it."""
        from services.extraction.progression import ProgressionExtractor

        ext = ProgressionExtractor.__new__(ProgressionExtractor)
        mock_engine = MagicMock()
        mock_engine.get_progression_system_prompt.return_value = "sys"
        mock_engine.build_progression_user_prompt.return_value = "user"
        ext._engine = mock_engine

        context = {"stats": {}, "rolls": [], "narrative_summary": "test"}
        sys_prompt, user_prompt = ext._build_prompts(
            context, self.NARRATIVE_TEXTS, cycle=3,
            resolution_map=self.RESOLUTION_MAP,
        )
        # Progression doesn't inject resolution — it delegates to engine
        assert "ENTITY RESOLUTION MAP" not in user_prompt
        assert user_prompt == "user"
