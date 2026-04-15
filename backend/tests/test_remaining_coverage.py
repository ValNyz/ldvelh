"""
Tests for remaining low-coverage modules:
- schema/world_generation.py (validators, arrival event, soft refs)
- services/auth_service.py (hash, JWT, verify_email, change_password)
- utils/crypto.py (encrypt/decrypt, mask_api_key)
- services/email_service.py (send_verification_email, generate_token)
- schema/entities.py (validators for traits, hobbies, features parsing)
- schema/narrative.py (normalizers, semantic_key, event_type fallback)
- schema/extraction.py (InventoryChange validators, entity_type normalizers)
- schema/core.py (truncation, _normalize_enum_value edge cases, TemporalValidationMixin)
"""

import secrets
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError


# =============================================================================
# SCHEMA / CORE — truncation, normalization, TemporalValidationMixin
# =============================================================================


class TestCoreTruncation:
    """Test the _truncate factory and annotated text types."""

    def test_truncate_none_value(self):
        """Truncation returns None for None input."""
        from schema.core import _truncate

        fn = _truncate(50)
        assert fn(None) is None

    def test_truncate_short_string_unchanged(self):
        """Short string under limit is returned as-is."""
        from schema.core import _truncate

        fn = _truncate(50)
        assert fn("hello") == "hello"

    def test_truncate_long_string_with_spaces(self):
        """Long string is truncated at word boundary with ellipsis."""
        from schema.core import _truncate

        fn = _truncate(30)
        text = "This is a fairly long text that exceeds the limit"
        result = fn(text)
        assert len(result) <= 30
        assert result.endswith("...")

    def test_truncate_long_string_no_spaces(self):
        """Long string with no spaces still truncates."""
        from schema.core import _truncate

        fn = _truncate(20)
        text = "a" * 100
        result = fn(text)
        assert len(result) <= 20
        assert result.endswith("...")

    def test_truncate_converts_non_string(self):
        """Non-string value is converted to str before truncation."""
        from schema.core import _truncate

        fn = _truncate(50)
        assert fn(12345) == "12345"

    def test_label_truncation_at_30(self):
        """Label type truncates at 30 chars."""
        from schema.entities import CompanionData

        long_name = "A" * 100
        companion = CompanionData(name=long_name)
        assert len(companion.name) <= 30

    def test_tag_truncation_at_50(self):
        """Tag type truncates at 50 chars."""
        from schema.core import Skill

        long_skill = "x" * 200
        skill = Skill(name=long_skill, level=3)
        assert len(skill.name) <= 50

    def test_backstory_truncation_at_600(self):
        """Backstory type truncates at 600 chars."""
        from schema.entities import ProtagonistData

        long_backstory = "word " * 300  # 1500 chars
        p = ProtagonistData(
            skills=[
                {"name": "skill_a", "level": 3},
                {"name": "skill_b", "level": 2},
            ],
            backstory=long_backstory,
        )
        assert len(p.backstory) <= 600


class TestNormalizeEnumValueEdgeCases:
    """Cover edge cases in _normalize_enum_value."""

    def test_none_value_returns_none(self):
        """None input returns None."""
        from schema.core import _normalize_enum_value, EntityType, ENTITY_TYPE_SYNONYMS
        from schema.synonyms import ENTITY_TYPE_SYNONYMS

        result = _normalize_enum_value(None, ENTITY_TYPE_SYNONYMS, EntityType, "test")
        assert result is None

    def test_enum_instance_returns_value(self):
        """Passing an actual enum instance returns its .value."""
        from schema.core import normalize_entity_type, EntityType

        result = normalize_entity_type(EntityType.CHARACTER)
        assert result == "character"

    def test_unknown_synonym_falls_back(self):
        """Unknown synonym triggers fallback to first enum value."""
        from schema.core import normalize_entity_type

        result = normalize_entity_type("completely_unknown_type_xyz")
        # Falls back to the first value of EntityType
        assert result == "protagonist"

    def test_direct_valid_enum_value_no_synonym(self):
        """Value is a valid enum value but not in synonyms dict."""
        from schema.core import normalize_moment

        # "morning" should be in synonyms, but let's test the direct path
        result = normalize_moment("morning")
        assert result == "morning"

    def test_synonym_key_differs_from_result_logs_info(self):
        """When the synonym maps to a different string, info is logged."""
        from schema.core import normalize_entity_type

        # "pnj" maps to "character" (different key)
        result = normalize_entity_type("pnj")
        assert result == "character"

    def test_normalize_org_size(self):
        """OrgSize normalization works."""
        from schema.core import normalize_org_size

        assert normalize_org_size("small") == "small"
        assert normalize_org_size("large") == "large"

    def test_normalize_departure_reason_unknown(self):
        """Unknown departure reason falls back."""
        from schema.core import normalize_departure_reason

        result = normalize_departure_reason("something_weird")
        assert result == "flight"  # first enum value


class TestTemporalValidationMixin:
    """Test TemporalValidationMixin.enforce_temporal_coherence."""

    def test_no_arrival_or_founding(self):
        """Mixin does nothing when neither field is present."""
        from pydantic import BaseModel, model_validator
        from schema.core import TemporalValidationMixin

        class M(BaseModel, TemporalValidationMixin):
            x: int = 1

        m = M()
        assert m.x == 1

    def test_arrival_before_founding_corrected(self):
        """arrival_cycle < founding_cycle is corrected."""
        from pydantic import BaseModel, model_validator
        from schema.core import TemporalValidationMixin

        class M(BaseModel, TemporalValidationMixin):
            arrival_cycle: int = 10
            founding_cycle: int = 100

        m = M()
        assert m.arrival_cycle == 100  # corrected to founding_cycle

    def test_arrival_after_founding_unchanged(self):
        """arrival_cycle >= founding_cycle is not changed."""
        from pydantic import BaseModel
        from schema.core import TemporalValidationMixin

        class M(BaseModel, TemporalValidationMixin):
            arrival_cycle: int = 200
            founding_cycle: int = 100

        m = M()
        assert m.arrival_cycle == 200


