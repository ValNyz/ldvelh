"""
LDVELH - Entity Models (Dedicated Tables)
Each entity has its own typed fields — no more EAV
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .core import (
    Backstory,
    Cycle,
    DepartureReason,
    EntityRef,
    Label,
    Mood,
    Name,
    ShortText,
    Skill,
    Tag,
    Text,
)

logger = logging.getLogger(__name__)


# =============================================================================
# WORLD / STATION
# =============================================================================


class WorldData(BaseModel):
    """The space station — global world context"""

    name: Name
    description: Text | None = None
    atmosphere: Mood | None = None
    sectors: list[str] = Field(..., min_length=2, max_length=10)
    founding_cycle: Cycle = Field(default=-5000, le=-100)
    seed_words: list[str] = Field(default_factory=list)


# =============================================================================
# PROTAGONIST
# =============================================================================


class ProtagonistData(BaseModel):
    """The player character"""

    name: Tag = "Valentin"
    # Gauges
    energy: float = Field(default=4.0, ge=0, le=5)
    morale: float = Field(default=3.0, ge=0, le=5)
    health: float = Field(default=5.0, ge=0, le=5)
    credits: int = Field(default=1400, ge=0)
    # Profile
    occupation: Name | None = None
    origin: Name | None = None
    departure_reason: DepartureReason = DepartureReason.FRESH_START
    backstory: Backstory | None = None
    hobbies: list[str] = Field(default_factory=list)
    description: Text | None = None
    # References
    employer_ref: EntityRef | None = None
    residence_ref: EntityRef | None = None
    # Skills
    skills: list[Skill] = Field(default_factory=list, min_length=2, max_length=6)
    # Flexible
    details: dict = Field(default_factory=dict)

    @field_validator("departure_reason", mode="before")
    @classmethod
    def _normalize_departure(cls, v: Any) -> str:
        from .core import normalize_departure_reason

        return normalize_departure_reason(v)

    @field_validator("hobbies", mode="before")
    @classmethod
    def _parse_hobbies(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return [v]
        return v


# =============================================================================
# PERSONAL ASSISTANT
# =============================================================================


class PersonalAssistantData(BaseModel):
    """The protagonist's AI companion"""

    name: Label
    voice: ShortText | None = None
    traits: list[str] = Field(default_factory=list)
    quirk: ShortText | None = None
    substrate: Name = "terminal personnel"
    details: dict = Field(default_factory=dict)

    @field_validator("traits", mode="before")
    @classmethod
    def _parse_traits(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return [v]
        return v


# =============================================================================
# CHARACTER (NPC)
# =============================================================================


class CharacterData(BaseModel):
    """An NPC in the world"""

    name: Name
    # Identity
    known_by_protagonist: bool = False
    unknown_name: Name | None = None
    species: Tag | None = None
    gender: Label | None = None
    pronouns: Label | None = None
    age: Label | None = None
    description: Text | None = None
    # Personality & state
    traits: list[str] = Field(default_factory=list)
    mood: Mood | None = None
    occupation: Name | None = None
    origin: Name | None = None
    # Related locations
    workplace_ref: EntityRef | None = None
    residence_ref: EntityRef | None = None
    # Narrative
    romantic_potential: bool = False
    is_mandatory: bool = False
    ambient: ShortText | None = None
    # Flexible
    details: dict = Field(default_factory=dict)

    @field_validator("traits", mode="before")
    @classmethod
    def _parse_traits(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return [v]
        return v


# =============================================================================
# LOCATION
# =============================================================================


class LocationData(BaseModel):
    """A location on the station"""

    name: Name
    # Hierarchy
    parent_location_ref: EntityRef | None = None
    # Properties
    location_type: Tag | None = None
    sector: Tag | None = None
    description: Text | None = None
    atmosphere: Mood | None = None
    accessible: bool = True
    notable_features: list[str] = Field(default_factory=list)
    typical_crowd: ShortText | None = None
    operating_hours: Tag | None = None
    price_range: Tag | None = None
    # Narrative
    ambient: ShortText | None = None
    # Flexible
    details: dict = Field(default_factory=dict)

    @field_validator("notable_features", mode="before")
    @classmethod
    def _parse_features(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return [v]
        return v


# =============================================================================
# OBJECT
# =============================================================================


class ObjectData(BaseModel):
    """An object in the world or inventory"""

    name: Name
    category: Tag | None = None
    description: Text | None = None
    transportable: bool = True
    stackable: bool = False
    base_value: int | None = None
    # For initial inventory (quantity)
    quantity: int = Field(default=1, ge=1)
    # Flexible
    details: dict = Field(default_factory=dict)


# =============================================================================
# ORGANIZATION
# =============================================================================


class OrganizationData(BaseModel):
    """A company, faction, or group"""

    name: Name
    org_type: Tag | None = None
    domain: Tag | None = None
    size: Tag | None = None
    description: Text | None = None
    reputation: ShortText | None = None
    headquarters_ref: EntityRef | None = None
    founding_cycle: Cycle | None = None
    ambient: ShortText | None = None
    # Flexible
    details: dict = Field(default_factory=dict)
