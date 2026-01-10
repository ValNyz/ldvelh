"""
LDVELH - Narrative Extraction Schema
Modèles pour extraire les données du texte narratif généré par le LLM
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .core import (
    Attribute,
    CertaintyLevel,
    CommitmentType,
    Cycle,
    EntityRef,
    EntityType,
    Skill,
)
from .entities import CharacterData, LocationData, ObjectData, OrganizationData
from .narrative import (
    BeliefData,
    CharacterArc,
    CommitmentCreation,
    CommitmentResolution,
    EventScheduled,
    FactData,
)
from .relations import RelationData, RelationType

# =============================================================================
# ENTITY CHANGES
# =============================================================================


class EntityCreation(BaseModel):
    """A new entity discovered/introduced in the narrative"""

    entity_type: EntityType
    name: str = Field(..., max_length=100)
    aliases: list[str] = Field(default_factory=list)
    confirmed: bool = Field(
        default=True, description="False if entity is only mentioned/rumored"
    )
    # Type-specific data (one of these based on entity_type)
    character_data: CharacterData | None = None
    location_data: LocationData | None = None
    object_data: ObjectData | None = None
    organization_data: OrganizationData | None = None

    @model_validator(mode="after")
    def validate_data_matches_type(self) -> "EntityCreation":
        """Ensure the right data field is populated"""
        type_to_field = {
            EntityType.CHARACTER: "character_data",
            EntityType.LOCATION: "location_data",
            EntityType.OBJECT: "object_data",
            EntityType.ORGANIZATION: "organization_data",
        }
        expected_field = type_to_field.get(self.entity_type)
        if expected_field:
            if getattr(self, expected_field) is None:
                raise ValueError(
                    f"Entity type {self.entity_type} requires {expected_field}"
                )
        return self


class EntityUpdate(BaseModel):
    """An update to an existing entity"""

    entity_ref: EntityRef
    # What changed
    new_aliases: list[str] = Field(default_factory=list)
    attributes_changed: list[Attribute] = Field(default_factory=list)
    skills_changed: list[Skill] = Field(default_factory=list)
    # For characters: arc updates
    arc_updates: list[CharacterArc] = Field(default_factory=list)
    # Removal
    removed: bool = False
    removal_reason: str | None = None


class EntityRemoval(BaseModel):
    """An entity that's been removed (death, departure, destruction)"""

    entity_ref: EntityRef
    reason: str = Field(..., max_length=300)
    cycle: Cycle


# =============================================================================
# RELATION CHANGES
# =============================================================================


class RelationCreation(BaseModel):
    """A new relationship discovered/formed"""

    relation: RelationData
    cycle: Cycle


class RelationUpdate(BaseModel):
    """Update to an existing relation"""

    source_ref: EntityRef
    target_ref: EntityRef
    relation_type: RelationType
    # What changed
    new_certainty: CertaintyLevel | None = None
    new_level: int | None = Field(default=None, ge=0, le=10)
    new_context: str | None = None
    revealed_truth: bool | None = None  # If is_true changed


class RelationEnd(BaseModel):
    """A relationship that ended"""

    source_ref: EntityRef
    target_ref: EntityRef
    relation_type: RelationType
    cycle: Cycle
    reason: str | None = Field(default=None, max_length=200)


# =============================================================================
# PROTAGONIST CHANGES
# =============================================================================


class GaugeChange(BaseModel):
    """Change to protagonist's energy/morale/health"""

    gauge: Literal["energy", "morale", "health"]
    delta: float = Field(..., ge=-5, le=5)
    reason: str = Field(..., max_length=100)


class CreditTransaction(BaseModel):
    """Money gained or spent"""

    amount: int  # Positive = gain, negative = spend
    description: str = Field(..., max_length=150)


class InventoryChange(BaseModel):
    """Item gained, lost, or modified"""

    action: Literal["acquire", "lose", "modify", "use"]
    object_ref: EntityRef | None = None  # For existing items
    new_object: ObjectData | None = None  # For new items
    quantity_delta: int = Field(default=1)
    reason: str | None = Field(default=None, max_length=150)


