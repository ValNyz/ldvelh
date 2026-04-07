"""
Tests for prompt builder functions.
No LLM calls, pure logic only.
"""

from prompts.extraction import EXTRACTOR_MODULES


# =============================================================================
# TESTS EXTRACTOR MODULES REGISTRY
# =============================================================================


class TestExtractorModules:
    """Tests for the EXTRACTOR_MODULES registry."""

    def test_all_extractors_registered(self):
        """All 5 extractor types are in the registry."""
        expected = {"characters", "locations", "organizations", "inventory", "narrative_arcs"}
        assert set(EXTRACTOR_MODULES.keys()) == expected

    def test_each_module_has_required_exports(self):
        """Each module exports SYSTEM_PROMPT, build_user_prompt, get_tool_schema."""
        for name, module in EXTRACTOR_MODULES.items():
            assert hasattr(module, "SYSTEM_PROMPT"), f"{name} missing SYSTEM_PROMPT"
            assert hasattr(module, "build_user_prompt"), f"{name} missing build_user_prompt"
            assert hasattr(module, "get_tool_schema"), f"{name} missing get_tool_schema"

    def test_system_prompts_are_non_empty_strings(self):
        """Each SYSTEM_PROMPT is a non-empty string."""
        for name, module in EXTRACTOR_MODULES.items():
            assert isinstance(module.SYSTEM_PROMPT, str), f"{name} SYSTEM_PROMPT not a string"
            assert len(module.SYSTEM_PROMPT) > 50, f"{name} SYSTEM_PROMPT too short"

    def test_tool_schemas_are_dicts(self):
        """Each get_tool_schema() returns a dict with expected keys."""
        for name, module in EXTRACTOR_MODULES.items():
            schema = module.get_tool_schema()
            assert isinstance(schema, dict), f"{name} schema not a dict"
            assert "properties" in schema or "type" in schema, f"{name} schema missing structure"


class TestExtractionExampleKeys:
    """Tests that extraction examples match documented keys."""

    def test_example_keys_match_documented_keys(self):
        """Keys in JSON examples match documented schema."""
        from prompts.examples import (
            EXTRACTION_PROTAGONIST_STATE_EXAMPLE,
            EXTRACTION_ENTITIES_EXAMPLE,
            EXTRACTION_FACTS_EXAMPLE,
            EXTRACTION_RELATIONS_EXAMPLE,
            EXTRACTION_ARCS_EXAMPLE,
            EXTRACTION_OBJECTS_EXAMPLE,
        )

        assert set(EXTRACTION_PROTAGONIST_STATE_EXAMPLE.keys()) == {
            "credit_transactions", "inventory_changes"
        }
        assert set(EXTRACTION_ENTITIES_EXAMPLE.keys()) == {
            "entities_created", "entities_updated"
        }
        assert set(EXTRACTION_FACTS_EXAMPLE.keys()) == {"facts"}
        assert set(EXTRACTION_RELATIONS_EXAMPLE.keys()) == {
            "relations_created", "relations_updated"
        }
        assert set(EXTRACTION_ARCS_EXAMPLE.keys()) == {
            "arcs_created", "arcs_resolved", "events_scheduled"
        }
        assert set(EXTRACTION_OBJECTS_EXAMPLE.keys()) == {"objects_created"}


# =============================================================================
# TESTS NARRATOR PROMPT BUILDER
# =============================================================================


