"""
Tests for WorldGeneration.normalize_and_ensure_defaults model validator.
Pure unit tests — no DB needed.
"""

import copy
import pytest
from pydantic import ValidationError

from schema.world_generation import WorldGeneration


# =============================================================================
# HELPERS
# =============================================================================


def _minimal_data():
    return {
        "generation_seed_words": ["test", "seed", "words"],
        "world": {"name": "Test", "sectors": ["A", "B"], "founding_cycle": -3000},
        "protagonist": {
            "name": "Val", "departure_reason": "fresh_start",
            "skills": [{"name": "a", "level": 2}, {"name": "b", "level": 1}],
        },
        "companion": {"name": "Bot"},
        "characters": [],
        "locations": [
            {"name": "Hub", "location_type": "hub", "sector": "A",
             "description": "Main hub", "accessible": True},
        ],
        "organizations": [],
        "inventory": [
            {"name": "Item", "category": "misc", "description": "A thing",
             "transportable": True, "stackable": False, "base_value": 10, "quantity": 1},
        ],
        "narrative_arcs": [
            {"title": "Arc", "domain": "personal", "description": "An arc",
             "intensity": 3, "involved_entities": []},
        ],
        "initial_relations": [
            {"source_ref": "Val", "target_ref": "Hub",
             "relation_type": "lives_at", "known_by_protagonist": True},
        ],
        "arrival_event": {
            "arrival_method": "navette de transport",
            "arrival_location_ref": "Hub",
            "arrival_date": "Lundi 1er Janvier 2850",
            "time": "8h00",
            "immediate_sensory_details": [
                "L'air recyclé de la station",
                "Le bourdonnement des systèmes",
                "La lumière artificielle",
            ],
            "initial_mood": "Mélange d'appréhension et d'excitation",
            "immediate_need": "Trouver ses quartiers et s'orienter",
        },
    }


# =============================================================================
# HOISTING TESTS
# =============================================================================


class TestNormalizerHoisting:
    """Test that fields nested under 'world' are hoisted to top level."""

    def test_flat_structure_unchanged(self):
        """A properly flat structure passes through unchanged."""
        data = _minimal_data()
        wg = WorldGeneration.model_validate(data)
        assert wg.protagonist.name == "Val"
        assert wg.companion.name == "Bot"
        assert len(wg.locations) == 1
        assert wg.locations[0].name == "Hub"

    def test_hoists_characters_from_world(self):
        """Characters nested inside world.characters are hoisted to top level."""
        data = _minimal_data()
        data.pop("characters")
        data["world"]["characters"] = [
            {"name": "Alice", "known_by_protagonist": True},
        ]
        wg = WorldGeneration.model_validate(data)
        assert len(wg.characters) == 1
        assert wg.characters[0].name == "Alice"
        # world dict should no longer contain 'characters'
        assert "characters" not in data["world"]

    def test_hoists_locations_from_world(self):
        """Locations nested inside world.locations are hoisted to top level."""
        data = _minimal_data()
        data.pop("locations")
        data["world"]["locations"] = [
            {"name": "Dock", "location_type": "dock", "sector": "A",
             "description": "Arrival dock", "accessible": True},
        ]
        # arrival_event refs "Hub" which no longer exists — update to Dock
        data["arrival_event"]["arrival_location_ref"] = "Dock"
        data["initial_relations"][0]["target_ref"] = "Dock"
        wg = WorldGeneration.model_validate(data)
        assert len(wg.locations) == 1
        assert wg.locations[0].name == "Dock"

    def test_hoists_protagonist_from_world(self):
        """Protagonist nested inside world.protagonist is hoisted."""
        data = _minimal_data()
        data.pop("protagonist")
        data["world"]["protagonist"] = {
            "name": "Val", "departure_reason": "fresh_start",
            "skills": [{"name": "a", "level": 2}, {"name": "b", "level": 1}],
        }
        wg = WorldGeneration.model_validate(data)
        assert wg.protagonist.name == "Val"

    def test_hoists_companion_from_world(self):
        """Companion nested inside world.companion is hoisted."""
        data = _minimal_data()
        data.pop("companion")
        data["world"]["companion"] = {"name": "WorldBot"}
        wg = WorldGeneration.model_validate(data)
        assert wg.companion.name == "WorldBot"

    def test_hoists_multiple_fields(self):
        """Multiple fields nested under world are all hoisted."""
        data = _minimal_data()
        data.pop("characters")
        data.pop("organizations")
        data["world"]["characters"] = [{"name": "Bob"}]
        data["world"]["organizations"] = [
            {"name": "Corp", "org_type": "company"}
        ]
        wg = WorldGeneration.model_validate(data)
        assert len(wg.characters) == 1
        assert wg.characters[0].name == "Bob"
        assert len(wg.organizations) == 1
        assert wg.organizations[0].name == "Corp"

    def test_top_level_takes_precedence_over_nested(self):
        """If field exists at both top level and inside world, top level wins."""
        data = _minimal_data()
        # companion is at top level ("Bot") AND inside world
        data["world"]["companion"] = {"name": "WorldBot"}
        wg = WorldGeneration.model_validate(data)
        # Top-level companion should win
        assert wg.companion.name == "Bot"

    def test_hoists_narrative_arcs_from_world(self):
        """narrative_arcs nested inside world are hoisted."""
        data = _minimal_data()
        data.pop("narrative_arcs")
        data["world"]["narrative_arcs"] = [
            {"title": "WorldArc", "domain": "personal", "description": "Arc from world",
             "intensity": 2, "involved_entities": []},
        ]
        wg = WorldGeneration.model_validate(data)
        assert len(wg.narrative_arcs) == 1
        assert wg.narrative_arcs[0].title == "WorldArc"