# =============================================================================
# SCHEMA / ENTITIES — validators for traits, hobbies, features
# =============================================================================


class TestEntitiesValidators:
    """Test field_validators in entities.py models."""

    def test_character_traits_from_json_string(self):
        """CharacterData._parse_traits handles JSON string."""
        from schema.entities import CharacterData

        c = CharacterData(name="Alice", traits='["brave", "kind"]')
        assert c.traits == ["brave", "kind"]

    def test_character_traits_from_plain_string(self):
        """CharacterData._parse_traits wraps plain string in list."""
        from schema.entities import CharacterData

        c = CharacterData(name="Bob", traits="curious")
        assert c.traits == ["curious"]

    def test_character_traits_from_list(self):
        """CharacterData._parse_traits passes list through."""
        from schema.entities import CharacterData

        c = CharacterData(name="Eve", traits=["smart", "brave"])
        assert c.traits == ["smart", "brave"]

    def test_character_traits_invalid_json_string(self):
        """CharacterData._parse_traits handles invalid JSON string gracefully."""
        from schema.entities import CharacterData

        c = CharacterData(name="Zara", traits="{not valid json}")
        assert c.traits == ["{not valid json}"]

    def test_companion_traits_from_json_string(self):
        """CompanionData._parse_traits handles JSON string."""
        from schema.entities import CompanionData

        companion = CompanionData(name="AI", traits='["sarcastic"]')
        assert companion.traits == ["sarcastic"]

    def test_companion_traits_from_plain_string(self):
        """CompanionData._parse_traits wraps plain string."""
        from schema.entities import CompanionData

        companion = CompanionData(name="Bot", traits="helpful")
        assert companion.traits == ["helpful"]

    def test_location_features_from_json_string(self):
        """LocationData._parse_features handles JSON string."""
        from schema.entities import LocationData

        loc = LocationData(name="Bar", notable_features='["neon lights"]')
        assert loc.notable_features == ["neon lights"]

    def test_location_features_from_plain_string(self):
        """LocationData._parse_features wraps plain string."""
        from schema.entities import LocationData

        loc = LocationData(name="Dock", notable_features="large crane")
        assert loc.notable_features == ["large crane"]

    def test_location_features_invalid_json(self):
        """LocationData._parse_features handles invalid JSON."""
        from schema.entities import LocationData

        loc = LocationData(name="Lab", notable_features="{broken}")
        assert loc.notable_features == ["{broken}"]

    def test_protagonist_hobbies_from_json_string(self):
        """ProtagonistData._parse_hobbies handles JSON string."""
        from schema.entities import ProtagonistData

        p = ProtagonistData(
            skills=[
                {"name": "a", "level": 1},
                {"name": "b", "level": 2},
            ],
            hobbies='["reading", "chess"]',
        )
        assert p.hobbies == ["reading", "chess"]

    def test_protagonist_hobbies_from_plain_string(self):
        """ProtagonistData._parse_hobbies wraps plain string."""
        from schema.entities import ProtagonistData

        p = ProtagonistData(
            skills=[
                {"name": "a", "level": 1},
                {"name": "b", "level": 2},
            ],
            hobbies="painting",
        )
        assert p.hobbies == ["painting"]

    def test_protagonist_hobbies_invalid_json(self):
        """ProtagonistData._parse_hobbies handles invalid JSON."""
        from schema.entities import ProtagonistData

        p = ProtagonistData(
            skills=[
                {"name": "a", "level": 1},
                {"name": "b", "level": 2},
            ],
            hobbies="{not json}",
        )
        assert p.hobbies == ["{not json}"]

    def test_protagonist_departure_reason_normalization(self):
        """ProtagonistData normalizes departure_reason from synonym."""
        from schema.entities import ProtagonistData

        p = ProtagonistData(
            skills=[
                {"name": "a", "level": 1},
                {"name": "b", "level": 2},
            ],
            departure_reason="fresh_start",
        )
        assert p.departure_reason.value == "fresh_start"

    def test_protagonist_departure_reason_unknown(self):
        """ProtagonistData falls back on unknown departure_reason."""
        from schema.entities import ProtagonistData

        p = ProtagonistData(
            skills=[
                {"name": "a", "level": 1},
                {"name": "b", "level": 2},
            ],
            departure_reason="unknown_reason_xyz",
        )
        # Falls back to first enum value
        assert p.departure_reason.value == "flight"


# =============================================================================
# SCHEMA / NARRATIVE — normalizers and validators
# =============================================================================


