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
    object_data: ObjectData | None = None  # Pour objets décor uniquement
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
    new_aliases: list[str] = Field(default_factory=list)
    attributes_changed: list[Attribute] = Field(default_factory=list)
    skills_changed: list[Skill] = Field(default_factory=list)
    arc_updates: list[CharacterArc] = Field(default_factory=list)
    removed: bool = False
    removal_reason: str | None = None


class EntityRemoval(BaseModel):
    """An entity that's been removed (death, departure, destruction)"""

    entity_ref: EntityRef
    reason: str = Field(..., max_length=300)
    cycle: Cycle


# =============================================================================
# OBJECT CREATION (from inventory acquisition)
# =============================================================================


class ObjectCreation(BaseModel):
    """
    A new object created from inventory acquisition.
    Produced by the Objects extractor based on inventory hints.
    """

    name: str = Field(..., max_length=100)
    category: str = Field(..., max_length=50)
    description: str = Field(..., max_length=200)
    transportable: bool = True
    stackable: bool = False
    base_value: int = Field(default=0, ge=0)
    emotional_significance: str | None = Field(default=None, max_length=150)
    from_hint: str = Field(..., description="The original hint this was created from")


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
    new_certainty: CertaintyLevel | None = None
    new_level: int | None = Field(default=None, ge=0, le=10)
    new_context: str | None = None
    revealed_truth: bool | None = None


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
    """
    Item gained, lost, or used.

    Pour les nouveaux objets: utiliser object_hint (pas de création ici).
    L'extracteur Objets créera l'objet à partir du hint.
    """

    action: Literal["acquire", "lose", "use"]
    # Pour objets existants
    object_ref: EntityRef | None = None
    # Pour nouveaux objets: description textuelle, pas ObjectData
    object_hint: str | None = Field(
        default=None,
        max_length=200,
        description="Description du nouvel objet acquis (sera traité par extracteur Objets)",
    )
    quantity_delta: int = Field(default=1)
    reason: str | None = Field(default=None, max_length=150)

    @model_validator(mode="after")
    def validate_ref_or_hint(self) -> "InventoryChange":
        """Ensure either object_ref or object_hint is provided for acquire"""
        if self.action == "acquire" and not self.object_ref and not self.object_hint:
            raise ValueError("acquire action requires object_ref or object_hint")
        if self.action in ("lose", "use") and not self.object_ref:
            raise ValueError(f"{self.action} action requires object_ref")
        return self


# =============================================================================
# NARRATIVE ELEMENTS
# =============================================================================


class CommitmentCreation(BaseModel):
    """A new narrative commitment (foreshadowing, secret, etc.)"""

    commitment_type: CommitmentType
    description: str = Field(..., max_length=400)
    involved_entities: list[EntityRef] = Field(default_factory=list)
    deadline_cycle: Cycle | None = None
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
    time: str | None = Field(default="12h00", max_length=5)
    location_ref: EntityRef | None = None
    participants: list[EntityRef] = Field(default_factory=list)
    recurrence: dict | None = None
    amount: int | None = None


# =============================================================================
# COMPLETE EXTRACTION OUTPUT
# =============================================================================


class NarrativeExtraction(BaseModel):
    """
    Complete extraction from a narrative segment.
    Assembled from parallel extractors.
    """

    # Context
    cycle: Cycle = Field(default=1)
    time: str | None = Field(
        default=None, max_length=5, description="Hour at the start of the narration."
    )
    current_location_ref: EntityRef | None = None

    # Facts (immutable events that happened)
    facts: list[FactData] = Field(default_factory=list)

    # Entity changes
    entities_created: list[EntityCreation] = Field(default_factory=list)
    entities_updated: list[EntityUpdate] = Field(default_factory=list)
    entities_removed: list[EntityRemoval] = Field(default_factory=list)

    # Objects created (from inventory acquisition)
    objects_created: list[ObjectCreation] = Field(default_factory=list)

    # Relation changes (NO owns - handled automatically)
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

    # Summary
    segment_summary: str = Field(
        default="",
        max_length=500,
        description="Brief summary of what happened",
    )
    key_npcs_present: list[EntityRef] = Field(default_factory=list)


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
    narrator_notes: str | None = Field(default=None, max_length=500)
