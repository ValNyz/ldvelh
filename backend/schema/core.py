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
    """
    Types de faits - catégorisation précise pour éviter les ambiguïtés.
    Choisir le type le PLUS SPÉCIFIQUE applicable.
    """

    # === ACTIONS ===
    ACTION = "action"  # Valentin fait quelque chose de significatif
    NPC_ACTION = "npc_action"  # Un PNJ fait quelque chose d'observable

    # === COMMUNICATION ===
    STATEMENT = "statement"  # Déclaration factuelle, opinion exprimée
    REVELATION = "revelation"  # Information importante/secrète révélée
    PROMISE = "promise"  # Engagement verbal (je ferai X)
    REQUEST = "request"  # Demande faite (peux-tu faire X?)
    REFUSAL = "refusal"  # Refus explicite d'une demande
    QUESTION = "question"  # Question significative posée

    # === PERCEPTION ===
    OBSERVATION = "observation"  # Valentin remarque/déduit quelque chose
    ATMOSPHERE = "atmosphere"  # Ambiance, tension, contexte émotionnel

    # === CHANGEMENTS D'ÉTAT ===
    STATE_CHANGE = "state_change"  # Changement de relation, statut, humeur
    ACQUISITION = "acquisition"  # Gain: objet, info, compétence, accès
    LOSS = "loss"  # Perte: objet, relation, opportunité

    # === SOCIAL ===
    ENCOUNTER = "encounter"  # Première rencontre avec quelqu'un/quelque chose
    INTERACTION = "interaction"  # Échange social significatif (pas small talk)
    CONFLICT = "conflict"  # Tension, désaccord, confrontation

    # === TEMPOREL ===
    FLASHBACK = "flashback"  # Information sur le passé (backstory)
    FORESHADOW = "foreshadow"  # Élément annonçant un futur potentiel

    # === META ===
    DECISION = "decision"  # Choix significatif fait par Valentin
    REALIZATION = "realization"  # Prise de conscience de Valentin


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
    AFTERNOON = "afternoon"
    NOON = "noon"
    EVENING = "evening"
    NIGHT = "night"


# =============================================================================
# TYPE ALIASES
# =============================================================================

Cycle = Annotated[
    int, Field(description="Cycle number. Negative=past, 1=arrival, positive=future")
]
EntityRef = Annotated[
    str, Field(description="Reference to entity by name (case-insensitive)")
]


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