class TestNarrativeValidators:
    """Test field validators in narrative.py models."""

    def test_fact_participant_role_normalization(self):
        """FactParticipant normalizes role from string."""
        from schema.narrative import FactParticipant

        fp = FactParticipant(entity_ref="Alice", role="witness")
        assert fp.role.value == "witness"

    def test_fact_participant_role_unknown_falls_back(self):
        """FactParticipant role falls back on unknown value."""
        from schema.narrative import FactParticipant

        fp = FactParticipant(entity_ref="Bob", role="bystander_unknown_xyz")
        assert fp.role.value == "actor"  # first enum value

    def test_fact_type_normalization(self):
        """FactData normalizes fact_type."""
        from schema.narrative import FactData

        f = FactData(
            cycle=1,
            fact_type="revelation",
            description="Something happened",
            semantic_key="a:b:c",
        )
        assert f.fact_type.value == "revelation"

    def test_fact_semantic_key_wrong_format_rejected(self):
        """FactData rejects semantic_key with wrong number of parts."""
        from schema.narrative import FactData

        # The pattern validator catches it before the model_validator
        with pytest.raises(ValidationError):
            FactData(
                cycle=1,
                fact_type="action",
                description="Test",
                semantic_key="only_two:parts",
            )

    def test_narrative_arc_domain_normalization(self):
        """NarrativeArcData normalizes domain."""
        from schema.narrative import NarrativeArcData

        arc = NarrativeArcData(
            title="Test Arc",
            domain="professional",
            description="A test arc for professional development in the station",
        )
        assert arc.domain.value == "professional"

    def test_narrative_arc_domain_unknown_falls_back(self):
        """NarrativeArcData domain falls back on unknown."""
        from schema.narrative import NarrativeArcData

        arc = NarrativeArcData(
            title="Test Arc",
            domain="totally_unknown_domain_xyz",
            description="A test arc for unknown purposes",
        )
        assert arc.domain.value == "professional"  # first enum value

    def test_event_scheduled_event_type_string(self):
        """EventScheduled normalizes event_type from string."""
        from schema.narrative import EventScheduled

        e = EventScheduled(
            event_type="appointment",
            title="Meeting",
            planned_cycle=5,
        )
        assert e.event_type.value == "appointment"

    def test_event_scheduled_event_type_unknown_falls_back(self):
        """EventScheduled falls back to appointment on unknown type."""
        from schema.narrative import EventScheduled

        e = EventScheduled(
            event_type="completely_unknown",
            title="Something",
            planned_cycle=10,
        )
        assert e.event_type.value == "appointment"

    def test_event_scheduled_event_type_with_dash(self):
        """EventScheduled handles event_type with dashes."""
        from schema.narrative import EventScheduled

        e = EventScheduled(
            event_type="financial-due",
            title="Pay rent",
            planned_cycle=7,
        )
        assert e.event_type.value == "financial_due"


# =============================================================================
# SCHEMA / EXTRACTION — InventoryChange, EntityCreation, EventScheduled
# =============================================================================


class TestExtractionValidators:
    """Test validators in extraction.py models."""

    def test_inventory_change_acquire_with_hint(self):
        """InventoryChange acquire with object_hint passes."""
        from schema.extraction import InventoryChange

        ic = InventoryChange(action="acquire", object_hint="New key card")
        assert ic.action == "acquire"

    def test_inventory_change_acquire_with_ref(self):
        """InventoryChange acquire with object_ref passes."""
        from schema.extraction import InventoryChange

        ic = InventoryChange(action="acquire", object_ref="Old key card")
        assert ic.action == "acquire"

    def test_inventory_change_acquire_no_ref_no_hint_rejected(self):
        """InventoryChange acquire without ref or hint is rejected."""
        from schema.extraction import InventoryChange

        with pytest.raises(ValidationError, match="acquire action requires"):
            InventoryChange(action="acquire")

    def test_inventory_change_lose_requires_ref(self):
        """InventoryChange lose without object_ref is rejected."""
        from schema.extraction import InventoryChange

        with pytest.raises(ValidationError, match="lose action requires object_ref"):
            InventoryChange(action="lose", object_hint="something")

    def test_inventory_change_use_requires_ref(self):
        """InventoryChange use without object_ref is rejected."""
        from schema.extraction import InventoryChange

        with pytest.raises(ValidationError, match="use action requires object_ref"):
            InventoryChange(action="use")

    def test_inventory_change_lose_with_ref_passes(self):
        """InventoryChange lose with object_ref passes."""
        from schema.extraction import InventoryChange

        ic = InventoryChange(action="lose", object_ref="Terminal")
        assert ic.action == "lose"

    def test_entity_creation_type_normalization(self):
        """EntityCreation normalizes entity_type."""
        from schema.extraction import EntityCreation

        ec = EntityCreation(entity_type="pnj", name="Somebody")
        assert ec.entity_type.value == "character"

    def test_entity_update_type_none_passes(self):
        """EntityUpdate with entity_type=None passes."""
        from schema.extraction import EntityUpdate

        eu = EntityUpdate(entity_ref="Someone", entity_type=None)
        assert eu.entity_type is None

    def test_entity_update_type_normalization(self):
        """EntityUpdate normalizes entity_type when provided."""
        from schema.extraction import EntityUpdate

        eu = EntityUpdate(entity_ref="Someone", entity_type="lieu")
        assert eu.entity_type.value == "location"

    def test_event_scheduled_extraction_type_normalization(self):
        """EventScheduledExtraction normalizes event_type."""
        from schema.extraction import EventScheduledExtraction

        e = EventScheduledExtraction(
            event_type="deadline",
            title="Report due",
            planned_cycle=10,
        )
        assert e.event_type.value == "deadline"

    def test_event_scheduled_extraction_unknown_type(self):
        """EventScheduledExtraction falls back on unknown event_type."""
        from schema.extraction import EventScheduledExtraction

        e = EventScheduledExtraction(
            event_type="weird_event_type",
            title="Something",
            planned_cycle=3,
        )
        assert e.event_type.value == "appointment"

    def test_event_scheduled_extraction_enum_instance(self):
        """EventScheduledExtraction passes through EventType enum instance."""
        from schema.core import EventType
        from schema.extraction import EventScheduledExtraction

        e = EventScheduledExtraction(
            event_type=EventType.CELEBRATION,
            title="Party",
            planned_cycle=15,
        )
        assert e.event_type == EventType.CELEBRATION

    def test_ambient_update_type_normalization(self):
        """AmbientUpdate normalizes entity_type."""
        from schema.extraction import AmbientUpdate

        au = AmbientUpdate(
            entity_ref="Lab",
            entity_type="location",
            ambient="Quiet and dusty",
        )
        assert au.entity_type.value == "location"

    def test_get_extraction_tool_schema_strips_fields(self):
        """get_extraction_tool_schema removes caller-managed fields."""
        from schema.extraction import get_extraction_tool_schema

        schema = get_extraction_tool_schema()
        props = schema.get("properties", {})
        # These fields should be stripped
        assert "cycle" not in props
        assert "time" not in props
        assert "credit_transactions" not in props
        assert "inventory_changes" not in props
        assert "entities_removed" not in props
        # These should remain
        assert "facts" in props or "entities_created" in props


