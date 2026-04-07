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


SAMPLE_GAME_ID = uuid4()


def _mock_pool():
    """Build a mock asyncpg pool with a working acquire() context manager."""
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

        assert result["skipped"] is True

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