# =============================================================================
# NARRATIVE ELEMENTS
# =============================================================================


class CommitmentCreation(BaseModel):
    """A new narrative commitment (foreshadowing, secret, etc.)"""

    commitment_type: CommitmentType
    description: str = Field(..., max_length=400)
    involved_entities: list[EntityRef] = Field(default_factory=list)
    deadline_cycle: Cycle | None = None
    # For arcs
    objective: str | None = None
    obstacle: str | None = None


class CommitmentResolution(BaseModel):
    """A commitment that was resolved"""

    commitment_description: str = Field(
        ..., max_length=200, description="Description to match existing commitment"
    )
    resolution_description: str = Field(..., max_length=300)


class EventScheduled(BaseModel):
    """An event planned for the future"""

    event_type: Literal[
        "appointment", "deadline", "celebration", "recurring", "financial_due"
    ]
    title: str = Field(..., max_length=150)
    description: str | None = Field(default=None, max_length=300)
    planned_cycle: Cycle = Field(..., ge=1)
    hour: str | None = Field(default="12h00", max_length=5)
    location_ref: EntityRef | None = None
    participants: list[EntityRef] = Field(default_factory=list)
    recurrence: dict | None = None  # For recurring events
    amount: int | None = None  # For financial_due


# =============================================================================
# COMPLETE EXTRACTION OUTPUT
# =============================================================================


class NarrativeExtraction(BaseModel):
    """
    Complete extraction from a narrative segment.
    The LLM should produce this after generating narrative text.
    """

    # Context
    cycle: Cycle
    hour: str | None = Field(
        max_length=5, description="Hour at the start of the narration."
    )
    current_location_ref: EntityRef | None = None

    # Facts (immutable events that happened)
    facts: list[FactData] = Field(default_factory=list)

    # Entity changes
    entities_created: list[EntityCreation] = Field(default_factory=list)
    entities_updated: list[EntityUpdate] = Field(default_factory=list)
    entities_removed: list[EntityRemoval] = Field(default_factory=list)

    # Relation changes
    relations_created: list[RelationCreation] = Field(default_factory=list)
    relations_updated: list[RelationUpdate] = Field(default_factory=list)
    relations_ended: list[RelationEnd] = Field(default_factory=list)

    # Protagonist changes
    gauge_changes: list[GaugeChange] = Field(default_factory=list)
    credit_transactions: list[CreditTransaction] = Field(default_factory=list)
    inventory_changes: list[InventoryChange] = Field(default_factory=list)
    skills_changed: list[Skill] = Field(default_factory=list)

    # Beliefs (what protagonist learned/thinks)
    beliefs_updated: list[BeliefData] = Field(default_factory=list)

    # Narrative commitments
    commitments_created: list[CommitmentCreation] = Field(default_factory=list)
    commitments_resolved: list[CommitmentResolution] = Field(default_factory=list)

    # Future events
    events_scheduled: list[EventScheduled] = Field(default_factory=list)

    # Summary for context management
    segment_summary: str = Field(
        ...,
        max_length=500,
        description="Brief summary of what happened for context compression",
    )
    key_npcs_present: list[EntityRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_no_empty_extraction(self) -> "NarrativeExtraction":
        """Ensure we extracted something meaningful"""
        has_content = (
            self.facts
            or self.entities_created
            or self.entities_updated
            or self.relations_created
            or self.gauge_changes
            or self.beliefs_updated
        )
        if not has_content and not self.segment_summary:
            raise ValueError(
                "Extraction must contain at least facts, changes, or a summary"
            )
        return self


# =============================================================================
# EXTRACTION WITH NARRATIVE
# =============================================================================


class NarrativeWithExtraction(BaseModel):
    """
    Combined output: narrative text + extraction.
    Use this when the LLM generates both in one call.
    """

    narrative_text: str = Field(..., min_length=100)
    extraction: NarrativeExtraction

    # Optional: narrator notes (not shown to player)
    narrator_notes: str | None = Field(default=None, max_length=500)