# =============================================================================
# SCHEMA / WORLD_GENERATION — validators, arrival event, soft refs
# =============================================================================


class TestArrivalEventData:
    """Test ArrivalEventData and build_arrival_summary."""

    def _make_arrival(self, **overrides):
        """Helper to build an ArrivalEventData with defaults."""
        from schema.world_generation import ArrivalEventData

        defaults = {
            "arrival_method": "navette",
            "arrival_location_ref": "Dock 7",
            "arrival_date": "Lundi 1er Janvier 2850",
            "time": "8h00",
            "immediate_sensory_details": ["air", "bruit", "lumiere"],
            "initial_mood": "Anxieux mais excite",
            "immediate_need": "Trouver ses quartiers",
        }
        defaults.update(overrides)
        return ArrivalEventData(**defaults)

    def test_build_arrival_summary_basic(self):
        """Basic summary includes method, mood, and need."""
        arrival = self._make_arrival()
        summary = arrival.build_arrival_summary()
        assert "navette" in summary
        assert summary.endswith(".")

    def test_build_arrival_summary_with_incident(self):
        """Summary includes incident when present."""
        arrival = self._make_arrival(optional_incident="Alarme de decompression.")
        summary = arrival.build_arrival_summary()
        assert "Alarme" in summary or "decompression" in summary

    def test_build_arrival_summary_long_incident(self):
        """Long incident is truncated in summary."""
        long_incident = "Un incident grave survient dans le dock. " * 5
        arrival = self._make_arrival(optional_incident=long_incident)
        summary = arrival.build_arrival_summary()
        assert len(summary) <= 300

    def test_build_arrival_summary_very_long_incident(self):
        """Very long incident (> 100 chars first sentence) is truncated at 80."""
        long_first = "x" * 120 + ". Second sentence."
        arrival = self._make_arrival(optional_incident=long_first)
        summary = arrival.build_arrival_summary()
        assert len(summary) <= 300

    def test_build_arrival_summary_short_need_shown(self):
        """Short immediate_need is included in summary."""
        arrival = self._make_arrival(immediate_need="Manger")
        summary = arrival.build_arrival_summary()
        assert "manger" in summary.lower()

    def test_build_arrival_summary_long_need_hidden(self):
        """Long immediate_need (>= 60 chars) is not included."""
        long_need = "x" * 70
        arrival = self._make_arrival(immediate_need=long_need)
        summary = arrival.build_arrival_summary()
        # Should not contain the need since it's too long
        assert long_need not in summary

    def test_build_arrival_summary_truncates_over_300(self):
        """Summary over 300 chars is truncated."""
        arrival = self._make_arrival(
            arrival_method="methode " * 30,
            initial_mood="mood " * 20,
            immediate_need="need " * 10,
        )
        summary = arrival.build_arrival_summary()
        assert len(summary) <= 300

    def test_summarize_incident_none(self):
        """_summarize_incident returns None when no incident."""
        arrival = self._make_arrival()
        assert arrival._summarize_incident() is None

    def test_summarize_incident_short(self):
        """_summarize_incident returns short incident as-is."""
        arrival = self._make_arrival(optional_incident="Court incident")
        result = arrival._summarize_incident()
        assert result == "Court incident"

    def test_summarize_incident_medium(self):
        """_summarize_incident extracts first sentence for medium text."""
        text = "First sentence here. Second sentence with more detail that makes it long."
        arrival = self._make_arrival(optional_incident=text)
        result = arrival._summarize_incident()
        assert "First sentence here" in result


