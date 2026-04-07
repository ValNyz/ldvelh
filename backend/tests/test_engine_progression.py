"""
Tests for Phase 7: Engine progression methods, progression extractor, and inventory extensions.
No DB or LLM calls — pure logic and schema validation.
"""

import pytest

from schema.extraction import (
    D6ProgressionExtraction,
    D6SkillUpgrade,
    ExtractionType,
    FateAspectRename,
    FateMilestoneExtraction,
    NarrativeTraitEvolution,
    ObjectCreation,
)
from services.engine import get_engine
from services.engine.base import BaseEngine
from services.engine.d6 import D6Engine, parse_dice_code
from services.engine.fate_core import FateCoreEngine
from services.engine.narrative import NarrativeEngine
from services.engine.none import NoneEngine


# =============================================================================
# SCHEMA VALIDATION
# =============================================================================


class TestProgressionSchemas:
    """Validate the progression Pydantic models."""

    def test_extraction_type_has_progression(self):
        assert ExtractionType.PROGRESSION == "progression"

    def test_d6_skill_upgrade(self):
        upgrade = D6SkillUpgrade(
            skill_name="Esquive",
            new_dice_value="4D",
            reason="Used frequently in combat",
        )
        assert upgrade.skill_name == "Esquive"
        assert upgrade.new_dice_value == "4D"

    def test_d6_progression_extraction(self):
        extraction = D6ProgressionExtraction(
            skill_upgrades=[
                D6SkillUpgrade(
                    skill_name="Esquive",
                    new_dice_value="4D+1",
                    reason="Many dodges this cycle",
                )
            ]
        )
        assert len(extraction.skill_upgrades) == 1

    def test_d6_progression_extraction_empty(self):
        extraction = D6ProgressionExtraction()
        assert extraction.skill_upgrades == []

    def test_fate_aspect_rename(self):
        rename = FateAspectRename(old_name="Méfiant", new_name="Confiant en ses alliés")
        assert rename.old_name == "Méfiant"

    def test_fate_milestone_extraction(self):
        extraction = FateMilestoneExtraction(
            milestone_type="significant",
            skill_upgrades=[{"skill_name": "Combat", "new_level": 4}],
            new_stunts=[{"name": "Riposte", "description": "Free attack on defense"}],
        )
        assert extraction.milestone_type == "significant"
        assert len(extraction.skill_upgrades) == 1
        assert len(extraction.new_stunts) == 1
        assert extraction.refresh_increase is False

    def test_fate_milestone_extraction_empty(self):
        extraction = FateMilestoneExtraction()
        assert extraction.milestone_type is None
        assert extraction.aspect_renames == []

    def test_narrative_trait_evolution(self):
        evolution = NarrativeTraitEvolution(
            new_traits=[{"name": "Déterminé", "description": "Refuses to give up"}],
            traits_deactivated=["Hésitant"],
            traits_replaced=[{
                "old_trait": "Novice",
                "new_trait_name": "Expérimenté",
                "new_trait_description": "Has seen much",
            }],
        )
        assert len(evolution.new_traits) == 1
        assert len(evolution.traits_deactivated) == 1
        assert len(evolution.traits_replaced) == 1

    def test_narrative_trait_evolution_empty(self):
        evolution = NarrativeTraitEvolution()
        assert evolution.new_traits == []
        assert evolution.traits_deactivated == []
        assert evolution.traits_replaced == []

    def test_object_creation_has_engine_data(self):
        obj = ObjectCreation(
            name="Blaster lourd",
            from_hint="Un blaster",
            engine_data={"stats": {"damage": "5D", "range": "medium"}},
        )
        assert obj.engine_data == {"stats": {"damage": "5D", "range": "medium"}}

    def test_object_creation_engine_data_none_by_default(self):
        obj = ObjectCreation(name="Stylo", from_hint="Un stylo")
        assert obj.engine_data is None


# =============================================================================
# ENGINE PROGRESSION METHODS
# =============================================================================


