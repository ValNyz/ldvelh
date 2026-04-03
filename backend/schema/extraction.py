"""
LDVELH - Narrative Extraction Schema
Models for extracting structured data from LLM narrative output.
Uses direct fields instead of EAV attributes.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .core import (
    Cycle,
    EntityRef,
    EntityType,
    EventType,
    FullText,
    Name,
    Phrase,
    ShortText,
    Skill,
    Text,
    normalize_entity_type,
)
from .narrative import FactData
from .relations import RelationData, RelationType


# =============================================================================
# EXTRACTION TYPE ENUM
# =============================================================================


class ExtractionType(str, Enum):
    """Identifies which specialized extractor to run."""

    CHARACTERS = "characters"
    LOCATIONS = "locations"
    ORGANIZATIONS = "organizations"
    INVENTORY = "inventory"
    NARRATIVE_ARCS = "narrative_arcs"


# =============================================================================
# ENTITY CREATION (Direct fields, no EAV)
# =============================================================================


class EntityCreation(BaseModel):
    """
    A new entity discovered/introduced in the narrative.
    Entity-specific fields go in the data dict, validated by the populator
    against the appropriate entity model (CharacterData, LocationData, etc.)
    """

    entity_type: EntityType
    name: Name  # 100 chars
    known_by_protagonist: bool = True
    unknown_name: Name | None = None
    # Entity-specific fields (keys match the target table columns)
    data: dict = Field(
        default_factory=dict,
        description="Entity-specific fields matching the target table columns",
    )

    @field_validator("entity_type", mode="before")
    @classmethod
    def _normalize_entity_type(cls, v):
        return normalize_entity_type(v)


class EntityUpdate(BaseModel):
    """An update to an existing entity"""

    entity_ref: EntityRef
    entity_type: EntityType | None = None  # Helps routing to the correct table
    # Direct field changes (keys match the entity table columns)
    changes: dict = Field(
        default_factory=dict,
        description="Fields to update on the entity (column_name: new_value)",
    )
    skills_changed: list[Skill] = Field(default_factory=list)
    now_known: bool | None = None
    real_name: Name | None = None
    removed: bool = False
    removal_reason: Text | None = None  # 300 chars

    @field_validator("entity_type", mode="before")
    @classmethod
    def _normalize_entity_type(cls, v):
        if v is None:
            return v
        return normalize_entity_type(v)


class EntityRemoval(BaseModel):
    """An entity that's been removed (death, departure, destruction)"""

    entity_ref: EntityRef
    reason: Text  # 300 chars
    cycle: Cycle


# =============================================================================
# OBJECT CREATION
# =============================================================================


class ObjectCreation(BaseModel):
    """A new object created from inventory acquisition"""

    name: Name  # 100 chars
    canonical_name: str | None = Field(
        default=None,
        max_length=100,
        description="Snake_case dedup key (e.g. 'cafe_au_lait')",
    )
    category: ShortText | None = None
    description: Text | None = None
    transportable: bool = True
    stackable: bool = False
    base_value: int | None = None
    quantity: int = Field(default=1, ge=1)
    from_hint: ShortText  # 200 chars - the original hint


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
    now_known: bool | None = None


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
    """Item gained, lost, or used"""

    action: Literal["acquire", "lose", "use"]
    object_ref: EntityRef | None = None
    object_hint: ShortText | None = None  # 200 chars - for new objects
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


class ArcCreation(BaseModel):
    """A new narrative arc created during extraction"""

    title: Name  # 100 chars
    domain: str  # ArcDomain value
    description: Text  # 300 chars
    involved_entities: list[EntityRef] = Field(default_factory=list)
    potential_triggers: list[str] = Field(default_factory=list, max_length=4)
    stakes: ShortText | None = None  # 200 chars
    deadline_cycle: Cycle | None = None
    intensity: int = Field(default=3, ge=1, le=5)


class ArcUpdate(BaseModel):
    """An existing narrative arc that progressed"""

    arc_title: Name  # Match by title
    intensity: int | None = Field(default=None, ge=1, le=5)
    progress: int | None = Field(default=None, ge=0, le=100)
    situation: Text | None = None  # Updated current state, 300 chars


class ArcResolutionExtraction(BaseModel):
    """A narrative arc that was resolved"""

    arc_title: Name  # Match by title
    resolution: Text  # 300 chars


class EventScheduledExtraction(BaseModel):
    """An event planned for the future"""

    event_type: EventType
    title: Phrase  # 150 chars
    description: Text | None = None  # 300 chars
    planned_cycle: Cycle = Field(..., ge=1)
    time: str | None = None
    location_ref: EntityRef | None = None
    participants: list[EntityRef] = Field(default_factory=list)

    @field_validator("event_type", mode="before")
    @classmethod
    def _normalize_event_type(cls, v):
        if isinstance(v, EventType):
            return v
        if isinstance(v, str):
            try:
                return EventType(v.lower().replace("-", "_"))
            except ValueError:
                pass
        return EventType.APPOINTMENT


# =============================================================================
# COMPLETE EXTRACTION OUTPUT
# =============================================================================


class AmbientUpdate(BaseModel):
    """Ambient text update for an entity — visible effect of ongoing arcs."""

    entity_ref: EntityRef
    entity_type: EntityType
    ambient: ShortText  # 200 chars max

    @field_validator("entity_type", mode="before")
    @classmethod
    def _normalize_entity_type(cls, v):
        return normalize_entity_type(v)


