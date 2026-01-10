"""
LDVELH - Narrative Extraction Schema
Modèles pour extraire les données du texte narratif généré par le LLM
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .core import (
    Attribute,
    CertaintyLevel,
    CommitmentType,
    Cycle,
    EntityRef,
    EntityType,
    FullText,
    LongText,
    Name,
    Phrase,
    ShortText,
    Skill,
    Tag,
    Text,
    normalize_certainty,
    normalize_commitment_type,
    normalize_entity_type,
)
from .entities import CharacterData, LocationData, ObjectData, OrganizationData
from .narrative import (
    BeliefData,
    CharacterArc,
    FactData,
)
from .relations import RelationData, RelationType

# =============================================================================
# ENTITY CHANGES
# =============================================================================


class EntityCreation(BaseModel):
    """A new entity discovered/introduced in the narrative"""

    entity_type: EntityType
    name: Name  # 100 chars
    aliases: list[str] = Field(default_factory=list)
    confirmed: bool = Field(
        default=True, description="False if entity is only mentioned/rumored"
    )
    # Type-specific data (one of these based on entity_type)
    character_data: CharacterData | None = None
    location_data: LocationData | None = None
    object_data: ObjectData | None = None  # Pour objets décor uniquement
    organization_data: OrganizationData | None = None

    @field_validator("entity_type", mode="before")
    @classmethod
    def _normalize_entity_type(cls, v):
        return normalize_entity_type(v)

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
    removal_reason: Text | None = None  # 300 chars


class EntityRemoval(BaseModel):
    """An entity that's been removed (death, departure, destruction)"""

    entity_ref: EntityRef
    reason: Text  # 300 chars
    cycle: Cycle


# =============================================================================
# OBJECT CREATION (from inventory acquisition)
# =============================================================================


class ObjectCreation(BaseModel):
    """
    A new object created from inventory acquisition.
    Produced by the Objects extractor based on inventory hints.
    """

    name: Name  # 100 chars
    category: Tag  # 50 chars
    description: ShortText  # 200 chars
    transportable: bool = True
    stackable: bool = False
    base_value: int = Field(default=0, ge=0)
    emotional_significance: Phrase | None = None  # 150 chars
    from_hint: ShortText  # 200 chars - The original hint


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
    new_context: ShortText | None = None  # 200 chars
    revealed_truth: bool | None = None

    @field_validator("new_certainty", mode="before")
    @classmethod
    def _normalize_certainty(cls, v):
        if v is None:
            return v
        return normalize_certainty(v)


class RelationEnd(BaseModel):
    """A relationship that ended"""

    source_ref: EntityRef
    target_ref: EntityRef
    relation_type: RelationType
    cycle: Cycle
    reason: ShortText | None = None  # 200 chars


# =============================================================================
# PROTAGONIST CHANGES
# =============================================================================


class GaugeChange(BaseModel):
    """Change to protagonist's energy/morale/health"""

    gauge: Literal["energy", "morale", "health"]
    delta: float = Field(..., ge=-5, le=5)
    reason: Name  # 100 chars


class CreditTransaction(BaseModel):
    """Money gained or spent"""

    amount: int  # Positive = gain, negative = spend
    description: Phrase  # 150 chars


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
    object_hint: ShortText | None = None  # 200 chars
    quantity_delta: int = Field(default=1)
    reason: Phrase | None = None  # 150 chars

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


class CommitmentCreationExtraction(BaseModel):
    """A new narrative commitment (foreshadowing, secret, etc.) - for extraction"""

    commitment_type: CommitmentType
    description: LongText  # 400 chars
    involved_entities: list[EntityRef] = Field(default_factory=list)
    deadline_cycle: Cycle | None = None
    objective: ShortText | None = None  # 200 chars
    obstacle: ShortText | None = None  # 200 chars

    @field_validator("commitment_type", mode="before")
    @classmethod
    def _normalize_commitment_type(cls, v):
        return normalize_commitment_type(v)


class CommitmentResolutionExtraction(BaseModel):
    """A commitment that was resolved - for extraction"""

    commitment_description: ShortText  # 200 chars - to match existing
    resolution_description: Text  # 300 chars


class EventScheduledExtraction(BaseModel):
    """An event planned for the future - for extraction"""

    event_type: Literal[
        "appointment", "deadline", "celebration", "recurring", "financial_due"
    ]
    title: Phrase  # 150 chars
    description: Text | None = None  # 300 chars
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
    commitments_created: list[CommitmentCreationExtraction] = Field(
        default_factory=list
    )
    commitments_resolved: list[CommitmentResolutionExtraction] = Field(
        default_factory=list
    )

    # Future events
    events_scheduled: list[EventScheduledExtraction] = Field(default_factory=list)

    # Summary
    segment_summary: FullText = ""  # 500 chars
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
    narrator_notes: FullText | None = None  # 500 chars