class TestNarratorPromptBuilder:
    """Tests for build_narrator_context_prompt"""

    def _make_base_context(self, **overrides):
        """Helper to create a base NarrationContext"""
        from schema import (
            NarrationContext,
            LocationSummary,
            ProtagonistState,
        )

        defaults = dict(
            current_cycle=1,
            current_date="Lundi 1er Janvier 2847",
            current_time="10h00",
            current_location=LocationSummary(
                name="Le Quart de Cycle",
                type="cafe",
                sector="Quai Central",
                atmosphere="calme",
            ),
            protagonist=ProtagonistState(
                name="Valentin",
                credits=1500,
                hobbies=["lecture"],
            ),
            organizations=[],
            all_npcs=[],
            player_input="Je regarde autour de moi",
            world_name="Escale Méridienne",
            world_atmosphere="industrielle",
        )
        defaults.update(overrides)
        return NarrationContext(**defaults)

    def test_build_narrator_context_prompt_basic(self):
        """Builder generates a valid prompt"""
        from prompts.narrator_prompt import build_narrator_context_prompt

        context = self._make_base_context()
        prompt = build_narrator_context_prompt(context)

        assert "CONTEXTE ACTUEL" in prompt
        assert "TEMPS" in prompt
        assert "LIEU ACTUEL" in prompt
        assert "PROTAGONISTE" in prompt
        assert "ACTION DU JOUEUR" in prompt
        assert "Je regarde autour de moi" in prompt
        assert "Valentin" in prompt
        assert "Le Quart de Cycle" in prompt

    def test_requested_entity_details_rendered(self):
        """Requested entity details are rendered in prompt"""
        from prompts.narrator_prompt import build_narrator_context_prompt

        context = self._make_base_context(
            requested_entity_details={
                "Kess": {
                    "_entity_type": "character",
                    "description": "Mécanicienne talentueuse",
                    "occupation": "Ingénieure",
                    "species": "human",
                    "traits": ["pragmatique", "directe"],
                    "relation_level": 4,
                    "recent_facts": [
                        "A réparé le générateur du secteur Est",
                    ],
                },
                "Terminal 7": {
                    "_entity_type": "location",
                    "sector": "Quai Nord",
                    "atmosphere": "bruyant et animé",
                    "location_type": "bar",
                },
            }
        )

        prompt = build_narrator_context_prompt(context)

        assert "DÉTAILS DEMANDÉS" in prompt
        assert "Kess" in prompt
        assert "Mécanicienne talentueuse" in prompt
        assert "pragmatique" in prompt
        assert "niveau 4/10" in prompt
        assert "A réparé le générateur" in prompt
        assert "Terminal 7" in prompt
        assert "Quai Nord" in prompt

    def test_no_details_section_when_empty(self):
        """No DÉTAILS DEMANDÉS section when no details requested"""
        from prompts.narrator_prompt import build_narrator_context_prompt

        context = self._make_base_context()
        prompt = build_narrator_context_prompt(context)

        assert "DÉTAILS DEMANDÉS" not in prompt


# =============================================================================
# TESTS WORLD GENERATION PROMPT BUILDER
# =============================================================================