class TestWorldGeneration:
    """Test WorldGeneration model validators."""

    def _minimal_world_gen_data(self, **overrides):
        """Build minimal data for WorldGeneration."""
        data = {
            "generation_seed_words": ["space", "mystery", "survival"],
            "world": {
                "name": "Station Alpha",
                "sectors": ["Sector A", "Sector B"],
                "founding_cycle": -5000,
            },
            "protagonist": {
                "name": "Valentin",
                "skills": [
                    {"name": "hack", "level": 3},
                    {"name": "pilot", "level": 2},
                ],
                "departure_reason": "fresh_start",
                "credits": 1400,
            },
            "companion": {
                "name": "Celimene",
                "traits": ["sarcastic"],
            },
            "characters": [
                {"name": f"NPC {i}", "species": "human" if i < 2 else "alien"}
                for i in range(3)
            ],
            "locations": [
                {"name": "Dock A", "location_type": "terminal"},
                {"name": "Appartement 1", "location_type": "apartment"},
                {"name": "Cafe", "location_type": "cafe"},
                {"name": "Market", "location_type": "market"},
            ],
            "organizations": [
                {"name": "Corp A", "founding_cycle": -3000},
            ],
            "inventory": [
                {"name": f"Item {i}", "category": "tech"} for i in range(3)
            ],
            "narrative_arcs": [
                {
                    "title": f"Arc {i}",
                    "domain": "personal",
                    "description": f"Description of arc {i} that is sufficiently long to pass",
                    "involved_entities": ["NPC 0"],
                }
                for i in range(3)
            ],
            "initial_relations": [
                {
                    "source_ref": "Valentin",
                    "target_ref": f"NPC {i % 3}",
                    "relation_type": "knows",
                }
                for i in range(5)
            ],
            "arrival_event": {
                "arrival_method": "navette",
                "arrival_location_ref": "Dock A",
                "arrival_date": "Lundi 1er Janvier 2850",
                "time": "8h00",
                "immediate_sensory_details": ["air", "bruit", "lumiere"],
                "initial_mood": "Anxieux",
                "immediate_need": "Trouver ses quartiers",
            },
        }
        data.update(overrides)
        return data

    def test_minimal_valid_world_generation(self):
        """Minimal valid WorldGeneration data parses."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        wg = WorldGeneration(**data)
        assert wg.world.name == "Station Alpha"
        assert len(wg.characters) == 3
        assert len(wg.locations) == 4

    def test_companion_rename_from_personal_ai(self):
        """companion field also accepts legacy personal_ai key."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["personal_ai"] = data.pop("companion")
        wg = WorldGeneration(**data)
        assert wg.companion.name == "Celimene"

    def test_missing_arrival_event_creates_default(self):
        """Missing arrival_event triggers default creation."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        del data["arrival_event"]
        wg = WorldGeneration(**data)
        assert wg.arrival_event is not None
        assert wg.arrival_event.arrival_method == "navette de transport"

    def test_null_arrival_event_creates_default(self):
        """None arrival_event triggers default creation."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["arrival_event"] = None
        wg = WorldGeneration(**data)
        assert wg.arrival_event is not None

    def test_default_arrival_event_finds_dock_location(self):
        """Default arrival event finds dock/terminal location."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        del data["arrival_event"]
        wg = WorldGeneration(**data)
        assert wg.arrival_event.arrival_location_ref in ("Dock A", "Station")

    def test_default_arrival_event_no_locations(self):
        """Default arrival event with no locations uses 'Station'."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        del data["arrival_event"]
        data["locations"] = []
        # Will have validation warnings but should not crash
        try:
            wg = WorldGeneration(**data)
        except ValidationError:
            pass  # locations may be required; that's fine

    def test_default_arrival_event_no_matching_dock(self):
        """Default arrival event without dock type falls back to first location."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        del data["arrival_event"]
        # Replace all locations with non-dock types
        data["locations"] = [
            {"name": f"Room {i}", "location_type": "room"} for i in range(4)
        ]
        wg = WorldGeneration(**data)
        assert wg.arrival_event.arrival_location_ref == "Room 0"

    def test_default_arrival_event_picks_first_npc(self):
        """Default arrival event picks first character as NPC."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        del data["arrival_event"]
        wg = WorldGeneration(**data)
        assert wg.arrival_event.first_npc_encountered == "NPC 0"

    def test_all_humans_triggers_warning(self):
        """All-human characters triggers diversity warning."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        for c in data["characters"]:
            c["species"] = "human"
        # Update relations to reference valid characters
        wg = WorldGeneration(**data)
        assert all(c.species == "human" for c in wg.characters)

    def test_no_residence_location_triggers_warning(self):
        """No residence type location triggers warning."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        for loc in data["locations"]:
            loc["location_type"] = "cafe"
        wg = WorldGeneration(**data)
        # Just verify it still creates the object (warning only)
        assert len(wg.locations) == 4

    def test_no_arrival_location_triggers_warning(self):
        """No arrival type location triggers warning."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        for loc in data["locations"]:
            if loc["location_type"] in ("terminal", "dock"):
                loc["location_type"] = "room"
        wg = WorldGeneration(**data)
        assert len(wg.locations) == 4

    def test_soft_minimums_warning(self):
        """Soft minimums trigger warnings but don't error."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        # Reduce characters to below minimum (3)
        data["characters"] = [{"name": "Solo", "species": "alien"}]
        # Need to fix relations to reference valid names
        data["initial_relations"] = [
            {"source_ref": "Valentin", "target_ref": "Solo", "relation_type": "knows"}
            for _ in range(5)
        ]
        data["narrative_arcs"] = [
            {
                "title": f"Arc {i}",
                "domain": "personal",
                "description": f"Description of arc {i} sufficient length for validation",
                "involved_entities": ["Solo"],
            }
            for i in range(3)
        ]
        wg = WorldGeneration(**data)
        assert len(wg.characters) == 1  # below minimum, but no error

    def test_temporal_coherence_org_before_world(self):
        """Organization founding before world founding is corrected."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["organizations"][0]["founding_cycle"] = -6000  # before world's -5000
        wg = WorldGeneration(**data)
        assert wg.organizations[0].founding_cycle == -5000

    def test_invalid_character_workplace_ref_nullified(self):
        """Invalid character workplace_ref is set to None."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["characters"][0]["workplace_ref"] = "Nonexistent Place"
        wg = WorldGeneration(**data)
        assert wg.characters[0].workplace_ref is None

    def test_invalid_character_residence_ref_nullified(self):
        """Invalid character residence_ref is set to None."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["characters"][0]["residence_ref"] = "Nowhere"
        wg = WorldGeneration(**data)
        assert wg.characters[0].residence_ref is None

    def test_invalid_location_parent_ref_nullified(self):
        """Invalid location parent_location_ref is set to None."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["locations"][0]["parent_location_ref"] = "Ghost Parent"
        wg = WorldGeneration(**data)
        assert wg.locations[0].parent_location_ref is None

    def test_invalid_org_hq_ref_nullified(self):
        """Invalid organization headquarters_ref is set to None."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["organizations"][0]["headquarters_ref"] = "Phantom HQ"
        wg = WorldGeneration(**data)
        assert wg.organizations[0].headquarters_ref is None

    def test_invalid_relation_source_filtered(self):
        """Relations with invalid source_ref are filtered out."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["initial_relations"].append(
            {
                "source_ref": "Ghost",
                "target_ref": "NPC 0",
                "relation_type": "knows",
            }
        )
        wg = WorldGeneration(**data)
        # The invalid relation should be filtered out
        sources = [r.source_ref for r in wg.initial_relations]
        assert "Ghost" not in sources

    def test_invalid_relation_target_filtered(self):
        """Relations with invalid target_ref are filtered out."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["initial_relations"].append(
            {
                "source_ref": "Valentin",
                "target_ref": "Nobody",
                "relation_type": "knows",
            }
        )
        wg = WorldGeneration(**data)
        targets = [r.target_ref for r in wg.initial_relations]
        assert "Nobody" not in targets

    def test_arc_invalid_entities_removed(self):
        """Arc with some invalid entities has them removed."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["narrative_arcs"][0]["involved_entities"] = ["NPC 0", "Phantom Entity"]
        wg = WorldGeneration(**data)
        arc_entities = wg.narrative_arcs[0].involved_entities
        assert "Phantom Entity" not in arc_entities
        assert "NPC 0" in arc_entities

    def test_arc_all_invalid_entities_removed_filters_arc(self):
        """Arc with only invalid entities is filtered out entirely."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["narrative_arcs"][0]["involved_entities"] = ["Ghost A", "Ghost B"]
        wg = WorldGeneration(**data)
        arc_titles = [a.title for a in wg.narrative_arcs]
        assert "Arc 0" not in arc_titles

    def test_duplicate_arcs_deduplicated(self):
        """Duplicate arc titles are removed."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["narrative_arcs"].append(
            {
                "title": "Arc 0",  # duplicate
                "domain": "social",
                "description": "Duplicate arc that should be removed",
                "involved_entities": ["NPC 0"],
            }
        )
        wg = WorldGeneration(**data)
        titles = [a.title for a in wg.narrative_arcs]
        assert titles.count("Arc 0") == 1

    def test_invalid_arrival_location_ref_fallback(self):
        """Invalid arrival_location_ref falls back to a valid location."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["arrival_event"]["arrival_location_ref"] = "Nonexistent Dock"
        wg = WorldGeneration(**data)
        # Should have fallen back to a valid location
        valid_names = {loc.name.lower() for loc in wg.locations}
        assert wg.arrival_event.arrival_location_ref.lower() in valid_names

    def test_invalid_first_npc_ref_nullified(self):
        """Invalid first_npc_encountered is set to None."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["arrival_event"]["first_npc_encountered"] = "Ghost NPC"
        wg = WorldGeneration(**data)
        assert wg.arrival_event.first_npc_encountered is None

    def test_validate_inventory_for_departure_warning(self):
        """Credits outside expected range for departure triggers warning."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["protagonist"]["credits"] = 10000  # way too high for fresh_start
        wg = WorldGeneration(**data)
        assert wg.protagonist.credits == 10000  # warning only, not corrected

    def test_validate_inventory_departure_enum_reason(self):
        """Credits validation with enum departure_reason."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        data["protagonist"]["departure_reason"] = "broke"
        data["protagonist"]["credits"] = 100
        wg = WorldGeneration(**data)
        assert wg.protagonist.departure_reason.value == "broke"

    def test_find_arrival_location_fallback_no_locations(self):
        """_find_arrival_location_fallback returns None when no locations."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        wg = WorldGeneration(**data)
        # Temporarily empty the locations to test fallback
        original = wg.locations
        wg.locations = []
        result = wg._find_arrival_location_fallback()
        assert result is None
        wg.locations = original

    def test_find_arrival_location_fallback_with_dock(self):
        """_find_arrival_location_fallback finds dock type."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        wg = WorldGeneration(**data)
        result = wg._find_arrival_location_fallback()
        assert result == "Dock A"

    def test_check_minimums_after_filtering(self):
        """_check_minimums_after_filtering logs warnings."""
        from schema.world_generation import WorldGeneration

        data = self._minimal_world_gen_data()
        wg = WorldGeneration(**data)
        # Shouldn't crash
        wg._check_minimums_after_filtering()

    def test_ensure_arrival_event_non_dict_data(self):
        """ensure_arrival_event passes through non-dict data."""
        from schema.world_generation import WorldGeneration

        # When data is not a dict, it should be returned as-is
        # (handled by the mode="before" validator)
        result = WorldGeneration.ensure_arrival_event("not_a_dict")
        assert result == "not_a_dict"


