"""
LDVELH - Core Schema
Enums, types primitifs, modèles de base réutilisables partout
Inclut les fonctions de normalisation et types avec troncature auto
"""

import logging
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    StringConstraints,
    field_validator,
)

from .synonyms import (
    ARC_DOMAIN_SYNONYMS,
    COMMITMENT_TYPE_SYNONYMS,
    DEPARTURE_REASON_SYNONYMS,
    ENTITY_TYPE_SYNONYMS,
    FACT_TYPE_SYNONYMS,
    MOMENT_SYNONYMS,
    ORG_SIZE_SYNONYMS,
    PARTICIPANT_ROLE_SYNONYMS,
    RELATION_TYPE_SYNONYMS,
    normalize_key,
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


class AttributeKey(str, Enum):
    """
    Clés d'attributs autorisées.
    Validation stricte par type d'entité via VALID_KEYS_BY_ENTITY.
    """

    # === SHARED (multi-types) ===
    DESCRIPTION = "description"
    HISTORY = "history"
    SECRET = "secret"
    REPUTATION = "reputation"

    # === CHARACTER ===
    MOOD = "mood"
    AGE = "age"
    VOICE = "voice"
    QUIRK = "quirk"
    ORIGIN = "origin"
    MOTIVATION = "motivation"
    FINANCIAL_STATUS = "financial_status"
    HEALTH_STATUS = "health_status"
    RELATIONSHIP_STATUS = "relationship_status"
    ARCS = "arcs"

    # === LOCATION ===
    ATMOSPHERE = "atmosphere"
    CROWD_LEVEL = "crowd_level"
    NOISE_LEVEL = "noise_level"
    CLEANLINESS = "cleanliness"
    PRICE_RANGE = "price_range"
    OPERATING_HOURS = "operating_hours"
    NOTABLE_FEATURES = "notable_features"
    TYPICAL_CROWD = "typical_crowd"

    # === OBJECT ===
    CONDITION = "condition"
    HIDDEN_FUNCTION = "hidden_function"
    EMOTIONAL_SIGNIFICANCE = "emotional_significance"
    ACTUAL_VALUE = "actual_value"

    # === ORGANIZATION ===
    PUBLIC_FACADE = "public_facade"
    TRUE_PURPOSE = "true_purpose"
    INFLUENCE_LEVEL = "influence_level"

    # === PROTAGONIST ===
    CREDITS = "credits"
    ENERGY = "energy"
    MORALE = "morale"
    HEALTH = "health"
    HOBBIES = "hobbies"
    DEPARTURE_REASON = "departure_reason"


class AttributeVisibility(str, Enum):
    """Visibilité par défaut d'un attribut pour le protagoniste"""

    ALWAYS = "always"  # Observable directement → known=true
    NEVER = "never"  # Caché par défaut → known=false
    CONDITIONAL = "conditional"  # Dépend du contexte narratif → analyse requise


# =============================================================================
# ATTRIBUTE VISIBILITY MAPPING
# =============================================================================

ATTRIBUTE_DEFAULT_VISIBILITY: dict[AttributeKey, AttributeVisibility] = {
    # === ALWAYS (Valentin observe/perçoit directement) ===
    AttributeKey.DESCRIPTION: AttributeVisibility.ALWAYS,
    AttributeKey.MOOD: AttributeVisibility.ALWAYS,
    AttributeKey.VOICE: AttributeVisibility.ALWAYS,
    AttributeKey.QUIRK: AttributeVisibility.ALWAYS,
    AttributeKey.ATMOSPHERE: AttributeVisibility.ALWAYS,
    AttributeKey.CROWD_LEVEL: AttributeVisibility.ALWAYS,
    AttributeKey.NOISE_LEVEL: AttributeVisibility.ALWAYS,
    AttributeKey.CLEANLINESS: AttributeVisibility.ALWAYS,
    AttributeKey.NOTABLE_FEATURES: AttributeVisibility.ALWAYS,
    AttributeKey.TYPICAL_CROWD: AttributeVisibility.ALWAYS,
    AttributeKey.CONDITION: AttributeVisibility.ALWAYS,
    AttributeKey.PUBLIC_FACADE: AttributeVisibility.ALWAYS,
    # Protagonist (toujours connu de lui-même)
    AttributeKey.CREDITS: AttributeVisibility.ALWAYS,
    AttributeKey.ENERGY: AttributeVisibility.ALWAYS,
    AttributeKey.MORALE: AttributeVisibility.ALWAYS,
    AttributeKey.HEALTH: AttributeVisibility.ALWAYS,
    AttributeKey.HOBBIES: AttributeVisibility.ALWAYS,
    AttributeKey.DEPARTURE_REASON: AttributeVisibility.ALWAYS,
    # === NEVER (secrets, doit être révélé explicitement) ===
    AttributeKey.HISTORY: AttributeVisibility.NEVER,
    AttributeKey.SECRET: AttributeVisibility.NEVER,
    AttributeKey.MOTIVATION: AttributeVisibility.NEVER,
    AttributeKey.ARCS: AttributeVisibility.NEVER,
    AttributeKey.HIDDEN_FUNCTION: AttributeVisibility.NEVER,
    AttributeKey.ACTUAL_VALUE: AttributeVisibility.NEVER,
    AttributeKey.TRUE_PURPOSE: AttributeVisibility.NEVER,
    # === CONDITIONAL (peut être déduit, mentionné, ou affiché) ===
    AttributeKey.REPUTATION: AttributeVisibility.CONDITIONAL,
    AttributeKey.AGE: AttributeVisibility.CONDITIONAL,
    AttributeKey.ORIGIN: AttributeVisibility.CONDITIONAL,
    AttributeKey.FINANCIAL_STATUS: AttributeVisibility.CONDITIONAL,
    AttributeKey.HEALTH_STATUS: AttributeVisibility.CONDITIONAL,
    AttributeKey.RELATIONSHIP_STATUS: AttributeVisibility.CONDITIONAL,
    AttributeKey.PRICE_RANGE: AttributeVisibility.CONDITIONAL,
    AttributeKey.OPERATING_HOURS: AttributeVisibility.CONDITIONAL,
    AttributeKey.EMOTIONAL_SIGNIFICANCE: AttributeVisibility.CONDITIONAL,
    AttributeKey.INFLUENCE_LEVEL: AttributeVisibility.CONDITIONAL,
}


# =============================================================================
# VALID KEYS BY ENTITY TYPE (validation stricte)
# =============================================================================

VALID_ATTRIBUTE_KEYS_BY_ENTITY: dict[EntityType, set[AttributeKey]] = {
    EntityType.CHARACTER: {
        # Shared
        AttributeKey.DESCRIPTION,
        AttributeKey.HISTORY,
        AttributeKey.SECRET,
        AttributeKey.REPUTATION,
        # Character-specific
        AttributeKey.MOOD,
        AttributeKey.AGE,
        AttributeKey.VOICE,
        AttributeKey.QUIRK,
        AttributeKey.ORIGIN,
        AttributeKey.MOTIVATION,
        AttributeKey.FINANCIAL_STATUS,
        AttributeKey.HEALTH_STATUS,
        AttributeKey.RELATIONSHIP_STATUS,
        AttributeKey.ARCS,
    },
    EntityType.LOCATION: {
        # Shared
        AttributeKey.DESCRIPTION,
        AttributeKey.HISTORY,
        AttributeKey.SECRET,
        # Location-specific
        AttributeKey.ATMOSPHERE,
        AttributeKey.CROWD_LEVEL,
        AttributeKey.NOISE_LEVEL,
        AttributeKey.CLEANLINESS,
        AttributeKey.PRICE_RANGE,
        AttributeKey.OPERATING_HOURS,
        AttributeKey.NOTABLE_FEATURES,
        AttributeKey.TYPICAL_CROWD,
    },
    EntityType.OBJECT: {
        # Shared
        AttributeKey.DESCRIPTION,
        AttributeKey.HISTORY,
        # Object-specific
        AttributeKey.CONDITION,
        AttributeKey.HIDDEN_FUNCTION,
        AttributeKey.EMOTIONAL_SIGNIFICANCE,
        AttributeKey.ACTUAL_VALUE,
    },
    EntityType.ORGANIZATION: {
        # Shared
        AttributeKey.DESCRIPTION,
        AttributeKey.HISTORY,
        AttributeKey.SECRET,
        AttributeKey.REPUTATION,
        # Organization-specific
        AttributeKey.PUBLIC_FACADE,
        AttributeKey.TRUE_PURPOSE,
        AttributeKey.INFLUENCE_LEVEL,
    },
    EntityType.PROTAGONIST: {
        AttributeKey.DESCRIPTION,
        AttributeKey.CREDITS,
        AttributeKey.ENERGY,
        AttributeKey.MORALE,
        AttributeKey.HEALTH,
        AttributeKey.HOBBIES,
        AttributeKey.DEPARTURE_REASON,
    },
    EntityType.AI: {
        AttributeKey.DESCRIPTION,
        AttributeKey.QUIRK,
        AttributeKey.VOICE,
    },
}


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


def get_attribute_visibility(key: AttributeKey) -> AttributeVisibility:
    """Retourne la visibilité par défaut d'un attribut."""
    return ATTRIBUTE_DEFAULT_VISIBILITY.get(key, AttributeVisibility.CONDITIONAL)


def validate_attribute_for_entity(key: AttributeKey, entity_type: EntityType) -> bool:
    """
    Valide qu'une clé est autorisée pour un type d'entité.
    Raises ValueError si invalide.
    """
    valid_keys = VALID_ATTRIBUTE_KEYS_BY_ENTITY.get(entity_type, set())

    if key not in valid_keys:
        raise ValueError(
            f"Attribute '{key.value}' is not valid for entity type '{entity_type.value}'. "
            f"Valid keys: {sorted(k.value for k in valid_keys)}"
        )

    return True


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
    """
    A key-value attribute for any entity.
    Key is normalized and validated against AttributeKey enum.
    """

    key: AttributeKey
    value: str
    details: dict | None = None

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        """Normalise la clé vers AttributeKey."""
        return normalize_key(v)


class AttributeWithVisibility(BaseModel):
    """
    Attribute avec flag de visibilité explicite.
    Utilisé après l'analyse de visibilité.
    """

    key: AttributeKey
    value: str
    details: dict | None = None
    known_by_protagonist: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        return normalize_key(v)