class TestWorldGenerationPromptBuilder:
    """Tests for world_generation_prompt functions"""

    def test_build_world_generation_user_prompt_default(self):
        """Builder generates a prompt with default sections"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt()

        assert "PERSONNAGE PRINCIPAL" in prompt
        assert "Valentin" in prompt
        assert "EMPLOI" in prompt
        assert "CHECKLIST FINALE" in prompt

    def test_build_world_generation_user_prompt_unemployed(self):
        """Builder handles unemployed mode"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(employer_preference="unemployed")

        assert "SANS emploi" in prompt

    def test_build_world_generation_user_prompt_with_mandatory_npcs(self):
        """Builder includes mandatory NPCs"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        mandatory = [
            {"name": "Alice", "age": 25, "gender": "femme", "romantic_potential": True}
        ]
        prompt = build_world_generation_user_prompt(mandatory_npcs=mandatory)

        assert "PNJ OBLIGATOIRES" in prompt
        assert "Alice" in prompt

    def test_get_full_generation_prompt_structure(self):
        """get_full_generation_prompt returns the right structure"""
        from prompts.world_generation_prompt import get_full_generation_prompt

        result = get_full_generation_prompt()

        assert "system" in result
        assert "user" in result
        assert len(result["system"]) > 100
        assert len(result["user"]) > 100

    # =================================================================
    # Engine-aware world generation prompt tests
    # =================================================================

    def test_engine_none_no_engine_section(self):
        """engine=none produces no engine section"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(engine="none")
        assert "MOTEUR DE JEU" not in prompt

    def test_engine_none_default_no_engine_section(self):
        """No engine param produces no engine section"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt()
        assert "MOTEUR DE JEU" not in prompt

    def test_engine_narrative_section(self):
        """engine=narrative adds narrative section"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(
            engine="narrative",
            world_config={"genre": "sci-fi", "difficulty": "moderate"},
        )
        assert "MOTEUR DE JEU" in prompt
        assert "Narratif" in prompt
        assert "traits narratifs" in prompt
        # Narrative engine should NOT ask for NPC stats
        assert "fate_skills" not in prompt
        assert "d6_attributes" not in prompt

    def test_engine_fate_core_section(self):
        """engine=fate_core adds Fate Core section with skills and NPC hints"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(
            engine="fate_core",
            world_config={"genre": "sci-fi", "difficulty": "hard"},
        )
        assert "MOTEUR DE JEU" in prompt
        assert "Fate Core" in prompt
        assert "fate_skills" in prompt
        assert "fate_aspects" in prompt
        # Should list actual skills
        assert "Athlétisme" in prompt
        assert "Technologie" in prompt  # sci-fi genre skill

    def test_engine_d6_section(self):
        """engine=d6 adds D6 System section with attributes and NPC hints"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(
            engine="d6",
            world_config={"genre": "sci-fi", "difficulty": "moderate"},
        )
        assert "MOTEUR DE JEU" in prompt
        assert "D6 System" in prompt
        assert "d6_attributes" in prompt
        assert "d6_skills" in prompt
        assert "Dextérité" in prompt

    def test_engine_with_lore(self):
        """World config lore is included in prompt"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(
            engine="fate_core",
            world_config={
                "genre": "cthulhu",
                "lore": "The station orbits a dead star. Strange whispers at night.",
            },
        )
        assert "Contexte supplémentaire" in prompt
        assert "dead star" in prompt

    def test_engine_with_custom_rules(self):
        """World config custom_rules is included"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(
            engine="d6",
            world_config={
                "genre": "sci-fi",
                "custom_rules": "No force users allowed",
            },
        )
        assert "Règles personnalisées" in prompt
        assert "No force users" in prompt

    def test_engine_hardcore_mode(self):
        """Hardcore flag adds brutal section"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(
            engine="narrative",
            world_config={"genre": "sci-fi", "hardcore": True},
        )
        assert "Mode Hardcore" in prompt
        assert "BRUTAL" in prompt

    def test_manual_entities_npcs(self):
        """Manual entities NPCs are included"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(
            manual_entities={
                "npcs": [
                    {"name": "Zara", "description": "A mysterious engineer"},
                ],
            },
        )
        assert "ENTITÉS IMPOSÉES" in prompt
        assert "Zara" in prompt
        assert "mysterious engineer" in prompt

    def test_manual_entities_locations_and_orgs(self):
        """Manual entities locations and orgs are included"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        prompt = build_world_generation_user_prompt(
            manual_entities={
                "locations": [
                    {"name": "The Void Bar", "description": "A hidden speakeasy"},
                ],
                "organizations": [
                    {"name": "Syndicate X", "description": "Shadowy group"},
                ],
            },
        )
        assert "Lieux imposés" in prompt
        assert "The Void Bar" in prompt
        assert "Organisations imposées" in prompt
        assert "Syndicate X" in prompt

    def test_get_full_generation_prompt_with_engine(self):
        """get_full_generation_prompt passes engine params through"""
        from prompts.world_generation_prompt import get_full_generation_prompt

        result = get_full_generation_prompt(
            engine="fate_core",
            world_config={"genre": "fantasy"},
        )
        assert "Fate Core" in result["user"]
        assert "Magie" in result["user"]  # fantasy genre skill

    def test_fate_genre_skills_vary(self):
        """Different genres produce different skill lists"""
        from prompts.world_generation_prompt import build_world_generation_user_prompt

        scifi = build_world_generation_user_prompt(
            engine="fate_core", world_config={"genre": "sci-fi"}
        )
        fantasy = build_world_generation_user_prompt(
            engine="fate_core", world_config={"genre": "fantasy"}
        )
        assert "Technologie" in scifi
        assert "Magie" in fantasy
        assert "Magie" not in scifi