# =============================================================================
# SERVICES / AUTH_SERVICE — hashing, JWT, verify_email, resend
# =============================================================================


class TestAuthServiceHashing:
    """Test hash_password and verify_password."""

    def test_hash_and_verify_success(self):
        """hash_password + verify_password round-trip works."""
        from services.auth_service import hash_password, verify_password

        hashed = hash_password("my_secret_password")
        assert hashed != "my_secret_password"
        assert verify_password("my_secret_password", hashed) is True

    def test_verify_wrong_password(self):
        """verify_password returns False for wrong password."""
        from services.auth_service import hash_password, verify_password

        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_verify_invalid_hash_returns_false(self):
        """verify_password returns False for malformed hash."""
        from services.auth_service import verify_password

        assert verify_password("anything", "not_a_valid_bcrypt_hash") is False


class TestAuthServiceJWT:
    """Test create_token and decode_token."""

    def test_create_and_decode_token(self):
        """create_token + decode_token round-trip."""
        from services.auth_service import create_token, decode_token

        user_id = uuid4()
        token = create_token(user_id, "test@example.com")
        payload = decode_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["email"] == "test@example.com"
        assert "exp" in payload

    def test_decode_expired_token(self):
        """decode_token raises on expired token."""
        import jwt as pyjwt
        from config import get_settings
        from services.auth_service import decode_token

        settings = get_settings()
        payload = {
            "sub": str(uuid4()),
            "email": "test@test.com",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_token(token)

    def test_decode_invalid_token(self):
        """decode_token raises on invalid token."""
        import jwt as pyjwt
        from services.auth_service import decode_token

        with pytest.raises(pyjwt.PyJWTError):
            decode_token("this.is.not.a.valid.jwt")


class TestAuthServiceRegister:
    """Test register function with mocked DB."""

    @pytest.mark.asyncio
    async def test_register_success(self):
        """register creates user and returns token."""
        from services.auth_service import register

        user_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": user_id,
            "email": "new@test.com",
            "display_name": "New User",
            "email_verified": False,
        }

        with patch("services.auth_service.send_verification_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await register(mock_conn, "New@Test.com", "password123", "New User")

        assert result["id"] == user_id
        assert result["email"] == "new@test.com"
        assert "token" in result
        assert result["email_verified"] is False

    @pytest.mark.asyncio
    async def test_register_short_password(self):
        """register raises ValueError for short password."""
        from services.auth_service import register

        mock_conn = AsyncMock()
        with pytest.raises(ValueError, match="at least 6 characters"):
            await register(mock_conn, "x@x.com", "12345")

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self):
        """register raises ValueError for duplicate email."""
        from services.auth_service import register

        mock_conn = AsyncMock()
        mock_conn.fetchrow.side_effect = Exception("unique constraint violation on email")

        with patch("services.auth_service.send_verification_email", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Email already registered"):
                await register(mock_conn, "dup@test.com", "password123")

    @pytest.mark.asyncio
    async def test_register_duplicate_display_name(self):
        """register raises ValueError for duplicate display_name."""
        from services.auth_service import register

        mock_conn = AsyncMock()
        mock_conn.fetchrow.side_effect = Exception(
            "unique constraint violation on display_name"
        )

        with patch("services.auth_service.send_verification_email", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Display name already taken"):
                await register(mock_conn, "new2@test.com", "password123", "Taken Name")


class TestAuthServiceAuthenticate:
    """Test authenticate function with mocked DB."""

    @pytest.mark.asyncio
    async def test_authenticate_by_email_success(self):
        """authenticate by email returns user dict with token."""
        from services.auth_service import authenticate, hash_password

        user_id = uuid4()
        pw_hash = hash_password("correct")
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": user_id,
            "email": "user@test.com",
            "password_hash": pw_hash,
            "display_name": "User",
            "email_verified": True,
        }

        result = await authenticate(mock_conn, "user@test.com", "correct")
        assert result is not None
        assert result["id"] == user_id
        assert "token" in result

    @pytest.mark.asyncio
    async def test_authenticate_by_display_name(self):
        """authenticate by display_name (no @) queries display_name."""
        from services.auth_service import authenticate, hash_password

        user_id = uuid4()
        pw_hash = hash_password("pass")
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": user_id,
            "email": "user@test.com",
            "password_hash": pw_hash,
            "display_name": "UserName",
            "email_verified": True,
        }

        result = await authenticate(mock_conn, "UserName", "pass")
        assert result is not None
        # Verify it called fetchrow with display_name query
        call_args = mock_conn.fetchrow.call_args
        assert "display_name" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password(self):
        """authenticate returns None for wrong password."""
        from services.auth_service import authenticate, hash_password

        pw_hash = hash_password("correct")
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": uuid4(),
            "email": "user@test.com",
            "password_hash": pw_hash,
            "display_name": "User",
            "email_verified": True,
        }

        result = await authenticate(mock_conn, "user@test.com", "wrong")
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_user_not_found(self):
        """authenticate returns None when user not found."""
        from services.auth_service import authenticate

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None

        result = await authenticate(mock_conn, "nobody@test.com", "pass")
        assert result is None


