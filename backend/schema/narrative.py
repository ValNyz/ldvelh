"""
LDVELH - Narrative Schema
Facts, Beliefs, Character Arcs, Events, Commitments
"""

from typing import Literal

from pydantic import BaseModel, Field

from .core import (
    ArcDomain,
    CertaintyLevel,
    CommitmentType,
    Cycle,
    EntityRef,
    FactDomain,
    FactType,
    ParticipantRole,
)

# =============================================================================
# CHARACTER ARCS
# =============================================================================


class CharacterArc(BaseModel):
    """An arc in a character's life - multiple per character"""

    domain: ArcDomain
    title: str = Field(..., max_length=100)
    situation: str = Field(..., max_length=300, description="Current state")
    desire: str = Field(..., max_length=150, description="What they want")
    obstacle: str = Field(..., max_length=150, description="What blocks them")
    potential_evolution: str = Field(..., max_length=200)
    intensity: int = Field(
        default=3, ge=1, le=5, description="How pressing is this arc now"
    )


# =============================================================================
# FACTS (Immutable past events)
# =============================================================================


class FactParticipant(BaseModel):
    """Someone involved in a fact"""

    entity_ref: EntityRef
    role: ParticipantRole = ParticipantRole.ACTOR


class FactData(BaseModel):
    """An immutable event that happened"""

    cycle: Cycle
    time: str | None = None
    fact_type: FactType
    domain: FactDomain = FactDomain.OTHER
    description: str = Field(..., max_length=500)
    location_ref: EntityRef | None = None
    importance: int = Field(default=3, ge=1, le=5)
    participants: list[FactParticipant] = Field(default_factory=list)


# =============================================================================
# BELIEFS (What the protagonist thinks they know)
# =============================================================================


class BeliefData(BaseModel):
    """What the protagonist believes (may be false)"""

    subject_ref: EntityRef
    key: str = Field(..., max_length=100)
    content: str
    is_true: bool = True
    certainty: CertaintyLevel = CertaintyLevel.CERTAIN
    source_description: str | None = None


# =============================================================================
# COMMITMENTS (Narrative promises)
# =============================================================================


class CommitmentCreation(BaseModel):
    """A new narrative commitment (foreshadowing, secret, etc.)"""

    commitment_type: CommitmentType
    description: str = Field(..., max_length=400)
    involved_entities: list[EntityRef] = Field(default_factory=list)
    deadline_cycle: Cycle | None = None
    # For arcs
    objective: str | None = Field(default=None, max_length=200)
    obstacle: str | None = Field(default=None, max_length=200)


class CommitmentResolution(BaseModel):
    """A commitment that was resolved"""

    commitment_description: str = Field(
        ..., max_length=200, description="Description to match existing commitment"
    )
    resolution_description: str = Field(..., max_length=300)


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
    title: str = Field(..., max_length=150)
    description: str | None = Field(default=None, max_length=300)
    planned_cycle: Cycle = Field(..., ge=1)
    time: str | None = Field(default="12h00", max_length=5)
    location_ref: EntityRef | None = None
    participants: list[EntityRef] = Field(default_factory=list)
    recurrence: dict | None = Field(
        default=None,
        description="Recurrence rule: {'type': 'weekly', 'day': 'monday'} or {'type': 'monthly', 'day': 15}",
    )
    amount: int | None = Field(default=None, description="For financial_due events")


# =============================================================================
# NARRATIVE ARCS (Global story arcs)
# =============================================================================


class NarrativeArcData(BaseModel):
    """A potential story arc for the game"""

    title: str = Field(..., max_length=100)
    arc_type: CommitmentType
    domain: ArcDomain = ArcDomain.PERSONAL
    description: str = Field(..., max_length=400)
    involved_entities: list[EntityRef] = Field(..., min_length=1)
    potential_triggers: list[str] = Field(..., min_length=1, max_length=4)
    stakes: str = Field(..., max_length=200)
    deadline_cycle: Cycle | None = Field(default=None, ge=1)
