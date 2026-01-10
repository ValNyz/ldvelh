"""
LDVELH - Entity Schema Models
Modèles pour chaque type d'entité, réutilisables partout
"""

import logging
from pydantic import BaseModel, Field, field_validator

from .core import (
    ArcDomain,
    Backstory,
    Cycle,
    DepartureReason,
    EntityRef,
    FullText,
    Label,
    LongText,
    Name,
    OrgSize,
    Phrase,
    ShortText,
    Skill,
    Tag,
    TemporalValidationMixin,
    Text,
    normalize_departure_reason,
    normalize_org_size,
)
from .narrative import CharacterArc

logger = logging.getLogger(__name__)


# =============================================================================
# WORLD / STATION
# =============================================================================


class WorldData(BaseModel, TemporalValidationMixin):
    """The space station/habitat - top-level location"""

    name: Name  # 100 chars
    station_type: Tag  # 50 chars
    population: int = Field(..., ge=100, le=5_000_000)
    atmosphere: Tag  # 50 chars - 2-3 words
    description: FullText  # 500 chars
    sectors: list[str] = Field(..., min_length=2, max_length=10)
    founding_cycle: Cycle = Field(
        default=-5000,
        le=-100,
        description="When station was founded. -5000 = ~13 years ago",
    )


# =============================================================================
# PROTAGONIST
# =============================================================================


class ProtagonistData(BaseModel):
    """The player character"""

    name: Tag = "Valentin"  # 50 chars
    origin_location: Name  # 100 chars
    departure_reason: DepartureReason
    departure_story: LongText  # 400 chars
    backstory: Backstory  # 600 chars
    hobbies: list[str] = Field(..., min_length=2, max_length=5)
    skills: list[Skill] = Field(..., min_length=2, max_length=6)
    initial_credits: int = Field(..., ge=0, le=10000)
    initial_energy: float = Field(default=3.0, ge=0, le=5)
    initial_morale: float = Field(default=3.0, ge=0, le=5)
    initial_health: float = Field(default=4.0, ge=0, le=5)

    @field_validator("departure_reason", mode="before")
    @classmethod
    def _normalize_departure_reason(cls, v):
        return normalize_departure_reason(v)


# =============================================================================
# PERSONAL AI
# =============================================================================


class PersonalAIData(BaseModel):
    """The protagonist's AI companion"""

    name: Label  # 30 chars
    voice_description: Phrase  # 150 chars
    personality_traits: list[str] = Field(..., min_length=2, max_length=5)
    substrate: Tag = "personal_device"  # 50 chars
    quirk: ShortText  # 200 chars


# =============================================================================
# CHARACTER (NPC)
# =============================================================================


class CharacterData(BaseModel, TemporalValidationMixin):
    """An NPC in the world"""

    name: Name  # 100 chars
    species: Tag = "human"  # 50 chars
    gender: Label  # 30 chars
    pronouns: Label  # 30 chars
    age: int | None = Field(default=None, ge=1, le=1000)
    physical_description: Text  # 300 chars
    personality_traits: list[str] = Field(..., min_length=2, max_length=6)
    occupation: Name  # 100 chars
    workplace_ref: EntityRef | None = None
    residence_ref: EntityRef | None = None
    origin_location: Name | None = None  # 100 chars
    station_arrival_cycle: Cycle = Field(
        ...,
        le=1,
        description="When they arrived. Veterans: -4000 to -2000. Recent: -100 to -1",
    )

    # Multiple arcs per character
    arcs: list[CharacterArc] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Multiple life arcs: work, personal, romantic, etc.",
    )

    # Meta
    is_mandatory: bool = Field(default=False)
    romantic_potential: bool = Field(default=False)
    initial_relationship_to_protagonist: ShortText | None = None  # 200 chars

    @field_validator("arcs")
    @classmethod
    def validate_arc_diversity(cls, v: list[CharacterArc]) -> list[CharacterArc]:
        """Encourage diverse arc domains - soft validation"""
        domains = [arc.domain for arc in v]
        if len(v) >= 3 and len(set(domains)) < 2:
            logger.warning(
                f"[Validation] Character has {len(v)} arcs but only "
                f"{len(set(domains))} domain(s) - diversity encouraged"
            )
        return v


# =============================================================================
# LOCATION
# =============================================================================


class LocationData(BaseModel):
    """A place in the station"""

    name: Name  # 100 chars
    location_type: Tag  # 50 chars
    sector: Tag | None = None  # 50 chars
    description: LongText  # 400 chars
    atmosphere: Name  # 100 chars - slightly longer for locations
    parent_location_ref: EntityRef | None = None
    accessible: bool = True
    notable_features: list[str] = Field(default_factory=list, max_length=5)
    typical_crowd: Phrase | None = None  # 150 chars
    operating_hours: Tag | None = None  # 50 chars


# =============================================================================
# OBJECT
# =============================================================================


class ObjectData(BaseModel):
    """An item that can be owned"""

    name: Name  # 100 chars
    category: Tag  # 50 chars
    description: ShortText  # 200 chars
    transportable: bool = True
    stackable: bool = False
    quantity: int = Field(default=1, ge=1)
    base_value: int = Field(default=0, ge=0)
    emotional_significance: Phrase | None = None  # 150 chars


# =============================================================================
# ORGANIZATION
# =============================================================================


class OrganizationData(BaseModel, TemporalValidationMixin):
    """A company, faction, or group"""

    name: Name  # 100 chars
    org_type: Tag  # 50 chars
    domain: Name  # 100 chars
    size: OrgSize
    description: FullText  # 500 chars
    reputation: Phrase  # 150 chars
    headquarters_ref: EntityRef | None = None
    founding_cycle: Cycle | None = Field(default=None, le=1)
    is_employer: bool = False

    @field_validator("size", mode="before")
    @classmethod
    def _normalize_size(cls, v):
        return normalize_org_size(v)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_minimal_character(
    name: str, occupation: str, station_arrival_cycle: int, **kwargs
) -> CharacterData:
    """Create a character with minimal required fields + sensible defaults"""
    defaults = {
        "species": "human",
        "gender": "non-spécifié",
        "pronouns": "iel",
        "physical_description": "Apparence ordinaire",
        "personality_traits": ["discret"],
        "arcs": [
            CharacterArc(
                domain=ArcDomain.PROFESSIONAL,
                title=f"Travail de {name}",
                situation=f"Travaille comme {occupation}",
                desire="Continuer ainsi",
                obstacle="La routine",
                potential_evolution="À découvrir",
            )
        ],
    }
    defaults.update(kwargs)
    return CharacterData(
        name=name,
        occupation=occupation,
        station_arrival_cycle=station_arrival_cycle,
        **defaults,
    )