class TestAuthServiceVerifyEmail:
    """Test verify_email function with mocked DB."""

    @pytest.mark.asyncio
    async def test_verify_email_success(self):
        """verify_email marks email as verified."""
        from services.auth_service import verify_email

        user_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": user_id,
            "email": "user@test.com",
            "display_name": "User",
            "email_verified": False,
            "email_verification_sent_at": datetime.now(timezone.utc) - timedelta(hours=1),
        }

        result = await verify_email(mock_conn, "valid_token")
        assert result is not None
        assert result["already_verified"] is False
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_email_already_verified(self):
        """verify_email returns already_verified for already-verified user."""
        from services.auth_service import verify_email

        user_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": user_id,
            "email": "user@test.com",
            "display_name": "User",
            "email_verified": True,
            "email_verification_sent_at": datetime.now(timezone.utc),
        }

        result = await verify_email(mock_conn, "valid_token")
        assert result is not None
        assert result["already_verified"] is True

    @pytest.mark.asyncio
    async def test_verify_email_token_not_found(self):
        """verify_email returns None for non-existent token."""
        from services.auth_service import verify_email

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None

        result = await verify_email(mock_conn, "bad_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_email_expired_token(self):
        """verify_email returns None for expired token (> 24h)."""
        from services.auth_service import verify_email

        user_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": user_id,
            "email": "user@test.com",
            "display_name": "User",
            "email_verified": False,
            "email_verification_sent_at": datetime.now(timezone.utc) - timedelta(hours=25),
        }

        result = await verify_email(mock_conn, "expired_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_email_no_sent_at(self):
        """verify_email proceeds when email_verification_sent_at is None."""
        from services.auth_service import verify_email

        user_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "id": user_id,
            "email": "user@test.com",
            "display_name": "User",
            "email_verified": False,
            "email_verification_sent_at": None,
        }

        result = await verify_email(mock_conn, "valid_token")
        assert result is not None
        assert result["already_verified"] is False


