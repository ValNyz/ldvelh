"""
LDVELH - Narrative Extraction Schema (EAV Architecture)
Unified models for extracting data from LLM narrative output
All entity types use the same attributes-based format
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .core import (
    AttributeKey,
    AttributeWithVisibility,
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
    Text,
    normalize_commitment_type,
    normalize_entity_type,
)
from .narrative import FactData
from .relations import RelationData, RelationType


# =============================================================================
# ENTITY CREATION (Unified EAV format)
# =============================================================================


class EntityCreation(BaseModel):
    """
    A new entity discovered/introduced in the narrative.
    All entity types use the same structure with attributes.
    """

    entity_type: EntityType
    name: Name  # 100 chars
    aliases: list[str] = Field(default_factory=list)

    # Visibility
    known_by_protagonist: bool = Field(
        default=True, description="False if Val doesn't know this entity's real name"
    )
    unknown_name: Name | None = Field(
        default=None, description="How Val refers to this entity if unknown"
    )

    # All data as attributes (unified format)
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)

    # FK references (resolved by populator)
    parent_location_ref: EntityRef | None = Field(
        default=None, description="For locations: parent location"
    )
    headquarters_ref: EntityRef | None = Field(
        default=None, description="For organizations: HQ location"
    )
    creator_ref: EntityRef | None = Field(
        default=None, description="For AIs: creator entity"
    )
    workplace_ref: EntityRef | None = Field(
        default=None, description="For characters: workplace"
    )
    residence_ref: EntityRef | None = Field(
        default=None, description="For characters: residence"
    )

    @field_validator("entity_type", mode="before")
    @classmethod
    def _normalize_entity_type(cls, v):
        return normalize_entity_type(v)

    @field_validator("attributes", mode="before")
    @classmethod
    def _normalize_attributes(cls, v):
        """Convert dict format to AttributeWithVisibility list"""
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    # Handle {"key": "...", "value": "...", "known": true} format
                    result.append(
                        AttributeWithVisibility(
                            key=item.get("key"),
                            value=item.get("value", ""),
                            known_by_protagonist=item.get(
                                "known", item.get("known_by_protagonist", True)
                            ),
                            details=item.get("details"),
                        )
                    )
                elif isinstance(item, AttributeWithVisibility):
                    result.append(item)
            return result
        return v

    def get_attribute(self, key: AttributeKey) -> str | None:
        """Get an attribute value by key"""
        for attr in self.attributes:
            if attr.key == key:
                return attr.value
        return None


class EntityUpdate(BaseModel):
    """An update to an existing entity"""

    entity_ref: EntityRef
    new_aliases: list[str] = Field(default_factory=list)
    attributes_changed: list[AttributeWithVisibility] = Field(default_factory=list)
    skills_changed: list[Skill] = Field(default_factory=list)
    now_known: bool | None = Field(
        default=None, description="Set to True when Val learns the entity's real name"
    )
    real_name: Name | None = Field(
        default=None, description="The real name if now_known=True"
    )
    removed: bool = False
    removal_reason: Text | None = None  # 300 chars

    @field_validator("attributes_changed", mode="before")
    @classmethod
    def _normalize_attributes(cls, v):
        """Convert dict format to AttributeWithVisibility list"""
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    result.append(
                        AttributeWithVisibility(
                            key=item.get("key"),
                            value=item.get("value", ""),
                            known_by_protagonist=item.get(
                                "known", item.get("known_by_protagonist", True)
                            ),
                            details=item.get("details"),
                        )
                    )
                elif isinstance(item, AttributeWithVisibility):
                    result.append(item)
            return result
        return v


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
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    quantity: int = Field(default=1, ge=1)
    from_hint: ShortText  # 200 chars - The original hint

    @field_validator("attributes", mode="before")
    @classmethod
    def _normalize_attributes(cls, v):
        """Convert dict or simple format to AttributeWithVisibility list"""
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    result.append(
                        AttributeWithVisibility(
                            key=item.get("key"),
                            value=item.get("value", ""),
                            known_by_protagonist=item.get("known", True),
                            details=item.get("details"),
                        )
                    )
                elif isinstance(item, AttributeWithVisibility):
                    result.append(item)
            return result
        return v

    @classmethod
    def from_extracted(
        cls,
        name: str,
        category: str,
        description: str,
        transportable: bool = True,
        stackable: bool = False,
        base_value: int = 0,
        emotional_significance: str | None = None,
        from_hint: str = "",
    ) -> "ObjectCreation":
        """Factory from extracted data"""
        attrs = [
            AttributeWithVisibility(
                key=AttributeKey.DESCRIPTION,
                value=description,
                known_by_protagonist=True,
                details={
                    "category": category,
                    "transportable": transportable,
                    "stackable": stackable,
                    "base_value": base_value,
                },
            ),
        ]

        if emotional_significance:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.EMOTIONAL_SIGNIFICANCE,
                    value=emotional_significance,
                    known_by_protagonist=True,
                )
            )

        return cls(name=name, attributes=attrs, from_hint=from_hint)


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
    new_level: int | None = Field(default=None, ge=0, le=10)
    new_context: ShortText | None = None  # 200 chars
    now_known: bool | None = Field(
        default=None, description="Set to True when Val learns about this relation"
    )


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
    For new objects: use object_hint (object will be created separately).
    """

    action: Literal["acquire", "lose", "use"]
    # For existing objects
    object_ref: EntityRef | None = None
    # For new objects: text description, not ObjectData
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
    """A new narrative commitment (foreshadowing, secret, etc.)"""

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
    """A commitment that was resolved"""

    commitment_description: ShortText  # 200 chars - to match existing
    resolution_description: Text  # 300 chars


class EventScheduledExtraction(BaseModel):
    """An event planned for the future"""

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

    # Entity changes (unified EAV format)
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