class TestNoneEngineProgression:
    """NoneEngine returns empty/no-op for all progression methods."""

    def test_no_progression_system_prompt(self):
        engine = NoneEngine()
        assert engine.get_progression_system_prompt() == ""

    def test_no_progression_user_prompt(self):
        engine = NoneEngine()
        assert engine.build_progression_user_prompt({}, [], "") == ""

    def test_no_progression_tool_schema(self):
        engine = NoneEngine()
        assert engine.get_progression_tool_schema() == {}

    def test_no_object_prompt_addon(self):
        engine = NoneEngine()
        assert engine.get_object_prompt_addon() == ""


class TestNarrativeEngineProgression:
    """NarrativeEngine progression: trait evolution."""

    def test_system_prompt_not_empty(self):
        engine = NarrativeEngine()
        prompt = engine.get_progression_system_prompt()
        assert len(prompt) > 50
        assert "traits" in prompt.lower()

    def test_user_prompt_includes_traits(self):
        engine = NarrativeEngine()
        stats = {"traits": [{"name": "Prudent", "description": "Always careful"}]}
        prompt = engine.build_progression_user_prompt(stats, [], "Some narrative")
        assert "Prudent" in prompt
        assert "Some narrative" in prompt

    def test_user_prompt_empty_traits(self):
        engine = NarrativeEngine()
        prompt = engine.build_progression_user_prompt({}, [], "")
        assert "(aucun trait)" in prompt

    def test_tool_schema_structure(self):
        engine = NarrativeEngine()
        schema = engine.get_progression_tool_schema()
        assert schema["type"] == "object"
        props = schema["properties"]
        assert "new_traits" in props
        assert "traits_deactivated" in props
        assert "traits_replaced" in props

    def test_object_prompt_addon_not_empty(self):
        engine = NarrativeEngine()
        addon = engine.get_object_prompt_addon()
        assert "narrative_description" in addon


class TestFateCoreEngineProgression:
    """FateCoreEngine progression: milestones."""

    def test_system_prompt_has_milestone_rules(self):
        engine = FateCoreEngine()
        prompt = engine.get_progression_system_prompt()
        assert "Minor" in prompt or "minor" in prompt
        assert "Significant" in prompt or "significant" in prompt
        assert "Major" in prompt or "major" in prompt

    def test_user_prompt_includes_skills(self):
        engine = FateCoreEngine()
        stats = {
            "aspects": [{"name": "Pilote hors pair", "type": "high_concept"}],
            "skills": [{"name": "Pilotage", "level": 4, "label": "Excellent"}],
            "stunts": [{"name": "As du vaisseau", "description": "+2 in space"}],
            "fate_points": 3,
            "refresh": 3,
        }
        rolls = [{"skill_used": "Pilotage", "outcome": "success"}]
        prompt = engine.build_progression_user_prompt(stats, rolls, "Some combat")
        assert "Pilote hors pair" in prompt
        assert "Pilotage" in prompt
        assert "As du vaisseau" in prompt
        assert "Some combat" in prompt

    def test_tool_schema_structure(self):
        engine = FateCoreEngine()
        schema = engine.get_progression_tool_schema()
        assert schema["type"] == "object"
        props = schema["properties"]
        assert "milestone_type" in props
        assert "aspect_renames" in props
        assert "new_stunts" in props
        assert "skill_upgrades" in props
        assert "refresh_increase" in props

    def test_object_prompt_addon_mentions_aspects(self):
        engine = FateCoreEngine()
        addon = engine.get_object_prompt_addon()
        assert "item_type" in addon
        assert "stunts" in addon