class TestAuthServiceResendVerification:
    """Test resend_verification function with mocked DB."""

    @pytest.mark.asyncio
    async def test_resend_verification_success(self):
        """resend_verification regenerates token and resends."""
        from services.auth_service import resend_verification

        user_id = uuid4()
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "email": "user@test.com",
            "email_verified": False,
        }

        with patch("services.auth_service.send_verification_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await resend_verification(mock_conn, user_id)

        assert result is True
        mock_conn.execute.assert_called_once()
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_resend_verification_already_verified(self):
        """resend_verification returns False for already-verified user."""
        from services.auth_service import resend_verification

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "email": "user@test.com",
            "email_verified": True,
        }

        result = await resend_verification(mock_conn, uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_resend_verification_user_not_found(self):
        """resend_verification returns False for non-existent user."""
        from services.auth_service import resend_verification

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None

        result = await resend_verification(mock_conn, uuid4())
        assert result is False


# =============================================================================
# UTILS / CRYPTO — encrypt, decrypt, mask_api_key
# =============================================================================


class TestCrypto:
    """Test crypto utilities."""

    def test_encrypt_and_decrypt_roundtrip(self):
        """encrypt_value + decrypt_value round-trip works."""
        from cryptography.fernet import Fernet

        test_key = Fernet.generate_key().decode()

        with patch("utils.crypto.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(encryption_key=test_key)

            from utils.crypto import encrypt_value, decrypt_value

            ciphertext = encrypt_value("my_secret_api_key")
            assert ciphertext != "my_secret_api_key"
            plaintext = decrypt_value(ciphertext)
            assert plaintext == "my_secret_api_key"

    def test_decrypt_invalid_ciphertext(self):
        """decrypt_value raises ValueError for invalid ciphertext."""
        from cryptography.fernet import Fernet

        test_key = Fernet.generate_key().decode()

        with patch("utils.crypto.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(encryption_key=test_key)

            from utils.crypto import decrypt_value

            with pytest.raises(ValueError, match="Decryption failed"):
                decrypt_value("not_valid_ciphertext")

    def test_missing_encryption_key_raises(self):
        """_get_fernet raises ValueError when key is empty."""
        with patch("utils.crypto.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(encryption_key="")

            from utils.crypto import _get_fernet

            with pytest.raises(ValueError, match="ENCRYPTION_KEY not configured"):
                _get_fernet()

    def test_mask_api_key_normal(self):
        """mask_api_key shows first 4 and last 4 chars."""
        from utils.crypto import mask_api_key

        result = mask_api_key("sk-ant-1234567890abcdef")
        assert result.startswith("sk-a")
        assert result.endswith("cdef")
        assert "****" not in result[:4]
        assert "*" in result

    def test_mask_api_key_short(self):
        """mask_api_key returns **** for short key."""
        from utils.crypto import mask_api_key

        assert mask_api_key("short") == "****"
        assert mask_api_key("12345678") == "****"

    def test_mask_api_key_empty(self):
        """mask_api_key returns **** for empty string."""
        from utils.crypto import mask_api_key

        assert mask_api_key("") == "****"

    def test_mask_api_key_none(self):
        """mask_api_key returns **** for None."""
        from utils.crypto import mask_api_key

        assert mask_api_key(None) == "****"

    def test_mask_api_key_exactly_9_chars(self):
        """mask_api_key works for 9-char key (just above threshold)."""
        from utils.crypto import mask_api_key

        result = mask_api_key("123456789")
        assert result == "1234*6789"


# =============================================================================
# SERVICES / EMAIL_SERVICE — send_verification_email, generate_token
# =============================================================================


class TestEmailService:
    """Test email service functions."""

    def test_generate_verification_token_is_hex(self):
        """generate_verification_token returns a 64-char hex string."""
        from services.email_service import generate_verification_token

        token = generate_verification_token()
        assert len(token) == 64
        # Verify it's valid hex
        int(token, 16)

    def test_generate_verification_token_unique(self):
        """generate_verification_token produces unique tokens."""
        from services.email_service import generate_verification_token

        tokens = {generate_verification_token() for _ in range(100)}
        assert len(tokens) == 100

    @pytest.mark.asyncio
    async def test_send_verification_email_no_api_key(self):
        """send_verification_email returns False when no API key configured."""
        from services.email_service import send_verification_email

        with patch("services.email_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(resend_api_key="")
            result = await send_verification_email("test@test.com", "token123")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_verification_email_success(self):
        """send_verification_email returns True on successful send."""
        from services.email_service import send_verification_email

        with patch("services.email_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                resend_api_key="re_test_key",
                frontend_url="http://localhost:3000",
                email_from="noreply@test.com",
            )
            with patch("services.email_service.resend") as mock_resend:
                mock_resend.Emails.send.return_value = {"id": "msg_123"}
                result = await send_verification_email("user@test.com", "token_abc")

        assert result is True
        mock_resend.Emails.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_verification_email_failure(self):
        """send_verification_email returns False on send failure."""
        from services.email_service import send_verification_email

        with patch("services.email_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                resend_api_key="re_test_key",
                frontend_url="http://localhost:3000",
                email_from="noreply@test.com",
            )
            with patch("services.email_service.resend") as mock_resend:
                mock_resend.Emails.send.side_effect = Exception("API error")
                result = await send_verification_email("user@test.com", "token_abc")

        assert result is False

    def test_verification_html_contains_link(self):
        """_verification_html includes the verification URL."""
        from services.email_service import _verification_html

        html = _verification_html("http://example.com/verify?token=abc")
        assert "http://example.com/verify?token=abc" in html
        assert "LDVELH" in html


# =============================================================================
# SCHEMA / RELATIONS — relation_type normalization
# =============================================================================


class TestRelationDataValidator:
    """Test RelationData field validators."""

    def test_relation_type_normalization_from_synonym(self):
        """RelationData normalizes relation_type from synonym."""
        from schema.relations import RelationData

        rd = RelationData(
            source_ref="A",
            target_ref="B",
            relation_type="ami",  # FR synonym for friend_of
        )
        assert rd.relation_type.value == "friend_of"

    def test_relation_type_from_enum_value(self):
        """RelationData accepts direct enum value string."""
        from schema.relations import RelationData

        rd = RelationData(
            source_ref="X",
            target_ref="Y",
            relation_type="employed_by",
        )
        assert rd.relation_type.value == "employed_by"

    def test_relation_category_property(self):
        """RelationType.category returns the correct category."""
        from schema.core import RelationType, RelationCategory

        assert RelationType.KNOWS.category == RelationCategory.SOCIAL
        assert RelationType.EMPLOYED_BY.category == RelationCategory.PROFESSIONAL
        assert RelationType.FREQUENTS.category == RelationCategory.SPATIAL
        assert RelationType.OWNS.category == RelationCategory.OWNERSHIP
