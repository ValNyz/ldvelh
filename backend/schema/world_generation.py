"""
LDVELH - World Generation Schema
Modèle spécifique pour la génération initiale du monde
"""

from pydantic import BaseModel, Field, field_validator, model_validator

from .core import EntityRef, Moment, TemporalValidationMixin
from .entities import (
    CharacterData,
    LocationData,
    ObjectData,
    OrganizationData,
    PersonalAIData,
    ProtagonistData,
    WorldData,
)
from .relations import RelationData
from .narrative import NarrativeArcData

# =============================================================================
# ARRIVAL EVENT
# =============================================================================


class ArrivalEventData(BaseModel):
    """Instructions for generating the first narrative moment"""

    arrival_method: str = Field(..., max_length=100)
    arrival_location_ref: EntityRef
    arrival_date: str = Field(
        ...,
        max_length=50,
        description="Date d'arrivée dans l'univers, ex: 'Lundi 14 Mars 2847'",
    )
    time_of_day: Moment
    immediate_sensory_details: list[str] = Field(..., min_length=3, max_length=6)
    first_npc_encountered: EntityRef | None = None
    initial_mood: str = Field(..., max_length=80)
    immediate_need: str = Field(..., max_length=200)
    optional_incident: str | None = Field(default=None, max_length=300)


# =============================================================================
# COMPLETE WORLD GENERATION OUTPUT
# =============================================================================


class WorldGeneration(BaseModel, TemporalValidationMixin):
    """Complete output from world generation LLM call"""

    # Meta
    generation_seed_words: list[str] = Field(
        ...,
        min_length=3,
        max_length=6,
        description="Thematic words guiding this generation",
    )
    tone_notes: str = Field(..., max_length=300)

    # Core elements
    world: WorldData
    protagonist: ProtagonistData
    personal_ai: PersonalAIData

    # Entities
    characters: list[CharacterData] = Field(..., min_length=3, max_length=8)
    locations: list[LocationData] = Field(..., min_length=4, max_length=10)
    organizations: list[OrganizationData] = Field(..., min_length=1, max_length=5)
    inventory: list[ObjectData] = Field(..., min_length=3, max_length=15)

    # Narrative
    narrative_arcs: list[NarrativeArcData] = Field(..., min_length=4, max_length=10)

    # Relations
    initial_relations: list[RelationData] = Field(..., min_length=5)

    # First moment
    arrival_event: ArrivalEventData

    # =========================================================================
    # VALIDATORS
    # =========================================================================

    @field_validator("characters")
    @classmethod
    def validate_character_diversity(
        cls, v: list[CharacterData]
    ) -> list[CharacterData]:
        """Ensure species diversity"""
        species = [c.species.lower() for c in v]
        if species.count("human") == len(species):
            raise ValueError("Need at least one non-human character for diversity")
        return v

    @field_validator("locations")
    @classmethod
    def validate_essential_locations(cls, v: list[LocationData]) -> list[LocationData]:
        """Ensure we have arrival point and residence"""
        types = [loc.location_type.lower() for loc in v]

        residence_types = {
            "apartment",
            "quarters",
            "residence",
            "housing",
            "room",
            "studio",
        }
        arrival_types = {"dock", "terminal", "port", "arrival", "gate", "bay", "quai"}

        has_residence = any(t in residence_types for t in types)
        has_arrival = any(t in arrival_types for t in types)

        if not has_residence:
            raise ValueError("Must include a residence location for Valentin")
        if not has_arrival:
            raise ValueError("Must include an arrival location (dock, terminal, etc.)")
        return v

    @model_validator(mode="after")
    def validate_temporal_coherence(self) -> "WorldGeneration":
        """Validate all temporal relationships"""
        founding = self.world.founding_cycle

        # Check character arrivals
        for char in self.characters:
            if char.station_arrival_cycle < founding:
                raise ValueError(
                    f"Character '{char.name}' arrived (cycle {char.station_arrival_cycle}) "
                    f"before station was founded (cycle {founding})"
                )

        # Check organization foundings
        for org in self.organizations:
            if org.founding_cycle and org.founding_cycle < founding:
                raise ValueError(
                    f"Organization '{org.name}' founded (cycle {org.founding_cycle}) before station (cycle {founding})"
                )

        return self

    @model_validator(mode="after")
    def validate_references(self) -> "WorldGeneration":
        """Validate all entity references exist"""
        # Build entity name registry
        known_names = {self.protagonist.name.lower(), self.personal_ai.name.lower()}
        known_names.update(c.name.lower() for c in self.characters)
        known_names.update(l.name.lower() for l in self.locations)
        known_names.update(o.name.lower() for o in self.organizations)
        known_names.update(i.name.lower() for i in self.inventory)

        errors = []

        # Check character refs
        for char in self.characters:
            if char.workplace_ref and char.workplace_ref.lower() not in known_names:
                errors.append(
                    f"Character '{char.name}' workplace_ref '{char.workplace_ref}' not found"
                )
            if char.residence_ref and char.residence_ref.lower() not in known_names:
                errors.append(
                    f"Character '{char.name}' residence_ref '{char.residence_ref}' not found"
                )

        # Check location parent refs
        for loc in self.locations:
            if (
                loc.parent_location_ref
                and loc.parent_location_ref.lower() not in known_names
            ):
                errors.append(
                    f"Location '{loc.name}' parent_ref '{loc.parent_location_ref}' not found"
                )

        # Check organization HQ refs
        for org in self.organizations:
            if org.headquarters_ref and org.headquarters_ref.lower() not in known_names:
                errors.append(
                    f"Organization '{org.name}' HQ ref '{org.headquarters_ref}' not found"
                )

        # Check relation refs
        for rel in self.initial_relations:
            if rel.source_ref.lower() not in known_names:
                errors.append(f"Relation source '{rel.source_ref}' not found")
            if rel.target_ref.lower() not in known_names:
                errors.append(f"Relation target '{rel.target_ref}' not found")

        # Check arrival event refs
        if self.arrival_event.arrival_location_ref.lower() not in known_names:
            errors.append(
                f"Arrival location '{self.arrival_event.arrival_location_ref}' not found"
            )
        if self.arrival_event.first_npc_encountered:
            if self.arrival_event.first_npc_encountered.lower() not in known_names:
                errors.append(
                    f"First NPC '{self.arrival_event.first_npc_encountered}' not found"
                )

        # Check narrative arc refs
        for arc in self.narrative_arcs:
            for entity in arc.involved_entities:
                if entity.lower() not in known_names:
                    errors.append(
                        f"Arc '{arc.title}' references unknown entity '{entity}'"
                    )

        if errors:
            raise ValueError("Reference validation failed:\n" + "\n".join(errors[:10]))

        return self

    @model_validator(mode="after")
    def validate_inventory_for_departure(self) -> "WorldGeneration":
        """Check inventory matches departure reason"""
        reason = self.protagonist.departure_reason
        credits = self.protagonist.initial_credits

        expected_ranges = {
            "flight": (100, 600),
            "breakup": (600, 1800),
            "opportunity": (1800, 5000),
            "fresh_start": (800, 2500),
            "standard": (1200, 2200),
            "broke": (0, 300),
            "other": (0, 10000),
        }

        min_c, max_c = expected_ranges.get(reason.value, (0, 10000))
        if not (min_c <= credits <= max_c):
            raise ValueError(
                f"Credits ({credits}) unusual for departure_reason '{reason.value}' (expected {min_c}-{max_c})"
            )

        return self