class TestD6EngineProgression:
    """D6Engine progression: skill dice upgrades."""

    def test_system_prompt_has_dice_rules(self):
        engine = D6Engine()
        prompt = engine.get_progression_system_prompt()
        assert "2D" in prompt
        assert "3D" in prompt
        assert "pip" in prompt.lower() or "Progression" in prompt

    def test_user_prompt_includes_skills(self):
        engine = D6Engine()
        stats = {
            "attributes": {"Dextérité": "3D", "Force": "2D+1"},
            "skills": [
                {"name": "Esquive", "attribute": "Dextérité", "dice_value": "4D"},
                {"name": "Bagarre", "attribute": "Force", "dice_value": "3D+2"},
            ],
        }
        rolls = [{"skill_used": "Esquive", "outcome": "success"}]
        prompt = engine.build_progression_user_prompt(stats, rolls, "A fight")
        assert "Esquive" in prompt
        assert "4D" in prompt
        assert "A fight" in prompt

    def test_tool_schema_structure(self):
        engine = D6Engine()
        schema = engine.get_progression_tool_schema()
        assert schema["type"] == "object"
        props = schema["properties"]
        assert "skill_upgrades" in props
        items = props["skill_upgrades"]["items"]
        assert "skill_name" in items["properties"]
        assert "new_dice_value" in items["properties"]
        assert "reason" in items["properties"]

    def test_object_prompt_addon_mentions_stats(self):
        engine = D6Engine()
        addon = engine.get_object_prompt_addon()
        assert "stats" in addon
        assert "damage" in addon.lower() or "D6" in addon or "4D" in addon


class TestD6DiceUpgradePath:
    """Test D6 dice code parsing used in progression upgrades."""

    def test_parse_basic_dice(self):
        assert parse_dice_code("3D") == (3, 0)

    def test_parse_dice_with_pips(self):
        assert parse_dice_code("3D+2") == (3, 2)

    def test_parse_lowercase(self):
        assert parse_dice_code("2d+1") == (2, 1)

    def test_parse_invalid(self):
        assert parse_dice_code("invalid") == (1, 0)


# =============================================================================
# BASE ENGINE DEFAULTS
# =============================================================================


class TestBaseEngineDefaults:
    """Verify that BaseEngine provides sensible defaults for new methods."""

    def test_defaults_via_none_engine(self):
        """NoneEngine inherits all defaults — verify they work."""
        engine = NoneEngine()
        assert engine.get_progression_system_prompt() == ""
        assert engine.build_progression_user_prompt({}, [], "") == ""
        assert engine.get_progression_tool_schema() == {}
        assert engine.get_object_prompt_addon() == ""


# =============================================================================
# ORCHESTRATOR REGISTRATION
# =============================================================================


class TestOrchestratorRegistration:
    """Verify progression extractor is registered in the orchestrator."""

    def test_progression_in_extractor_map(self):
        from services.extraction.orchestrator import EXTRACTOR_MAP
        assert "progression" in EXTRACTOR_MAP

    def test_progression_extractor_class(self):
        from services.extraction.orchestrator import EXTRACTOR_MAP
        from services.extraction.progression import ProgressionExtractor
        assert EXTRACTOR_MAP["progression"] is ProgressionExtractor

    def test_all_extractors_registered(self):
        """All ExtractionType values have a matching extractor."""
        from services.extraction.orchestrator import EXTRACTOR_MAP
        for et in ExtractionType:
            assert et.value in EXTRACTOR_MAP, f"ExtractionType.{et.name} not in EXTRACTOR_MAP"


# =============================================================================
# INVENTORY PROMPT ENGINE ADDON
# =============================================================================


class TestInventoryPromptEngineAddon:
    """Test that inventory prompt accepts engine addon."""

    def test_build_user_prompt_without_addon(self):
        from prompts.extraction.inventory_prompt import build_user_prompt
        prompt = build_user_prompt(
            narrative_texts=["Some text"],
            cycle=1,
            existing_canonical_names=["item_a"],
        )
        assert "ENGINE-SPECIFIC" not in prompt

    def test_build_user_prompt_with_addon(self):
        from prompts.extraction.inventory_prompt import build_user_prompt
        prompt = build_user_prompt(
            narrative_texts=["Some text"],
            cycle=1,
            existing_canonical_names=["item_a"],
            engine_object_addon='Add "engine_data": {"damage": "4D"} for weapons',
        )
        assert "ENGINE-SPECIFIC OBJECT DATA" in prompt
        assert "damage" in prompt
