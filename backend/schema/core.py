"""
LDVELH - Core Schema
Enums, types primitifs, modèles de base réutilisables partout
Inclut les fonctions de normalisation et types avec troncature auto
"""

import logging
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

from .synonyms import (
    ARC_DOMAIN_SYNONYMS,
    CERTAINTY_SYNONYMS,
    COMMITMENT_TYPE_SYNONYMS,
    DEPARTURE_REASON_SYNONYMS,
    ENTITY_TYPE_SYNONYMS,
    FACT_TYPE_SYNONYMS,
    MOMENT_SYNONYMS,
    ORG_SIZE_SYNONYMS,
    PARTICIPANT_ROLE_SYNONYMS,
    RELATION_TYPE_SYNONYMS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# TRUNCATED STRING TYPES
# =============================================================================


def _truncate(max_len: int):
    """Factory pour créer une fonction de troncature."""

    def _inner(v: Any) -> str | None:
        if v is None:
            return None
        v = str(v)
        if len(v) <= max_len:
            return v
        # Tronquer au dernier mot complet
        truncated = v[: max_len - 3].rsplit(" ", 1)[0] + "..."
        logger.warning(f"[Truncate] {len(v)} → {len(truncated)} chars")
        return truncated

    return _inner


# Types avec troncature automatique - alignés pour instructions LLM claires
# Utiliser ces types au lieu de `str = Field(..., max_length=X)`

Label = Annotated[str, BeforeValidator(_truncate(30)), StringConstraints(max_length=30)]
"""30 chars - 2-3 mots (pronouns, gender, tags)"""

Tag = Annotated[str, BeforeValidator(_truncate(50)), StringConstraints(max_length=50)]
"""50 chars - quelques mots (type, category, sector)"""

Mood = Annotated[str, BeforeValidator(_truncate(80)), StringConstraints(max_length=80)]
"""80 chars - une courte phrase (ambiance, humeur)"""

Name = Annotated[
    str, BeforeValidator(_truncate(100)), StringConstraints(max_length=100)
]
"""100 chars - nom complet (entités, occupation, title)"""

Phrase = Annotated[
    str, BeforeValidator(_truncate(150)), StringConstraints(max_length=150)
]
"""150 chars - 1-2 phrases (desire, obstacle, reputation)"""

ShortText = Annotated[
    str, BeforeValidator(_truncate(200)), StringConstraints(max_length=200)
]
"""200 chars - 2-3 phrases (quirk, context, description courte)"""

Text = Annotated[
    str, BeforeValidator(_truncate(300)), StringConstraints(max_length=300)
]
"""300 chars - court paragraphe (description, situation, notes)"""

LongText = Annotated[
    str, BeforeValidator(_truncate(400)), StringConstraints(max_length=400)
]
"""400 chars - paragraphe (departure_story, location description)"""

FullText = Annotated[
    str, BeforeValidator(_truncate(500)), StringConstraints(max_length=500)
]
"""500 chars - paragraphe détaillé (world/org description)"""

Backstory = Annotated[
    str, BeforeValidator(_truncate(600)), StringConstraints(max_length=600)
]
"""600 chars - historique complet"""


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


class RelationCategory(str, Enum):
    """Categories of relations"""

    SOCIAL = "social"
    PROFESSIONAL = "professional"
    SPATIAL = "spatial"
    OWNERSHIP = "ownership"


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

    @property
    def category(self) -> RelationCategory:
        """Returns the category of this relation type"""
        return _RELATION_CATEGORY_MAP[self]


# Mapping relation types to categories
_RELATION_CATEGORY_MAP: dict[RelationType, RelationCategory] = {
    RelationType.KNOWS: RelationCategory.SOCIAL,
    RelationType.FRIEND_OF: RelationCategory.SOCIAL,
    RelationType.ENEMY_OF: RelationCategory.SOCIAL,
    RelationType.FAMILY_OF: RelationCategory.SOCIAL,
    RelationType.ROMANTIC: RelationCategory.SOCIAL,
    RelationType.EMPLOYED_BY: RelationCategory.PROFESSIONAL,
    RelationType.COLLEAGUE_OF: RelationCategory.PROFESSIONAL,
    RelationType.MANAGES: RelationCategory.PROFESSIONAL,
    RelationType.FREQUENTS: RelationCategory.SPATIAL,
    RelationType.LIVES_AT: RelationCategory.SPATIAL,
    RelationType.LOCATED_IN: RelationCategory.SPATIAL,
    RelationType.WORKS_AT: RelationCategory.SPATIAL,
    RelationType.OWNS: RelationCategory.OWNERSHIP,
    RelationType.OWES_TO: RelationCategory.OWNERSHIP,
}


class CertaintyLevel(str, Enum):
    CERTAIN = "certain"
    PROBABLE = "probable"
    RUMOR = "rumor"
    UNCERTAIN = "uncertain"


class FactType(str, Enum):
    ACTION = "action"
    NPC_ACTION = "npc_action"
    STATEMENT = "statement"
    REVELATION = "revelation"
    PROMISE = "promise"
    REQUEST = "request"
    REFUSAL = "refusal"
    QUESTION = "question"
    OBSERVATION = "observation"
    ATMOSPHERE = "atmosphere"
    STATE_CHANGE = "state_change"
    ACQUISITION = "acquisition"
    LOSS = "loss"
    ENCOUNTER = "encounter"
    INTERACTION = "interaction"
    CONFLICT = "conflict"
    FLASHBACK = "flashback"
    FORESHADOW = "foreshadow"
    DECISION = "decision"
    REALIZATION = "realization"


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


class OrgSize(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    STATION_WIDE = "station-wide"


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
# ENUM NORMALIZERS - Pour utilisation dans field_validator(mode="before")
# =============================================================================


def _normalize_enum_value(
    value: Any,
    synonyms: dict[str, str],
    enum_class: type[Enum],
    field_name: str,
) -> str:
    """
    Normalise une valeur vers une valeur d'enum valide.
    Retourne la valeur canonique (str) pour que Pydantic la convertisse en enum.
    """
    if value is None:
        return value

    # Si c'est déjà l'enum, extraire la valeur
    if isinstance(value, enum_class):
        return value.value

    # Normaliser la clé
    key = str(value).lower().strip().replace(" ", "_").replace("-", "_")

    # Chercher dans les synonymes
    result = synonyms.get(key)

    if result is None:
        # Vérifier si c'est déjà une valeur valide de l'enum
        valid_values = {e.value for e in enum_class}
        if key in valid_values:
            return key

        # Fallback: première valeur de l'enum
        fallback = list(enum_class)[0].value
        logger.warning(
            f"[Normalizer] Unknown {field_name}='{value}' → fallback '{fallback}'"
        )
        return fallback

    if key != result:
        logger.info(f"[Normalizer] {field_name}: '{value}' → '{result}'")

    return result


def normalize_entity_type(value: Any) -> str:
    """Normalise EntityType"""
    return _normalize_enum_value(value, ENTITY_TYPE_SYNONYMS, EntityType, "entity_type")


def normalize_relation_type(value: Any) -> str:
    """Normalise RelationType"""
    return _normalize_enum_value(
        value, RELATION_TYPE_SYNONYMS, RelationType, "relation_type"
    )


def normalize_certainty(value: Any) -> str:
    """Normalise CertaintyLevel"""
    return _normalize_enum_value(value, CERTAINTY_SYNONYMS, CertaintyLevel, "certainty")


def normalize_fact_type(value: Any) -> str:
    """Normalise FactType"""
    return _normalize_enum_value(value, FACT_TYPE_SYNONYMS, FactType, "fact_type")


def normalize_participant_role(value: Any) -> str:
    """Normalise ParticipantRole"""
    return _normalize_enum_value(
        value, PARTICIPANT_ROLE_SYNONYMS, ParticipantRole, "participant_role"
    )


def normalize_commitment_type(value: Any) -> str:
    """Normalise CommitmentType"""
    return _normalize_enum_value(
        value, COMMITMENT_TYPE_SYNONYMS, CommitmentType, "commitment_type"
    )


def normalize_arc_domain(value: Any) -> str:
    """Normalise ArcDomain"""
    return _normalize_enum_value(value, ARC_DOMAIN_SYNONYMS, ArcDomain, "arc_domain")


def normalize_departure_reason(value: Any) -> str:
    """Normalise DepartureReason"""
    return _normalize_enum_value(
        value, DEPARTURE_REASON_SYNONYMS, DepartureReason, "departure_reason"
    )


def normalize_moment(value: Any) -> str:
    """Normalise Moment"""
    return _normalize_enum_value(value, MOMENT_SYNONYMS, Moment, "moment")


def normalize_org_size(value: Any) -> str:
    """Normalise OrgSize"""
    return _normalize_enum_value(value, ORG_SIZE_SYNONYMS, OrgSize, "org_size")


# =============================================================================
# TEMPORAL VALIDATION
# =============================================================================


class TemporalValidationMixin:
    """Mixin for models needing temporal coherence validation"""

    @staticmethod
    def is_temporally_valid(
        arrival_cycle: int | None, founding_cycle: int | None, context: str = ""
    ) -> bool:
        """
        Check if arrival happened after founding (more negative = earlier).
        Returns True if valid, False if invalid.
        Logs a warning if invalid.
        """
        if arrival_cycle is not None and founding_cycle is not None:
            if arrival_cycle < founding_cycle:
                logger.warning(
                    f"[Temporal] {context}: arrival_cycle ({arrival_cycle}) "
                    f"before founding_cycle ({founding_cycle}) - filtering"
                )
                return False
        return True


# =============================================================================
# BASE MODELS
# =============================================================================


class Skill(BaseModel):
    """A skill with level 1-5"""

    name: Tag  # 50 chars
    level: int = Field(..., ge=1, le=5)


class Attribute(BaseModel):
    """A key-value attribute for any entity"""

    key: Name  # 100 chars
    value: str
    details: dict | None = None
