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

    @field_validator("semantic_key", mode="before")
    @classmethod
    def _normalize_semantic_key(cls, v):
        """Strip accents and special chars from semantic_key."""
        if not isinstance(v, str):
            return v
        import unicodedata
        # Decompose accented chars, keep only ASCII
        nfkd = unicodedata.normalize("NFKD", v.lower())
        ascii_key = "".join(c for c in nfkd if c.isascii())
        # Replace non-alnum (except : and _) with _
        cleaned = "".join(c if c.isalnum() or c in ":_" else "_" for c in ascii_key)
        # Collapse multiple underscores
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_")

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
    """A narrative arc (story thread) — simplified, managed by Director"""

    title: Name  # 100 chars
    domain: str = "personal"  # free text, no enum constraint
    description: LongText  # 400 chars
    intensity: int = Field(default=3, ge=1, le=5)
    involved_entities: list[EntityRef] = Field(default_factory=list)

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, v):
        """Best-effort normalization, no error on unknown domains."""
        if not isinstance(v, str):
            return "personal"
        return v.lower().strip()


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
