"""
LDVELH - Narrative Schema
Facts, Narrative Arcs, Events
"""

from pydantic import BaseModel, Field, field_validator, model_validator

from .core import (
    ArcDomain,
    Cycle,
    EntityRef,
    EventType,
    FactType,
    FullText,
    LongText,
    Name,
    ParticipantRole,
    Phrase,
    ShortText,
    Tag,
    Text,
    normalize_arc_domain,
    normalize_fact_type,
    normalize_participant_role,
)


# =============================================================================
# FACTS (Immutable past events)
# =============================================================================


class FactParticipant(BaseModel):
    """An entity involved in a fact"""

    entity_ref: EntityRef
    role: ParticipantRole = ParticipantRole.ACTOR

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, v):
        return normalize_participant_role(v)


class FactData(BaseModel):
    """
    An immutable event that happened.
    One fact = ONE atomic piece of information.
    semantic_key is required for deduplication.
    """

    cycle: Cycle
    time: str | None = None
    fact_type: FactType
    description: FullText  # 500 chars
    location_ref: EntityRef | None = None
    importance: int = Field(default=3, ge=1, le=5)
    participants: list[FactParticipant] = Field(default_factory=list)
    semantic_key: Name = Field(
        ...,
        pattern=r"^[a-z0-9_]+:[a-z0-9_]+:[a-z0-9_]+$",
        description="Format: {subject}:{verb}:{object} in snake_case",
    )

    @field_validator("fact_type", mode="before")
    @classmethod
    def _normalize_fact_type(cls, v):
        return normalize_fact_type(v)

    @model_validator(mode="after")
    def validate_semantic_key_format(self) -> "FactData":
        """Verify semantic_key has the correct 3-part format"""
        parts = self.semantic_key.split(":")
        if len(parts) != 3:
            raise ValueError("semantic_key must have format subject:verb:object")
        return self


# =============================================================================
# NARRATIVE ARCS
# =============================================================================


class NarrativeArcData(BaseModel):
    """A narrative arc (story thread) tracked across cycles"""

    title: Name  # 100 chars
    domain: ArcDomain = ArcDomain.PERSONAL
    description: LongText  # 400 chars
    # State
    intensity: int = Field(default=3, ge=1, le=5, description="How pressing this arc is")
    progress: int = Field(default=0, ge=0, le=100)
    situation: Text | None = None  # 300 chars - current state
    desire: Phrase | None = None  # 150 chars - goal / tension
    obstacle: Phrase | None = None  # 150 chars - what blocks progress
    # Triggers
    potential_triggers: list[str] = Field(default_factory=list, max_length=4)
    stakes: ShortText | None = None  # 200 chars
    deadline_cycle: Cycle | None = Field(default=None, ge=1)
    # Participants (entity refs, resolved to entity_registry by populator)
    involved_entities: list[EntityRef] = Field(default_factory=list)

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, v):
        return normalize_arc_domain(v)


class ArcResolution(BaseModel):
    """Resolution of a narrative arc"""

    arc_title: Name  # Match by title
    resolution: Text  # 300 chars
    cycle: Cycle


# =============================================================================
# EVENTS (Scheduled future events)
# =============================================================================


class EventScheduled(BaseModel):
    """An event planned for the future"""

    event_type: EventType
    title: Phrase  # 150 chars
    description: Text | None = None  # 300 chars
    planned_cycle: Cycle = Field(..., ge=1)
    time: Tag | None = None
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
