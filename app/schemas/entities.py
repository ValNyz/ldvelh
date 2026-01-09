"""
LDVELH - Entity Schema Models
Modèles pour chaque type d'entité, réutilisables partout
"""

from pydantic import BaseModel, Field, field_validator

from .core import ArcDomain, Cycle, DepartureReason, EntityRef, Skill, TemporalValidationMixin
from .narrative import CharacterArc

# =============================================================================
# WORLD / STATION
# =============================================================================


class WorldData(BaseModel, TemporalValidationMixin):
    """The space station/habitat - top-level location"""

    name: str = Field(..., max_length=100)
    station_type: str = Field(..., max_length=50)
    population: int = Field(..., ge=100, le=5_000_000)
    atmosphere: str = Field(..., max_length=50, description="2-3 words")
    description: str = Field(..., max_length=500)
    sectors: list[str] = Field(..., min_length=2, max_length=10)
    founding_cycle: Cycle = Field(default=-5000, le=-100, description="When station was founded. -5000 = ~13 years ago")


# =============================================================================
# PROTAGONIST
# =============================================================================


class ProtagonistData(BaseModel):
    """The player character"""

    name: str = Field(default="Valentin", max_length=50)
    origin_location: str = Field(..., max_length=100)
    departure_reason: DepartureReason
    departure_story: str = Field(..., max_length=400)
    backstory: str = Field(..., max_length=600)
    hobbies: list[str] = Field(..., min_length=2, max_length=5)
    skills: list[Skill] = Field(..., min_length=2, max_length=6)
    initial_credits: int = Field(..., ge=0, le=10000)
    initial_energy: float = Field(default=3.0, ge=0, le=5)
    initial_morale: float = Field(default=3.0, ge=0, le=5)
    initial_health: float = Field(default=4.0, ge=0, le=5)


# =============================================================================
# PERSONAL AI
# =============================================================================

FORBIDDEN_AI_NAMES = frozenset(
    [
        "aria",
        "nova",
        "luna",
        "stella",
        "aurora",
        "athena",
        "cortana",
        "alexa",
        "siri",
        "echo",
        "iris",
        "lyra",
        "astra",
        "vega",
        "maya",
        "eve",
        "ava",
        "zoe",
        "cleo",
        "neo",
        "max",
        "sam",
        "friday",
        "jarvis",
    ]
)


class PersonalAIData(BaseModel):
    """The protagonist's AI companion"""

    name: str = Field(..., max_length=30)
    voice_description: str = Field(..., max_length=150)
    personality_traits: list[str] = Field(..., min_length=2, max_length=5)
    substrate: str = Field(default="personal_device", max_length=50)
    quirk: str = Field(..., max_length=200)

    @field_validator("name")
    @classmethod
    def validate_ai_name(cls, v: str) -> str:
        if v.lower() in FORBIDDEN_AI_NAMES:
            raise ValueError(f"AI name '{v}' is too common/cliché. Choose something original.")
        return v


# =============================================================================
# CHARACTER (NPC)
# =============================================================================


class CharacterData(BaseModel, TemporalValidationMixin):
    """An NPC in the world"""

    name: str = Field(..., max_length=100)
    species: str = Field(default="human", max_length=50)
    gender: str = Field(..., max_length=30)
    pronouns: str = Field(..., max_length=20)
    age: int | None = Field(default=None, ge=1, le=1000)
    physical_description: str = Field(..., max_length=300)
    personality_traits: list[str] = Field(..., min_length=2, max_length=6)
    occupation: str = Field(..., max_length=100)
    workplace_ref: EntityRef | None = None
    residence_ref: EntityRef | None = None
    origin_location: str | None = Field(default=None, max_length=100)
    station_arrival_cycle: Cycle = Field(
        ..., le=1, description="When they arrived. Veterans: -4000 to -2000. Recent: -100 to -1"
    )

    # Multiple arcs per character
    arcs: list[CharacterArc] = Field(
        ..., min_length=1, max_length=5, description="Multiple life arcs: work, personal, romantic, etc."
    )

    # Meta
    is_mandatory: bool = Field(default=False)
    romantic_potential: bool = Field(default=False)
    initial_relationship_to_protagonist: str | None = Field(default=None, max_length=200)

    @field_validator("arcs")
    @classmethod
    def validate_arc_diversity(cls, v: list[CharacterArc]) -> list[CharacterArc]:
        """Encourage diverse arc domains"""
        domains = [arc.domain for arc in v]
        if len(v) >= 3 and len(set(domains)) < 2:
            raise ValueError("Character with 3+ arcs should have at least 2 different domains")
        return v


# =============================================================================
# LOCATION
# =============================================================================


class LocationData(BaseModel):
    """A place in the station"""

    name: str = Field(..., max_length=100)
    location_type: str = Field(..., max_length=50)
    sector: str | None = Field(default=None, max_length=50)
    description: str = Field(..., max_length=400)
    atmosphere: str = Field(..., max_length=100)
    parent_location_ref: EntityRef | None = None
    accessible: bool = True
    notable_features: list[str] = Field(default_factory=list, max_length=5)
    typical_crowd: str | None = Field(default=None, max_length=150)
    operating_hours: str | None = Field(default=None, max_length=50)


# =============================================================================
# OBJECT
# =============================================================================


class ObjectData(BaseModel):
    """An item that can be owned"""

    name: str = Field(..., max_length=100)
    category: str = Field(..., max_length=50)
    description: str = Field(..., max_length=200)
    transportable: bool = True
    stackable: bool = False
    quantity: int = Field(default=1, ge=1)
    base_value: int = Field(default=0, ge=0)
    emotional_significance: str | None = Field(default=None, max_length=150)


# =============================================================================
# ORGANIZATION
# =============================================================================


class OrganizationData(BaseModel, TemporalValidationMixin):
    """A company, faction, or group"""

    name: str = Field(..., max_length=100)
    org_type: str = Field(..., max_length=50)
    domain: str = Field(..., max_length=100)
    size: str = Field(..., pattern="^(small|medium|large|station-wide)$")
    description: str = Field(..., max_length=300)
    reputation: str = Field(..., max_length=150)
    headquarters_ref: EntityRef | None = None
    founding_cycle: Cycle | None = Field(default=None, le=1)
    is_employer: bool = False


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_minimal_character(name: str, occupation: str, station_arrival_cycle: int, **kwargs) -> CharacterData:
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
    return CharacterData(name=name, occupation=occupation, station_arrival_cycle=station_arrival_cycle, **defaults)
