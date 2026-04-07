"""
Tests for the entity resolver (Phase 1 pre-extraction disambiguation).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.extraction.resolver import (
    MentionMapping,
    ResolutionMap,
    _build_entity_catalog,
    _build_resolver_user_prompt,
    _format_catalog_section,
    _parse_resolution,
    resolve_entities,
)
from schema.extraction import EntityResolution, ResolvedMention, NewMention


# =============================================================================
# ResolutionMap UNIT TESTS
# =============================================================================


class TestResolutionMap:
    """Tests for ResolutionMap dataclass."""

    def test_empty_map(self):
        rmap = ResolutionMap()
        assert rmap.get_canonical("anything") is None
        assert rmap.to_prompt_section() == ""

    def test_get_canonical_exact(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
        ])
        assert rmap.get_canonical("le docteur") == "Dr. Elara Voss"

    def test_get_canonical_case_insensitive(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("Le Docteur", "Dr. Elara Voss", "character", False),
        ])
        assert rmap.get_canonical("le docteur") == "Dr. Elara Voss"
        assert rmap.get_canonical("LE DOCTEUR") == "Dr. Elara Voss"

    def test_get_canonical_miss(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
        ])
        assert rmap.get_canonical("le mécanicien") is None

    def test_to_prompt_section_existing(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
            MentionMapping("Voss", "Dr. Elara Voss", "character", False),
        ])
        section = rmap.to_prompt_section("character")
        assert "Dr. Elara Voss" in section
        assert '"le docteur"' in section
        assert '"Voss"' in section
        assert "EXISTING" in section
        assert "NEW" not in section

    def test_to_prompt_section_new(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le scientifique", "Le Scientifique", "character", True),
        ])
        section = rmap.to_prompt_section("character")
        assert "NEW" in section
        assert '"le scientifique"' in section
        assert "Le Scientifique" in section

    def test_to_prompt_section_mixed(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
            MentionMapping("le scientifique", "Le Scientifique", "character", True),
        ])
        section = rmap.to_prompt_section("character")
        assert "EXISTING" in section
        assert "NEW" in section

    def test_to_prompt_section_filter_by_type(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
            MentionMapping("le bar", "Le Nebula Lounge", "location", False),
        ])
        char_section = rmap.to_prompt_section("character")
        assert "Dr. Elara Voss" in char_section
        assert "Nebula Lounge" not in char_section

        loc_section = rmap.to_prompt_section("location")
        assert "Nebula Lounge" in loc_section
        assert "Dr. Elara Voss" not in loc_section

    def test_to_prompt_section_no_filter(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
            MentionMapping("le bar", "Le Nebula Lounge", "location", False),
        ])
        section = rmap.to_prompt_section(None)
        assert "Dr. Elara Voss" in section
        assert "Nebula Lounge" in section

    def test_to_prompt_section_empty_for_type(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
        ])
        assert rmap.to_prompt_section("location") == ""

    def test_groups_mentions_by_canonical(self):
        """Multiple mentions of the same entity grouped on one line."""
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Elara Voss", "character", False),
            MentionMapping("Voss", "Dr. Elara Voss", "character", False),
            MentionMapping("la médecin", "Dr. Elara Voss", "character", False),
        ])
        section = rmap.to_prompt_section("character")
        # All mentions should be on the same line with the canonical name
        lines = [l for l in section.split("\n") if "Dr. Elara Voss" in l]
        assert len(lines) == 1
        assert '"le docteur"' in lines[0]
        assert '"Voss"' in lines[0]
        assert '"la médecin"' in lines[0]


# =============================================================================
# PARSE RESOLUTION TESTS
# =============================================================================


class TestParseResolution:
    """Tests for _parse_resolution."""

    def test_parse_existing(self):
        raw = {
            "existing": [
                {
                    "mentions": ["le docteur", "Voss"],
                    "canonical": "Dr. Elara Voss",
                    "entity_type": "character",
                }
            ],
            "new": [],
        }
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 2
        assert rmap.get_canonical("le docteur") == "Dr. Elara Voss"
        assert rmap.get_canonical("Voss") == "Dr. Elara Voss"
        assert not rmap.mappings[0].is_new

    def test_parse_new(self):
        raw = {
            "existing": [],
            "new": [
                {
                    "mentions": ["le scientifique"],
                    "suggested_name": "Le Scientifique",
                    "entity_type": "character",
                }
            ],
        }
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 1
        assert rmap.get_canonical("le scientifique") == "Le Scientifique"
        assert rmap.mappings[0].is_new

    def test_parse_mixed(self):
        raw = {
            "existing": [
                {
                    "mentions": ["le bar"],
                    "canonical": "Le Nebula Lounge",
                    "entity_type": "location",
                }
            ],
            "new": [
                {
                    "mentions": ["la lame rouillée"],
                    "suggested_name": "Lame Rouillée",
                    "entity_type": "object",
                }
            ],
        }
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 2
        assert rmap.get_canonical("le bar") == "Le Nebula Lounge"
        assert rmap.get_canonical("la lame rouillée") == "Lame Rouillée"

    def test_parse_empty(self):
        raw = {"existing": [], "new": []}
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 0

    def test_parse_defaults_to_empty(self):
        raw = {}
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 0


# =============================================================================
# CATALOG FORMAT TESTS
# =============================================================================


class TestFormatCatalog:
    """Tests for _format_catalog_section."""

    def test_empty_catalog(self):
        assert _format_catalog_section({}) == ""

    def test_characters_only(self):
        catalog = {
            "character": [
                {"name": "Dr. Elara Voss", "occupation": "médecin",
                 "unknown_name": None, "species": None},
            ]
        }
        text = _format_catalog_section(catalog)
        assert "Dr. Elara Voss" in text
        assert "médecin" in text
        assert "Characters:" in text

    def test_locations_with_sector(self):
        catalog = {
            "location": [
                {"name": "Le Nebula Lounge", "location_type": "bar",
                 "sector": "Loisirs"},
            ]
        }
        text = _format_catalog_section(catalog)
        assert "Le Nebula Lounge" in text
        assert "Loisirs" in text

    def test_objects_with_category(self):
        catalog = {
            "object": [
                {"name": "Couteau de survie", "category": "arme"},
            ]
        }
        text = _format_catalog_section(catalog)
        assert "Couteau de survie" in text
        assert "arme" in text

    def test_arcs_with_domain(self):
        catalog = {
            "arc": [
                {"title": "Mystères des couloirs E7", "domain": "enquête"},
            ]
        }
        text = _format_catalog_section(catalog)
        assert "Mystères des couloirs E7" in text
        assert "enquête" in text

    def test_multi_type(self):
        catalog = {
            "character": [
                {"name": "Kael", "occupation": "mécanicien",
                 "unknown_name": None, "species": None}
            ],
            "location": [
                {"name": "Hangar 7", "location_type": "hangar", "sector": None}
            ],
        }
        text = _format_catalog_section(catalog)
        assert "Characters:" in text
        assert "Locations:" in text
        assert "Kael" in text
        assert "Hangar 7" in text


# =============================================================================
# USER PROMPT TESTS
# =============================================================================


class TestBuildUserPrompt:
    """Tests for _build_resolver_user_prompt."""

    def test_basic_structure(self):
        catalog = {
            "character": [
                {"name": "Dr. Voss", "occupation": "médecin",
                 "unknown_name": None, "species": None}
            ],
        }
        messages = [
            {"role": "assistant", "content": "La docteur vous accueille."},
            {"role": "user", "content": "Je lui parle."},
        ]
        prompt = _build_resolver_user_prompt(catalog, messages)
        assert "KNOWN ENTITIES" in prompt
        assert "RECENT SCENE" in prompt
        assert "[assistant]" in prompt
        assert "[user]" in prompt
        assert "La docteur vous accueille." in prompt

    def test_empty_catalog(self):
        catalog = {}
        messages = [{"role": "assistant", "content": "Hello."}]
        prompt = _build_resolver_user_prompt(catalog, messages)
        assert "No entities in database yet" in prompt

    def test_empty_messages(self):
        catalog = {"character": [
            {"name": "Test", "occupation": None, "unknown_name": None, "species": None}
        ]}
        prompt = _build_resolver_user_prompt(catalog, [])
        assert "RECENT SCENE" in prompt


# =============================================================================
# SCHEMA MODELS TESTS
# =============================================================================


class TestSchemaModels:
    """Tests for EntityResolution pydantic models."""

    def test_resolved_mention_valid(self):
        m = ResolvedMention(
            mentions=["le docteur", "Voss"],
            canonical="Dr. Elara Voss",
            entity_type="character",
        )
        assert m.mentions == ["le docteur", "Voss"]
        assert m.canonical == "Dr. Elara Voss"

    def test_resolved_mention_empty_mentions(self):
        with pytest.raises(Exception):
            ResolvedMention(
                mentions=[],
                canonical="Dr. Elara Voss",
                entity_type="character",
            )

    def test_new_mention_valid(self):
        m = NewMention(
            mentions=["le scientifique"],
            suggested_name="Le Scientifique",
            entity_type="character",
        )
        assert m.suggested_name == "Le Scientifique"

    def test_entity_resolution_defaults(self):
        r = EntityResolution()
        assert r.existing == []
        assert r.new == []

    def test_entity_resolution_full(self):
        r = EntityResolution(
            existing=[
                ResolvedMention(
                    mentions=["le docteur"],
                    canonical="Dr. Voss",
                    entity_type="character",
                )
            ],
            new=[
                NewMention(
                    mentions=["le robot"],
                    suggested_name="Robot Gardien",
                    entity_type="character",
                )
            ],
        )
        assert len(r.existing) == 1
        assert len(r.new) == 1


# =============================================================================
# RESOLVE_ENTITIES INTEGRATION TESTS (mocked LLM)
# =============================================================================


def _make_mock_pool(mock_conn):
    """Create a properly mocked asyncpg Pool with async context manager support."""
    mock_pool = MagicMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = cm
    return mock_pool


class TestResolveEntities:
    """Tests for the resolve_entities main entry point."""

    @pytest.mark.asyncio
    async def test_empty_catalog_skips(self):
        """With no entities in DB, resolver should skip."""
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = _make_mock_pool(mock_conn)

        result, cost = await resolve_entities(
            mock_pool, "00000000-0000-0000-0000-000000000000",
            [{"role": "assistant", "content": "Some text"}],
        )
        assert result is None
        assert cost is None

    @pytest.mark.asyncio
    async def test_successful_resolution(self):
        """With entities in DB and LLM returning valid resolution."""
        mock_conn = AsyncMock()

        async def mock_fetch(query, *args):
            if "characters" in query.lower():
                return [{"name": "Dr. Voss", "known_by_protagonist": True,
                         "unknown_name": None, "species": None, "gender": None,
                         "pronouns": None, "age": None, "description": None,
                         "traits": None, "mood": None, "occupation": "médecin",
                         "origin": None, "romantic_potential": None,
                         "is_mandatory": False, "ambient": None,
                         "workplace_name": None, "residence_name": None,
                         "relation_level": None, "relation_context": None,
                         "usual_location": None, "id": "some-id"}]
            return []

        mock_conn.fetch = AsyncMock(side_effect=mock_fetch)
        mock_pool = _make_mock_pool(mock_conn)

        llm_response = {
            "existing": [
                {
                    "mentions": ["le docteur", "la médecin"],
                    "canonical": "Dr. Voss",
                    "entity_type": "character",
                }
            ],
            "new": [],
        }

        with patch("services.extraction.resolver.get_llm_service") as mock_llm:
            mock_service = MagicMock()
            mock_service.extract_text = AsyncMock(return_value=llm_response)
            mock_service._last_call_cost = {"cost_usd": 0.001}
            mock_llm.return_value = mock_service

            result, cost = await resolve_entities(
                mock_pool,
                "00000000-0000-0000-0000-000000000000",
                [{"role": "assistant", "content": "Le docteur vous accueille."}],
            )

        assert result is not None
        assert len(result.mappings) == 2
        assert result.get_canonical("le docteur") == "Dr. Voss"
        assert result.get_canonical("la médecin") == "Dr. Voss"
        assert cost == {"cost_usd": 0.001}

    @pytest.mark.asyncio
    async def test_llm_returns_none(self):
        """When LLM returns None, resolver returns None gracefully."""
        mock_conn = AsyncMock()

        async def mock_fetch(query, *args):
            if "characters" in query.lower():
                return [{"name": "Test", "known_by_protagonist": True,
                         "unknown_name": None, "species": None, "gender": None,
                         "pronouns": None, "age": None, "description": None,
                         "traits": None, "mood": None, "occupation": None,
                         "origin": None, "romantic_potential": None,
                         "is_mandatory": False, "ambient": None,
                         "workplace_name": None, "residence_name": None,
                         "relation_level": None, "relation_context": None,
                         "usual_location": None, "id": "id"}]
            return []

        mock_conn.fetch = AsyncMock(side_effect=mock_fetch)
        mock_pool = _make_mock_pool(mock_conn)

        with patch("services.extraction.resolver.get_llm_service") as mock_llm:
            mock_service = MagicMock()
            mock_service.extract_text = AsyncMock(return_value=None)
            mock_service._last_call_cost = None
            mock_llm.return_value = mock_service

            result, cost = await resolve_entities(
                mock_pool,
                "00000000-0000-0000-0000-000000000000",
                [{"role": "assistant", "content": "Text"}],
            )

        assert result is None
