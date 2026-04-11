"""
Tests for the entity resolver (context-propagation coreference resolution).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.extraction.resolver import (
    MentionMapping,
    ResolutionMap,
    _parse_resolution,
    _rebuild_annotated_text,
    build_span_annotations,
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

    def test_exact_match(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Voss", "character", False),
        ])
        assert rmap.get_canonical("le docteur") == "Dr. Voss"

    def test_case_insensitive(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("Le Docteur", "Dr. Voss", "character", False),
        ])
        assert rmap.get_canonical("le docteur") == "Dr. Voss"

    def test_no_match(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Voss", "character", False),
        ])
        assert rmap.get_canonical("le pilote") is None

    def test_multiple_mappings(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Voss", "character", False),
            MentionMapping("la médecin", "Dr. Voss", "character", False),
            MentionMapping("le bar", "Nebula Lounge", "location", False),
        ])
        assert rmap.get_canonical("le docteur") == "Dr. Voss"
        assert rmap.get_canonical("la médecin") == "Dr. Voss"
        assert rmap.get_canonical("le bar") == "Nebula Lounge"

    def test_to_prompt_section_existing(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Voss", "character", False),
            MentionMapping("la médecin", "Dr. Voss", "character", False),
        ])
        section = rmap.to_prompt_section()
        assert "EXISTING" in section
        assert "Dr. Voss" in section
        assert "le docteur" in section

    def test_to_prompt_section_new(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le mécanicien", "Marco", "character", True),
        ])
        section = rmap.to_prompt_section()
        assert "NEW" in section
        assert "Marco" in section

    def test_to_prompt_section_filter_type(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Voss", "character", False),
            MentionMapping("le bar", "Nebula Lounge", "location", False),
        ])
        char_section = rmap.to_prompt_section("character")
        assert "Dr. Voss" in char_section
        assert "Nebula" not in char_section

    def test_to_prompt_section_empty_filter(self):
        rmap = ResolutionMap(mappings=[
            MentionMapping("le docteur", "Dr. Voss", "character", False),
        ])
        section = rmap.to_prompt_section("organization")
        assert section == ""


# =============================================================================
# SPAN ANNOTATIONS
# =============================================================================


class TestBuildSpanAnnotations:
    """Tests for build_span_annotations."""

    def test_single_mention(self):
        text = "Je parle au docteur dans le couloir."
        rmap = ResolutionMap(mappings=[
            MentionMapping("docteur", "Dr. Voss", "character", False),
        ])
        annotations = build_span_annotations(text, rmap)
        assert len(annotations) == 1
        assert annotations[0][0] == 12  # start
        assert annotations[0][1] == 19  # end
        assert annotations[0][2] == "Dr. Voss"
        assert annotations[0][3] == "character"
        assert text[12:19] == "docteur"

    def test_multiple_occurrences(self):
        text = "Le docteur sourit. Le docteur parle."
        rmap = ResolutionMap(mappings=[
            MentionMapping("docteur", "Dr. Voss", "character", False),
        ])
        annotations = build_span_annotations(text, rmap)
        assert len(annotations) == 2

    def test_no_match(self):
        text = "Il fait beau sur la station."
        rmap = ResolutionMap(mappings=[
            MentionMapping("docteur", "Dr. Voss", "character", False),
        ])
        annotations = build_span_annotations(text, rmap)
        assert len(annotations) == 0

    def test_sorted_by_position(self):
        text = "Le bar est près du docteur."
        rmap = ResolutionMap(mappings=[
            MentionMapping("docteur", "Dr. Voss", "character", False),
            MentionMapping("bar", "Nebula Lounge", "location", False),
        ])
        annotations = build_span_annotations(text, rmap)
        assert len(annotations) == 2
        assert annotations[0][0] < annotations[1][0]  # sorted

    def test_case_insensitive_matching(self):
        text = "Le Docteur est là."
        rmap = ResolutionMap(mappings=[
            MentionMapping("docteur", "Dr. Voss", "character", False),
        ])
        annotations = build_span_annotations(text, rmap)
        assert len(annotations) == 1

    def test_empty_resolution_map(self):
        text = "Some text."
        rmap = ResolutionMap()
        annotations = build_span_annotations(text, rmap)
        assert annotations == []


# =============================================================================
# ANNOTATED TEXT REBUILD
# =============================================================================


class TestRebuildAnnotatedText:
    """Tests for _rebuild_annotated_text."""

    def test_single_annotation(self):
        text = "Le docteur sourit."
        annotations = [[3, 10, "Dr. Voss", "character"]]
        result = _rebuild_annotated_text(text, annotations)
        assert result == "Le docteur [= Dr. Voss] sourit."

    def test_multiple_annotations(self):
        text = "Le docteur va au bar."
        annotations = [
            [3, 10, "Dr. Voss", "character"],
            [17, 20, "Nebula Lounge", "location"],
        ]
        result = _rebuild_annotated_text(text, annotations)
        assert "[= Dr. Voss]" in result
        assert "[= Nebula Lounge]" in result

    def test_no_annotations(self):
        text = "Just some text."
        result = _rebuild_annotated_text(text, [])
        assert result == text

    def test_none_annotations(self):
        text = "Just some text."
        result = _rebuild_annotated_text(text, None)
        assert result == text


# =============================================================================
# PARSE RESOLUTION
# =============================================================================


class TestParseResolution:
    """Tests for _parse_resolution."""

    def test_existing_only(self):
        raw = {
            "existing": [
                {"mentions": ["le docteur", "Voss"], "canonical": "Dr. Voss", "entity_type": "character"}
            ],
            "new": [],
        }
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 2
        assert rmap.get_canonical("le docteur") == "Dr. Voss"
        assert rmap.get_canonical("Voss") == "Dr. Voss"
        assert not rmap.mappings[0].is_new

    def test_new_only(self):
        raw = {
            "existing": [],
            "new": [
                {"mentions": ["le mécanicien"], "suggested_name": "Marco", "entity_type": "character"}
            ],
        }
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 1
        assert rmap.get_canonical("le mécanicien") == "Marco"
        assert rmap.mappings[0].is_new

    def test_mixed(self):
        raw = {
            "existing": [
                {"mentions": ["le docteur"], "canonical": "Dr. Voss", "entity_type": "character"}
            ],
            "new": [
                {"mentions": ["le bar"], "suggested_name": "Café Nova", "entity_type": "location"}
            ],
        }
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 2

    def test_empty(self):
        raw = {"existing": [], "new": []}
        rmap = _parse_resolution(raw)
        assert len(rmap.mappings) == 0


# =============================================================================
# RESOLVE ENTITIES (integration with mocked LLM)
# =============================================================================


class TestResolveEntities:
    """Tests for the resolve_entities main entry point."""

    @pytest.mark.asyncio
    async def test_successful_resolution(self):
        """With previous annotations and LLM returning valid resolution."""
        mock_pool = MagicMock()

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
                previous_response="Le docteur [= Dr. Voss] vous accueille.",
                previous_annotations=[[3, 10, "Dr. Voss", "character"]],
                current_response="La médecin vous examine attentivement.",
            )

        assert result is not None
        assert len(result.mappings) == 2
        assert result.get_canonical("le docteur") == "Dr. Voss"
        assert result.get_canonical("la médecin") == "Dr. Voss"
        assert cost == {"cost_usd": 0.001}

    @pytest.mark.asyncio
    async def test_no_previous_annotations(self):
        """With no previous annotations, resolver still works (cold start)."""
        mock_pool = MagicMock()

        llm_response = {
            "existing": [],
            "new": [
                {"mentions": ["le pilote"], "suggested_name": "Karim", "entity_type": "character"}
            ],
        }

        with patch("services.extraction.resolver.get_llm_service") as mock_llm:
            mock_service = MagicMock()
            mock_service.extract_text = AsyncMock(return_value=llm_response)
            mock_service._last_call_cost = {"cost_usd": 0.001}
            mock_llm.return_value = mock_service

            result, cost = await resolve_entities(
                mock_pool,
                "00000000-0000-0000-0000-000000000000",
                previous_response="Il fait beau.",
                previous_annotations=None,
                current_response="Le pilote arrive.",
            )

        assert result is not None
        assert len(result.mappings) == 1
        assert result.mappings[0].is_new

    @pytest.mark.asyncio
    async def test_llm_returns_none(self):
        """When LLM returns None, resolver returns None gracefully."""
        mock_pool = MagicMock()

        with patch("services.extraction.resolver.get_llm_service") as mock_llm:
            mock_service = MagicMock()
            mock_service.extract_text = AsyncMock(return_value=None)
            mock_service._last_call_cost = None
            mock_llm.return_value = mock_service

            result, cost = await resolve_entities(
                mock_pool,
                "00000000-0000-0000-0000-000000000000",
                previous_response="Some text.",
                previous_annotations=None,
                current_response="More text.",
            )

        assert result is None
