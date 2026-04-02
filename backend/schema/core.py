"""
LDVELH - Core Schema
Enums, primitive types, base models, normalization functions
"""

import logging
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    StringConstraints,
    model_validator,
)

from .synonyms import (
    ARC_DOMAIN_SYNONYMS,
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
# TRUNCATED TEXT TYPES
# =============================================================================


def _truncate(max_len: int):
    """Factory to create a truncation function."""

    def _inner(v: Any) -> str | None:
        if v is None:
            return None
        v = str(v)
        if len(v) <= max_len:
            return v
        truncated = v[: max_len - 3].rsplit(" ", 1)[0] + "..."
        logger.warning(f"[Truncate] {len(v)} -> {len(truncated)} chars")
        return truncated

    return _inner


Label = Annotated[str, BeforeValidator(_truncate(30)), StringConstraints(max_length=30)]
"""30 chars - 2-3 words (pronouns, gender, tags)"""

Tag = Annotated[str, BeforeValidator(_truncate(50)), StringConstraints(max_length=50)]
"""50 chars - a few words (type, category, sector)"""

Mood = Annotated[str, BeforeValidator(_truncate(80)), StringConstraints(max_length=80)]
"""80 chars - short sentence (atmosphere, mood)"""

Name = Annotated[
    str, BeforeValidator(_truncate(100)), StringConstraints(max_length=100)
]
"""100 chars - full name (entities, occupation)"""

Phrase = Annotated[
    str, BeforeValidator(_truncate(150)), StringConstraints(max_length=150)
]
"""150 chars - 1-2 sentences (desire, obstacle)"""

ShortText = Annotated[
    str, BeforeValidator(_truncate(200)), StringConstraints(max_length=200)
]
"""200 chars - 2-3 sentences (quirk, context)"""

Text = Annotated[
    str, BeforeValidator(_truncate(300)), StringConstraints(max_length=300)
]
"""300 chars - short paragraph (description)"""

LongText = Annotated[
    str, BeforeValidator(_truncate(400)), StringConstraints(max_length=400)
]
"""400 chars - paragraph"""

FullText = Annotated[
    str, BeforeValidator(_truncate(500)), StringConstraints(max_length=500)
]
"""500 chars - detailed paragraph"""

Backstory = Annotated[
    str, BeforeValidator(_truncate(600)), StringConstraints(max_length=600)
]
"""600 chars - full backstory"""


# =============================================================================
# ENUMS
# =============================================================================


class EntityType(str, Enum):
    PROTAGONIST = "protagonist"
    CHARACTER = "character"
    LOCATION = "location"
    OBJECT = "object"
    ORGANIZATION = "organization"


class RelationCategory(str, Enum):
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
        return _RELATION_CATEGORY_MAP[self]


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


class EventType(str, Enum):
    APPOINTMENT = "appointment"
    DEADLINE = "deadline"
    CELEBRATION = "celebration"
    RECURRING = "recurring"
    FINANCIAL_DUE = "financial_due"
    MILESTONE = "milestone"


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
# NORMALIZATION FUNCTIONS
# =============================================================================


def _normalize_enum_value(
    value: Any,
    synonyms: dict[str, str],
    enum_class: type[Enum],
    field_name: str,
) -> str:
    """Normalize a value to a valid enum value using synonym lookup."""
    if value is None:
        return value

    if isinstance(value, enum_class):
        return value.value

    key = str(value).lower().strip().replace(" ", "_").replace("-", "_")
    result = synonyms.get(key)

    if result is None:
        valid_values = {e.value for e in enum_class}
        if key in valid_values:
            return key
        fallback = list(enum_class)[0].value
        logger.warning(
            f"[Normalizer] Unknown {field_name}='{value}' -> fallback '{fallback}'"
        )
        return fallback

    if key != result:
        logger.info(f"[Normalizer] {field_name}: '{value}' -> '{result}'")

    return result


def normalize_entity_type(value: Any) -> str:
    return _normalize_enum_value(value, ENTITY_TYPE_SYNONYMS, EntityType, "entity_type")


def normalize_relation_type(value: Any) -> str:
    return _normalize_enum_value(
        value, RELATION_TYPE_SYNONYMS, RelationType, "relation_type"
    )


def normalize_fact_type(value: Any) -> str:
    return _normalize_enum_value(value, FACT_TYPE_SYNONYMS, FactType, "fact_type")


def normalize_participant_role(value: Any) -> str:
    return _normalize_enum_value(
        value, PARTICIPANT_ROLE_SYNONYMS, ParticipantRole, "participant_role"
    )


def normalize_arc_domain(value: Any) -> str:
    return _normalize_enum_value(value, ARC_DOMAIN_SYNONYMS, ArcDomain, "arc_domain")


def normalize_departure_reason(value: Any) -> str:
    return _normalize_enum_value(
        value, DEPARTURE_REASON_SYNONYMS, DepartureReason, "departure_reason"
    )


def normalize_moment(value: Any) -> str:
    return _normalize_enum_value(value, MOMENT_SYNONYMS, Moment, "moment")


def normalize_org_size(value: Any) -> str:
    return _normalize_enum_value(value, ORG_SIZE_SYNONYMS, OrgSize, "org_size")


# =============================================================================
# TYPE ALIASES
# =============================================================================

Cycle = Annotated[
    int, Field(description="Cycle number. Negative=past, 1=arrival, positive=future")
]
EntityRef = Annotated[
    str, Field(description="Reference to an entity by name (case-insensitive)")
]


# =============================================================================
# BASE MODELS
# =============================================================================


class Skill(BaseModel):
    """Skill with level 1-5"""

    name: Tag  # 50 chars
    level: int = Field(..., ge=1, le=5)


# =============================================================================
# TEMPORAL VALIDATION
# =============================================================================


class TemporalValidationMixin:
    """Mixin for models requiring temporal coherence validation"""

    @model_validator(mode="after")
    def enforce_temporal_coherence(self):
        arrival = getattr(self, "arrival_cycle", None)
        founding = getattr(self, "founding_cycle", None)

        if arrival is not None and founding is not None:
            if arrival < founding:
                logger.warning(
                    f"[Temporal] {self.__class__.__name__}: arrival_cycle ({arrival}) "
                    f"before founding_cycle ({founding}) - correcting to founding_cycle"
                )
                self.arrival_cycle = founding

        return self
