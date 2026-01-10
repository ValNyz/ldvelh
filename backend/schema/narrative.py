"""
LDVELH - Narrative Schema
Facts, Beliefs, Character Arcs, Events, Commitments
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .core import (
    ArcDomain,
    CertaintyLevel,
    CommitmentType,
    Cycle,
    EntityRef,
    FactType,
    FullText,
    LongText,
    Name,
    ParticipantRole,
    Phrase,
    ShortText,
    Text,
    normalize_arc_domain,
    normalize_certainty,
    normalize_commitment_type,
    normalize_fact_type,
    normalize_participant_role,
)

# =============================================================================
# CHARACTER ARCS
# =============================================================================


class CharacterArc(BaseModel):
    """An arc in a character's life - multiple per character"""

    domain: ArcDomain
    title: Name  # 100 chars
    situation: Text  # 300 chars - current state
    desire: Phrase  # 150 chars - what they want
    obstacle: Phrase  # 150 chars - what blocks them
    potential_evolution: ShortText  # 200 chars
    intensity: int = Field(
        default=3, ge=1, le=5, description="How pressing is this arc now"
    )

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, v):
        return normalize_arc_domain(v)


# =============================================================================
# FACTS (Immutable past events)
# =============================================================================


class FactParticipant(BaseModel):
    """Someone involved in a fact"""

    entity_ref: EntityRef
    role: ParticipantRole = ParticipantRole.ACTOR

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, v):
        return normalize_participant_role(v)


class FactData(BaseModel):
    """
    An immutable event that happened.

    RÈGLES:
    - Un fact = UNE information atomique
    - semantic_key obligatoire pour déduplication
    - Choisir le type le plus spécifique
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
        description="Format: {sujet}:{verbe}:{objet} en snake_case",
    )

    @field_validator("fact_type", mode="before")
    @classmethod
    def _normalize_fact_type(cls, v):
        return normalize_fact_type(v)

    @model_validator(mode="after")
    def validate_semantic_key_matches_content(self) -> "FactData":
        """Vérifie que la semantic_key est cohérente"""
        parts = self.semantic_key.split(":")
        if len(parts) != 3:
            raise ValueError("semantic_key doit avoir format sujet:verbe:objet")
        return self


# =============================================================================
# BELIEFS (What the protagonist thinks they know)
# =============================================================================


class BeliefData(BaseModel):
    """What the protagonist believes (may be false)"""

    subject_ref: EntityRef
    key: Name  # 100 chars
    content: str
    is_true: bool = True
    certainty: CertaintyLevel = CertaintyLevel.CERTAIN
    source_description: Phrase | None = None  # 150 chars

    @field_validator("certainty", mode="before")
    @classmethod
    def _normalize_certainty(cls, v):
        return normalize_certainty(v)


# =============================================================================
# COMMITMENTS (Narrative promises)
# =============================================================================


class CommitmentCreation(BaseModel):
    """A new narrative commitment (foreshadowing, secret, etc.)"""

    commitment_type: CommitmentType
    description: LongText  # 400 chars
    involved_entities: list[EntityRef] = Field(default_factory=list)
    deadline_cycle: Cycle | None = None
    # For arcs
    objective: ShortText | None = None  # 200 chars
    obstacle: ShortText | None = None  # 200 chars

    @field_validator("commitment_type", mode="before")
    @classmethod
    def _normalize_commitment_type(cls, v):
        return normalize_commitment_type(v)


class CommitmentResolution(BaseModel):
    """A commitment that was resolved"""

    commitment_description: ShortText  # 200 chars - to match existing
    resolution_description: Text  # 300 chars


# =============================================================================
# EVENTS (Future scheduled events)
# =============================================================================


class EventType(str):
    APPOINTMENT = "appointment"
    DEADLINE = "deadline"
    CELEBRATION = "celebration"
    RECURRING = "recurring"
    FINANCIAL_DUE = "financial_due"


class EventScheduled(BaseModel):
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
    recurrence: dict | None = Field(
        default=None,
        description="Recurrence rule: {'type': 'weekly', 'day': 'monday'}",
    )
    amount: int | None = Field(default=None, description="For financial_due events")


# =============================================================================
# NARRATIVE ARCS (Global story arcs)
# =============================================================================


class NarrativeArcData(BaseModel):
    """A potential story arc for the game"""

    title: Name  # 100 chars
    arc_type: CommitmentType
    domain: ArcDomain = ArcDomain.PERSONAL
    description: LongText  # 400 chars
    involved_entities: list[EntityRef] = Field(..., min_length=1)
    potential_triggers: list[str] = Field(..., min_length=1, max_length=4)
    stakes: ShortText  # 200 chars
    deadline_cycle: Cycle | None = Field(default=None, ge=1)

    @field_validator("arc_type", mode="before")
    @classmethod
    def _normalize_arc_type(cls, v):
        return normalize_commitment_type(v)

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, v):
        return normalize_arc_domain(v)