# =============================================================================
# RENAME TESTS
# =============================================================================


class TestNormalizerRenames:
    """Test that variant field names are normalized."""

    def test_personal_assistant_renamed_to_companion(self):
        """personal_assistant field is renamed to companion."""
        data = _minimal_data()
        data.pop("companion")
        data["personal_assistant"] = {"name": "AssistantBot"}
        wg = WorldGeneration.model_validate(data)
        assert wg.companion.name == "AssistantBot"

    def test_personal_ai_renamed_to_companion(self):
        """personal_ai field is renamed to companion."""
        data = _minimal_data()
        data.pop("companion")
        data["personal_ai"] = {"name": "AiBot"}
        wg = WorldGeneration.model_validate(data)
        assert wg.companion.name == "AiBot"

    def test_global_narrative_arcs_renamed(self):
        """global_narrative_arcs is renamed to narrative_arcs."""
        data = _minimal_data()
        data.pop("narrative_arcs")
        data["global_narrative_arcs"] = [
            {"title": "GlobalArc", "domain": "personal", "description": "Renamed arc",
             "intensity": 4, "involved_entities": []},
        ]
        wg = WorldGeneration.model_validate(data)
        assert len(wg.narrative_arcs) == 1
        assert wg.narrative_arcs[0].title == "GlobalArc"

    def test_relations_renamed_to_initial_relations(self):
        """relations field is renamed to initial_relations."""
        data = _minimal_data()
        data.pop("initial_relations")
        data["relations"] = [
            {"source_ref": "Val", "target_ref": "Hub",
             "relation_type": "lives_at", "known_by_protagonist": True},
        ]
        wg = WorldGeneration.model_validate(data)
        assert len(wg.initial_relations) >= 1
        assert wg.initial_relations[0].source_ref == "Val"


# =============================================================================
# DEFAULTS TESTS
# =============================================================================


class TestNormalizerDefaults:
    """Test that defaults are created for missing optional fields."""

    def test_default_companion_created(self):
        """A default companion is created when companion is missing."""
        data = _minimal_data()
        data.pop("companion")
        wg = WorldGeneration.model_validate(data)
        assert wg.companion is not None
        assert wg.companion.name == "Assistant"

    def test_default_inventory_created(self):
        """A default inventory item is created when inventory is missing."""
        data = _minimal_data()
        data.pop("inventory")
        wg = WorldGeneration.model_validate(data)
        assert wg.inventory is not None
        assert len(wg.inventory) >= 1
        # Default item is a terminal
        assert wg.inventory[0].name == "Terminal personnel"

    def test_default_arrival_event_created(self):
        """A default arrival_event is created when it is missing."""
        data = _minimal_data()
        data.pop("arrival_event")
        wg = WorldGeneration.model_validate(data)
        assert wg.arrival_event is not None
        assert wg.arrival_event.arrival_method == "navette de transport"
        # arrival_location_ref should be set to an existing location
        assert wg.arrival_event.arrival_location_ref is not None

    def test_default_initial_relations_created(self):
        """Default relations are created from protagonist/character refs when missing."""
        data = _minimal_data()
        data["protagonist"]["residence_ref"] = "Hub"
        data.pop("initial_relations")
        wg = WorldGeneration.model_validate(data)
        assert wg.initial_relations is not None
        # Should have at least the protagonist->residence relation
        source_refs = [r.source_ref for r in wg.initial_relations]
        assert "Val" in source_refs

    def test_protagonist_extracted_from_characters(self):
        """Protagonist is extracted from characters list by station_arrival_cycle=0."""
        data = _minimal_data()
        data.pop("protagonist")
        # Protagonist embedded in characters with station_arrival_cycle=0
        data["characters"] = [
            {
                "name": "CharProtag",
                "station_arrival_cycle": 0,
                "departure_reason": "fresh_start",
                "skills": [{"name": "a", "level": 2}, {"name": "b", "level": 1}],
            },
            {"name": "Alice"},
        ]
        # Update relations to use the extracted protagonist name
        data["initial_relations"] = [
            {"source_ref": "CharProtag", "target_ref": "Hub",
             "relation_type": "lives_at", "known_by_protagonist": True},
        ]
        wg = WorldGeneration.model_validate(data)
        assert wg.protagonist.name == "CharProtag"
        # The protagonist should no longer be in characters
        char_names = [c.name for c in wg.characters]
        assert "CharProtag" not in char_names