class NarrativeExtraction(BaseModel):
    """
    Complete extraction from a narrative segment.
    Assembled from parallel extractors.
    """

    # Context
    cycle: Cycle = Field(default=1)
    time: str | None = None
    current_location_ref: EntityRef | None = None

    # Facts (immutable events)
    facts: list[FactData] = Field(default_factory=list)

    # Entity changes
    entities_created: list[EntityCreation] = Field(default_factory=list)
    entities_updated: list[EntityUpdate] = Field(default_factory=list)
    entities_removed: list[EntityRemoval] = Field(default_factory=list)

    # Objects created (from inventory acquisition)
    objects_created: list[ObjectCreation] = Field(default_factory=list)

    # Relation changes
    relations_created: list[RelationCreation] = Field(default_factory=list)
    relations_updated: list[RelationUpdate] = Field(default_factory=list)
    relations_ended: list[RelationEnd] = Field(default_factory=list)

    # Protagonist changes
    gauge_changes: list[GaugeChange] = Field(default_factory=list)
    credit_transactions: list[CreditTransaction] = Field(default_factory=list)
    inventory_changes: list[InventoryChange] = Field(default_factory=list)
    skills_changed: list[Skill] = Field(default_factory=list)

    # Narrative arcs
    arcs_created: list[ArcCreation] = Field(default_factory=list)
    arcs_updated: list[ArcUpdate] = Field(default_factory=list)
    arcs_resolved: list[ArcResolutionExtraction] = Field(default_factory=list)

    # Future events
    events_scheduled: list[EventScheduledExtraction] = Field(default_factory=list)

    # Ambient updates (visible effects of arcs on entities)
    ambient_updates: list["AmbientUpdate"] = Field(default_factory=list)

    # Summary
    segment_summary: FullText = ""  # 500 chars
    key_npcs_present: list[EntityRef] = Field(default_factory=list)


# =============================================================================
# EXTRACTION WITH NARRATIVE
# =============================================================================


class NarrativeWithExtraction(BaseModel):
    """Combined output: narrative text + extraction"""

    narrative_text: str = Field(..., min_length=100)
    extraction: NarrativeExtraction
    narrator_notes: FullText | None = None  # 500 chars


# =============================================================================
# TOOL_USE SCHEMA HELPER
# =============================================================================


def get_extraction_tool_schema() -> dict:
    """Return JSON schema for NarrativeExtraction, suitable for Anthropic tool_use.

    Strips fields managed by the caller (cycle, time, current_location_ref,
    gauge_changes, credit_transactions, inventory_changes, skills_changed,
    key_npcs_present) to keep the schema focused on what the LLM should extract.
    """
    schema = NarrativeExtraction.model_json_schema()

    # Remove caller-managed fields from the top-level properties
    caller_managed = {
        "cycle", "time", "current_location_ref",
        "gauge_changes", "credit_transactions", "inventory_changes",
        "skills_changed", "key_npcs_present",
        "entities_removed", "relations_ended",
    }
    props = schema.get("properties", {})
    for key in caller_managed:
        props.pop(key, None)

    # Also remove from required if present
    if "required" in schema:
        schema["required"] = [
            r for r in schema["required"] if r not in caller_managed
        ]

    return schema


# =============================================================================
# SPECIALIZED EXTRACTION OUTPUTS (one per extractor)
# =============================================================================


class CharactersExtraction(BaseModel):
    """Output of the characters extractor — character CRUD + ambient + facts."""

    entities_created: list[EntityCreation] = Field(default_factory=list)
    entities_updated: list[EntityUpdate] = Field(default_factory=list)
    entities_removed: list[EntityRemoval] = Field(default_factory=list)
    ambient_updates: list[AmbientUpdate] = Field(default_factory=list)
    skills_changed: list[Skill] = Field(default_factory=list)
    facts: list[FactData] = Field(default_factory=list)


class LocationsExtraction(BaseModel):
    """Output of the locations extractor — location CRUD + ambient + facts."""

    entities_created: list[EntityCreation] = Field(default_factory=list)
    entities_updated: list[EntityUpdate] = Field(default_factory=list)
    ambient_updates: list[AmbientUpdate] = Field(default_factory=list)
    facts: list[FactData] = Field(default_factory=list)


class OrganizationsExtraction(BaseModel):
    """Output of the organizations extractor — org CRUD + ambient + facts."""

    entities_created: list[EntityCreation] = Field(default_factory=list)
    entities_updated: list[EntityUpdate] = Field(default_factory=list)
    ambient_updates: list[AmbientUpdate] = Field(default_factory=list)
    facts: list[FactData] = Field(default_factory=list)


class InventoryExtraction(BaseModel):
    """Output of the inventory extractor — objects + inventory changes + facts."""

    objects_created: list[ObjectCreation] = Field(default_factory=list)
    inventory_changes: list[InventoryChange] = Field(default_factory=list)
    facts: list[FactData] = Field(default_factory=list)


class NarrativeArcsExtraction(BaseModel):
    """Output of the narrative_arcs extractor — arcs, relations, events, summary."""

    arcs_created: list[ArcCreation] = Field(default_factory=list)
    arcs_updated: list[ArcUpdate] = Field(default_factory=list)
    arcs_resolved: list[ArcResolutionExtraction] = Field(default_factory=list)
    relations_created: list[RelationCreation] = Field(default_factory=list)
    relations_updated: list[RelationUpdate] = Field(default_factory=list)
    relations_ended: list[RelationEnd] = Field(default_factory=list)
    events_scheduled: list[EventScheduledExtraction] = Field(default_factory=list)
    facts: list[FactData] = Field(default_factory=list)
    segment_summary: FullText = ""  # 500 chars
