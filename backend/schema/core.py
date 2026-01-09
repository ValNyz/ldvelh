"""
LDVELH - Core Schema
Enums, types primitifs, modèles de base réutilisables partout
"""

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

# =============================================================================
# ENUMS
# =============================================================================


class EntityType(str, Enum):
    PROTAGONIST = "protagonist"
    CHARACTER = "character"
    LOCATION = "location"
    OBJECT = "object"
    AI = "ai"
    ORGANIZATION = "organization"


class RelationType(str, Enum):
    # Social
    KNOWS = "knows"
    FRIEND_OF = "friend_of"
    ENEMY_OF = "enemy_of"
    FAMILY_OF = "family_of"
    ROMANTIC = "romantic"
    # Professional
    EMPLOYED_BY = "employed_by"
    COLLEAGUE_OF = "colleague_of"
    MANAGES = "manages"
    # Spatial
    FREQUENTS = "frequents"
    LIVES_AT = "lives_at"
    LOCATED_IN = "located_in"
    WORKS_AT = "works_at"
    # Ownership
    OWNS = "owns"
    OWES_TO = "owes_to"


class CertaintyLevel(str, Enum):
    CERTAIN = "certain"
    PROBABLE = "probable"
    RUMOR = "rumor"
    UNCERTAIN = "uncertain"


class FactType(str, Enum):
    ACTION = "action"
    DIALOGUE = "dialogue"
    DISCOVERY = "discovery"
    INCIDENT = "incident"
    ENCOUNTER = "encounter"


class FactDomain(str, Enum):
    PERSONAL = "personal"
    PROFESSIONAL = "professional"
    ROMANTIC = "romantic"
    SOCIAL = "social"
    EXPLORATION = "exploration"
    FINANCIAL = "financial"
    OTHER = "other"


class ParticipantRole(str, Enum):
    ACTOR = "actor"
    WITNESS = "witness"
    TARGET = "target"
    MENTIONED = "mentioned"


class CommitmentType(str, Enum):
    FORESHADOWING = "foreshadowing"
    SECRET = "secret"
    SETUP = "setup"
    CHEKHOV_GUN = "chekhov_gun"
    ARC = "arc"


class ArcDomain(str, Enum):
    """Domains for character arcs"""

    PROFESSIONAL = "professional"
    PERSONAL = "personal"
    ROMANTIC = "romantic"
    SOCIAL = "social"
    FAMILY = "family"
    FINANCIAL = "financial"
    HEALTH = "health"
    EXISTENTIAL = "existential"


class DepartureReason(str, Enum):
    FLIGHT = "flight"
    BREAKUP = "breakup"
    OPPORTUNITY = "opportunity"
    FRESH_START = "fresh_start"
    STANDARD = "standard"
    BROKE = "broke"
    OTHER = "other"


class Moment(str, Enum):
    MORNING = "morning"
    NOON = "noon"
    EVENING = "evening"
    NIGHT = "night"


# =============================================================================
# TYPE ALIASES
# =============================================================================

Cycle = Annotated[int, Field(description="Cycle number. Negative=past, 1=arrival, positive=future")]
EntityRef = Annotated[str, Field(description="Reference to entity by name (case-insensitive)")]


# =============================================================================
# TEMPORAL VALIDATION
# =============================================================================


class TemporalValidationMixin:
    """Mixin for models needing temporal coherence validation"""

    @staticmethod
    def validate_arrival_after_founding(
        arrival_cycle: int | None, founding_cycle: int | None, context: str = ""
    ) -> None:
        """Ensure arrival happened after founding (more negative = earlier)"""
        if arrival_cycle is not None and founding_cycle is not None:
            if arrival_cycle < founding_cycle:
                raise ValueError(
                    f"{context}: arrival_cycle ({arrival_cycle}) cannot be before founding_cycle ({founding_cycle})"
                )


# =============================================================================
# BASE MODELS - RÉUTILISABLES PARTOUT
# =============================================================================


class Skill(BaseModel):
    """A skill with level 1-5"""

    name: str = Field(..., max_length=50)
    level: int = Field(..., ge=1, le=5)


class Attribute(BaseModel):
    """A key-value attribute for any entity"""

    key: str = Field(..., max_length=100)
    value: str
    details: dict | None = None