# =============================================================================
# MISTRAL-LIKE COMPREHENSIVE TEST
# =============================================================================


class TestNormalizerMistralOutput:
    """Test realistic Mistral-like payload with all malformations combined."""

    def test_mistral_nested_wrong_names_protagonist_in_characters(self):
        """
        Comprehensive test: everything is nested under world, field names are wrong,
        protagonist is inside characters, companion is personal_ai.
        """
        payload = {
            "generation_seed_words": ["cosmos", "mystery", "trade"],
            "world": {
                "name": "Nexus Prime",
                "sectors": ["Core", "Rim", "Void"],
                "founding_cycle": -5000,
                # Characters nested under world (Mistral habit)
                "characters": [
                    # Protagonist by station_arrival_cycle=0
                    {
                        "name": "Zara",
                        "station_arrival_cycle": 0,
                        "departure_reason": "opportunity",
                        "skills": [
                            {"name": "combat", "level": 3},
                            {"name": "piloting", "level": 2},
                        ],
                    },
                    {"name": "Marcus", "known_by_protagonist": True,
                     "species": "human"},
                    {"name": "Lyra", "known_by_protagonist": False,
                     "species": "alien"},
                    {"name": "Rex", "known_by_protagonist": True,
                     "species": "android"},
                ],
                # Locations nested under world
                "locations": [
                    {"name": "Docking Bay 7", "location_type": "dock",
                     "sector": "Core", "description": "Main docking area",
                     "accessible": True},
                    {"name": "Market District", "location_type": "commercial",
                     "sector": "Rim", "description": "Trading hub",
                     "accessible": True},
                    {"name": "Zara's Quarters", "location_type": "quarters",
                     "sector": "Core", "description": "Living space",
                     "accessible": True},
                    {"name": "Council Hall", "location_type": "government",
                     "sector": "Core", "description": "Political center",
                     "accessible": False},
                ],
                # Wrong name: personal_ai instead of companion
                "personal_ai": {"name": "ARIA", "voice": "calme et analytique",
                                "traits": ["logique", "curieuse"]},
                # Wrong name: global_narrative_arcs instead of narrative_arcs
                "global_narrative_arcs": [
                    {"title": "La Conspiration", "domain": "political",
                     "description": "Something is brewing", "intensity": 5,
                     "involved_entities": []},
                    {"title": "L'Heritage", "domain": "personal",
                     "description": "Past catches up", "intensity": 4,
                     "involved_entities": []},
                    {"title": "Le Commerce", "domain": "economic",
                     "description": "Trade war starts", "intensity": 3,
                     "involved_entities": []},
                ],
                # Wrong name: relations instead of initial_relations
                "relations": [
                    {"source_ref": "Zara", "target_ref": "Docking Bay 7",
                     "relation_type": "lives_at", "known_by_protagonist": True},
                    {"source_ref": "Marcus", "target_ref": "Market District",
                     "relation_type": "works_at", "known_by_protagonist": True},
                ],
                # Organizations nested under world
                "organizations": [
                    {"name": "Trade Guild", "org_type": "guild",
                     "description": "Powerful merchants"},
                ],
                # Inventory nested under world
                "inventory": [
                    {"name": "Blaster", "category": "weapon",
                     "description": "Standard issue", "transportable": True,
                     "stackable": False, "base_value": 500, "quantity": 1},
                    {"name": "Medkit", "category": "medical",
                     "description": "First aid kit", "transportable": True,
                     "stackable": True, "base_value": 100, "quantity": 3},
                    {"name": "Credits chip", "category": "finance",
                     "description": "Digital currency", "transportable": True,
                     "stackable": False, "base_value": 1000, "quantity": 1},
                ],
            },
        }

        wg = WorldGeneration.model_validate(payload)

        # Protagonist was extracted from characters
        assert wg.protagonist.name == "Zara"

        # personal_ai was renamed to companion
        assert wg.companion.name == "ARIA"
        assert wg.companion.voice == "calme et analytique"

        # Characters no longer include Zara (protagonist extracted)
        char_names = [c.name for c in wg.characters]
        assert "Zara" not in char_names
        assert "Marcus" in char_names
        assert "Lyra" in char_names
        assert "Rex" in char_names

        # global_narrative_arcs was renamed to narrative_arcs
        arc_titles = [a.title for a in wg.narrative_arcs]
        assert "La Conspiration" in arc_titles
        assert "L'Heritage" in arc_titles

        # Locations were hoisted
        loc_names = [l.name for l in wg.locations]
        assert "Docking Bay 7" in loc_names
        assert "Market District" in loc_names

        # Inventory was hoisted
        item_names = [i.name for i in wg.inventory]
        assert "Blaster" in item_names
        assert "Medkit" in item_names

        # Organizations were hoisted
        assert len(wg.organizations) == 1
        assert wg.organizations[0].name == "Trade Guild"

        # Arrival event was auto-generated (not in payload)
        assert wg.arrival_event is not None
        # Should prefer dock location for arrival
        assert wg.arrival_event.arrival_location_ref == "Docking Bay 7"
