"""
LDVELH - Core Schema (EAV Architecture)
Enums, primitive types, base models, attribute definitions
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
    model_validator,
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
    SHARED_ATTRIBUTE_SYNONYMS,
    CHARACTER_ATTRIBUTE_SYNONYMS,
    LOCATION_ATTRIBUTE_SYNONYMS,
    OBJECT_ATTRIBUTE_SYNONYMS,
    ORGANIZATION_ATTRIBUTE_SYNONYMS,
    PROTAGONIST_ATTRIBUTE_SYNONYMS,
    AI_ATTRIBUTE_SYNONYMS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# TRUNCATED STRING TYPES
# =============================================================================


def _truncate(max_len: int):
    """Factory to create truncation function."""

    def _inner(v: Any) -> str | None:
        if v is None:
            return None
        v = str(v)
        if len(v) <= max_len:
            return v
        truncated = v[: max_len - 3].rsplit(" ", 1)[0] + "..."
        logger.warning(f"[Truncate] {len(v)} → {len(truncated)} chars")
        return truncated

    return _inner


Label = Annotated[str, BeforeValidator(_truncate(30)), StringConstraints(max_length=30)]
"""30 chars - 2-3 words (pronouns, gender, tags)"""

Tag = Annotated[str, BeforeValidator(_truncate(50)), StringConstraints(max_length=50)]
"""50 chars - few words (type, category, sector)"""

Mood = Annotated[str, BeforeValidator(_truncate(80)), StringConstraints(max_length=80)]
"""80 chars - short phrase (ambiance, mood)"""

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
"""400 chars - paragraph (departure_story)"""

FullText = Annotated[
    str, BeforeValidator(_truncate(500)), StringConstraints(max_length=500)
]
"""500 chars - detailed paragraph"""

Backstory = Annotated[
    str, BeforeValidator(_truncate(600)), StringConstraints(max_length=600)
]
"""600 chars - complete history"""


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


"""
Mapping EntityType → table typée (seulement celles avec FK).

Tables supprimées (sans FK, données dans attributes via EAV) :
- entity_protagonists
- entity_characters  
- entity_objects
"""
ENTITY_TYPED_TABLES: dict[EntityType, str] = {
    EntityType.LOCATION: f"entity_{EntityType.LOCATION.value}s",
    EntityType.AI: f"entity_{EntityType.AI.value}s",
    EntityType.ORGANIZATION: f"entity_{EntityType.ORGANIZATION.value}s",
}


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
# ATTRIBUTE KEY ENUM (Complete EAV)
# =============================================================================


class AttributeKey(str, Enum):
    """All allowed attribute keys."""

    # === SHARED ===
    DESCRIPTION = "description"
    HISTORY = "history"
    SECRET = "secret"
    REPUTATION = "reputation"

    # === CHARACTER ===
    SPECIES = "species"
    GENDER = "gender"
    PRONOUNS = "pronouns"
    ARRIVAL_CYCLE = "arrival_cycle"
    TRAITS = "traits"
    MOOD = "mood"
    AGE = "age"
    VOICE = "voice"
    QUIRK = "quirk"
    ORIGIN = "origin"
    OCCUPATION = "occupation"
    MOTIVATION = "motivation"
    FINANCIAL_STATUS = "financial_status"
    HEALTH_STATUS = "health_status"
    RELATIONSHIP_STATUS = "relationship_status"
    ARCS = "arcs"
    ROMANTIC_POTENTIAL = "romantic_potential"
    IS_MANDATORY = "is_mandatory"

    # === LOCATION ===
    LOCATION_TYPE = "location_type"
    SECTOR = "sector"
    ACCESSIBLE = "accessible"
    ATMOSPHERE = "atmosphere"
    CROWD_LEVEL = "crowd_level"
    NOISE_LEVEL = "noise_level"
    CLEANLINESS = "cleanliness"
    PRICE_RANGE = "price_range"
    OPERATING_HOURS = "operating_hours"
    NOTABLE_FEATURES = "notable_features"
    TYPICAL_CROWD = "typical_crowd"

    # === OBJECT ===
    CATEGORY = "category"
    TRANSPORTABLE = "transportable"
    STACKABLE = "stackable"
    BASE_VALUE = "base_value"
    CONDITION = "condition"
    HIDDEN_FUNCTION = "hidden_function"
    EMOTIONAL_SIGNIFICANCE = "emotional_significance"
    ACTUAL_VALUE = "actual_value"

    # === ORGANIZATION ===
    ORG_TYPE = "org_type"
    DOMAIN = "domain"
    SIZE = "size"
    FOUNDING_CYCLE = "founding_cycle"
    PUBLIC_FACADE = "public_facade"
    TRUE_PURPOSE = "true_purpose"
    INFLUENCE_LEVEL = "influence_level"
    IS_EMPLOYER = "is_employer"

    # === PROTAGONIST ===
    CREDITS = "credits"
    ENERGY = "energy"
    MORALE = "morale"
    HEALTH = "health"
    HOBBIES = "hobbies"
    DEPARTURE_REASON = "departure_reason"
    BACKSTORY = "backstory"

    # === AI ===
    SUBSTRATE = "substrate"
    CREATION_CYCLE = "creation_cycle"


class AttributeVisibility(str, Enum):
    ALWAYS = "always"
    NEVER = "never"
    CONDITIONAL = "conditional"


# =============================================================================
# ATTRIBUTE SYNONYMS MAPPING BY ENTITY TYPE
# =============================================================================

ATTRIBUTE_SYNONYMS_BY_ENTITY: dict[EntityType, dict[str, str]] = {
    EntityType.CHARACTER: {
        **SHARED_ATTRIBUTE_SYNONYMS,
        **CHARACTER_ATTRIBUTE_SYNONYMS,
    },
    EntityType.LOCATION: {
        **SHARED_ATTRIBUTE_SYNONYMS,
        **LOCATION_ATTRIBUTE_SYNONYMS,
    },
    EntityType.OBJECT: {
        **SHARED_ATTRIBUTE_SYNONYMS,
        **OBJECT_ATTRIBUTE_SYNONYMS,
    },
    EntityType.ORGANIZATION: {
        **SHARED_ATTRIBUTE_SYNONYMS,
        **ORGANIZATION_ATTRIBUTE_SYNONYMS,
    },
    EntityType.PROTAGONIST: {
        **SHARED_ATTRIBUTE_SYNONYMS,
        **PROTAGONIST_ATTRIBUTE_SYNONYMS,
    },
    EntityType.AI: {
        **SHARED_ATTRIBUTE_SYNONYMS,
        **AI_ATTRIBUTE_SYNONYMS,
    },
}

# Fallback: all synonyms merged (for when entity type is unknown)
ALL_ATTRIBUTE_SYNONYMS: dict[str, str] = {
    **SHARED_ATTRIBUTE_SYNONYMS,
    **CHARACTER_ATTRIBUTE_SYNONYMS,
    **LOCATION_ATTRIBUTE_SYNONYMS,
    **OBJECT_ATTRIBUTE_SYNONYMS,
    **ORGANIZATION_ATTRIBUTE_SYNONYMS,
    **PROTAGONIST_ATTRIBUTE_SYNONYMS,
    **AI_ATTRIBUTE_SYNONYMS,
}


# =============================================================================
# ATTRIBUTE VISIBILITY MAPPING
# =============================================================================

ATTRIBUTE_DEFAULT_VISIBILITY: dict[AttributeKey, AttributeVisibility] = {
    # ALWAYS visible
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
    AttributeKey.SPECIES: AttributeVisibility.ALWAYS,
    AttributeKey.GENDER: AttributeVisibility.ALWAYS,
    AttributeKey.PRONOUNS: AttributeVisibility.ALWAYS,
    AttributeKey.LOCATION_TYPE: AttributeVisibility.ALWAYS,
    AttributeKey.CATEGORY: AttributeVisibility.ALWAYS,
    AttributeKey.ORG_TYPE: AttributeVisibility.ALWAYS,
    # Protagonist gauges
    AttributeKey.CREDITS: AttributeVisibility.ALWAYS,
    AttributeKey.ENERGY: AttributeVisibility.ALWAYS,
    AttributeKey.MORALE: AttributeVisibility.ALWAYS,
    AttributeKey.HEALTH: AttributeVisibility.ALWAYS,
    AttributeKey.HOBBIES: AttributeVisibility.ALWAYS,
    AttributeKey.DEPARTURE_REASON: AttributeVisibility.ALWAYS,
    AttributeKey.BACKSTORY: AttributeVisibility.ALWAYS,
    # NEVER visible (secrets)
    AttributeKey.HISTORY: AttributeVisibility.NEVER,
    AttributeKey.SECRET: AttributeVisibility.NEVER,
    AttributeKey.MOTIVATION: AttributeVisibility.NEVER,
    AttributeKey.ARCS: AttributeVisibility.NEVER,
    AttributeKey.HIDDEN_FUNCTION: AttributeVisibility.NEVER,
    AttributeKey.ACTUAL_VALUE: AttributeVisibility.NEVER,
    AttributeKey.TRUE_PURPOSE: AttributeVisibility.NEVER,
    AttributeKey.ROMANTIC_POTENTIAL: AttributeVisibility.NEVER,
    AttributeKey.IS_MANDATORY: AttributeVisibility.NEVER,
    AttributeKey.IS_EMPLOYER: AttributeVisibility.NEVER,
    # CONDITIONAL
    AttributeKey.REPUTATION: AttributeVisibility.CONDITIONAL,
    AttributeKey.AGE: AttributeVisibility.CONDITIONAL,
    AttributeKey.ORIGIN: AttributeVisibility.CONDITIONAL,
    AttributeKey.OCCUPATION: AttributeVisibility.CONDITIONAL,
    AttributeKey.TRAITS: AttributeVisibility.CONDITIONAL,
    AttributeKey.ARRIVAL_CYCLE: AttributeVisibility.CONDITIONAL,
    AttributeKey.FINANCIAL_STATUS: AttributeVisibility.CONDITIONAL,
    AttributeKey.HEALTH_STATUS: AttributeVisibility.CONDITIONAL,
    AttributeKey.RELATIONSHIP_STATUS: AttributeVisibility.CONDITIONAL,
    AttributeKey.PRICE_RANGE: AttributeVisibility.CONDITIONAL,
    AttributeKey.OPERATING_HOURS: AttributeVisibility.CONDITIONAL,
    AttributeKey.EMOTIONAL_SIGNIFICANCE: AttributeVisibility.CONDITIONAL,
    AttributeKey.INFLUENCE_LEVEL: AttributeVisibility.CONDITIONAL,
    AttributeKey.SECTOR: AttributeVisibility.CONDITIONAL,
    AttributeKey.ACCESSIBLE: AttributeVisibility.CONDITIONAL,
    AttributeKey.TRANSPORTABLE: AttributeVisibility.CONDITIONAL,
    AttributeKey.STACKABLE: AttributeVisibility.CONDITIONAL,
    AttributeKey.BASE_VALUE: AttributeVisibility.CONDITIONAL,
    AttributeKey.DOMAIN: AttributeVisibility.CONDITIONAL,
    AttributeKey.SIZE: AttributeVisibility.CONDITIONAL,
    AttributeKey.FOUNDING_CYCLE: AttributeVisibility.CONDITIONAL,
    AttributeKey.SUBSTRATE: AttributeVisibility.CONDITIONAL,
    AttributeKey.CREATION_CYCLE: AttributeVisibility.CONDITIONAL,
}


# =============================================================================
# VALID KEYS BY ENTITY TYPE
# =============================================================================

VALID_ATTRIBUTE_KEYS_BY_ENTITY: dict[EntityType, set[AttributeKey]] = {
    EntityType.CHARACTER: {
        AttributeKey.DESCRIPTION,
        AttributeKey.HISTORY,
        AttributeKey.SECRET,
        AttributeKey.REPUTATION,
        AttributeKey.SPECIES,
        AttributeKey.GENDER,
        AttributeKey.PRONOUNS,
        AttributeKey.ARRIVAL_CYCLE,
        AttributeKey.TRAITS,
        AttributeKey.MOOD,
        AttributeKey.AGE,
        AttributeKey.VOICE,
        AttributeKey.QUIRK,
        AttributeKey.ORIGIN,
        AttributeKey.OCCUPATION,
        AttributeKey.MOTIVATION,
        AttributeKey.FINANCIAL_STATUS,
        AttributeKey.HEALTH_STATUS,
        AttributeKey.RELATIONSHIP_STATUS,
        AttributeKey.ARCS,
        AttributeKey.ROMANTIC_POTENTIAL,
        AttributeKey.IS_MANDATORY,
    },
    EntityType.LOCATION: {
        AttributeKey.DESCRIPTION,
        AttributeKey.HISTORY,
        AttributeKey.SECRET,
        AttributeKey.LOCATION_TYPE,
        AttributeKey.SECTOR,
        AttributeKey.ACCESSIBLE,
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
        AttributeKey.DESCRIPTION,
        AttributeKey.HISTORY,
        AttributeKey.CATEGORY,
        AttributeKey.TRANSPORTABLE,
        AttributeKey.STACKABLE,
        AttributeKey.BASE_VALUE,
        AttributeKey.CONDITION,
        AttributeKey.HIDDEN_FUNCTION,
        AttributeKey.EMOTIONAL_SIGNIFICANCE,
        AttributeKey.ACTUAL_VALUE,
    },
    EntityType.ORGANIZATION: {
        AttributeKey.DESCRIPTION,
        AttributeKey.HISTORY,
        AttributeKey.SECRET,
        AttributeKey.REPUTATION,
        AttributeKey.ORG_TYPE,
        AttributeKey.DOMAIN,
        AttributeKey.SIZE,
        AttributeKey.FOUNDING_CYCLE,
        AttributeKey.PUBLIC_FACADE,
        AttributeKey.TRUE_PURPOSE,
        AttributeKey.INFLUENCE_LEVEL,
        AttributeKey.IS_EMPLOYER,
    },
    EntityType.PROTAGONIST: {
        AttributeKey.DESCRIPTION,
        AttributeKey.CREDITS,
        AttributeKey.ENERGY,
        AttributeKey.MORALE,
        AttributeKey.HEALTH,
        AttributeKey.HOBBIES,
        AttributeKey.DEPARTURE_REASON,
        AttributeKey.BACKSTORY,
        AttributeKey.ORIGIN,
    },
    EntityType.AI: {
        AttributeKey.DESCRIPTION,
        AttributeKey.QUIRK,
        AttributeKey.VOICE,
        AttributeKey.TRAITS,
        AttributeKey.SUBSTRATE,
        AttributeKey.CREATION_CYCLE,
    },
}


# =============================================================================
# NORMALIZATION FUNCTIONS
# =============================================================================


def normalize_attribute_key(
    key: str, entity_type: EntityType | None = None
) -> AttributeKey:
    """
    Normalize an attribute key string to AttributeKey enum.
    Uses entity-specific synonyms if entity_type is provided.
    """
    if isinstance(key, AttributeKey):
        return key

    normalized = key.lower().strip().replace(" ", "_").replace("-", "_")

    # Choose synonym dict based on entity type
    if entity_type is not None:
        synonyms = ATTRIBUTE_SYNONYMS_BY_ENTITY.get(entity_type, ALL_ATTRIBUTE_SYNONYMS)
    else:
        synonyms = ALL_ATTRIBUTE_SYNONYMS

    # Try synonym lookup
    canonical = synonyms.get(normalized)
    if canonical:
        try:
            return AttributeKey(canonical)
        except ValueError:
            pass

    # Try direct enum match
    try:
        return AttributeKey(normalized)
    except ValueError:
        pass

    # Fallback: log warning and raise
    logger.warning(
        f"[Normalizer] Unknown attribute key: '{key}' (entity_type={entity_type})"
    )
    raise ValueError(f"Unknown attribute key: '{key}'")


def normalize_attribute_key_for_character(key: str) -> AttributeKey:
    """Normalize attribute key for CHARACTER entity."""
    return normalize_attribute_key(key, EntityType.CHARACTER)


def normalize_attribute_key_for_location(key: str) -> AttributeKey:
    """Normalize attribute key for LOCATION entity."""
    return normalize_attribute_key(key, EntityType.LOCATION)


def normalize_attribute_key_for_object(key: str) -> AttributeKey:
    """Normalize attribute key for OBJECT entity."""
    return normalize_attribute_key(key, EntityType.OBJECT)


def normalize_attribute_key_for_organization(key: str) -> AttributeKey:
    """Normalize attribute key for ORGANIZATION entity."""
    return normalize_attribute_key(key, EntityType.ORGANIZATION)


def normalize_attribute_key_for_protagonist(key: str) -> AttributeKey:
    """Normalize attribute key for PROTAGONIST entity."""
    return normalize_attribute_key(key, EntityType.PROTAGONIST)


def normalize_attribute_key_for_ai(key: str) -> AttributeKey:
    """Normalize attribute key for AI entity."""
    return normalize_attribute_key(key, EntityType.AI)


# Mapping for easy access
ATTRIBUTE_NORMALIZERS: dict[EntityType, callable] = {
    EntityType.CHARACTER: normalize_attribute_key_for_character,
    EntityType.LOCATION: normalize_attribute_key_for_location,
    EntityType.OBJECT: normalize_attribute_key_for_object,
    EntityType.ORGANIZATION: normalize_attribute_key_for_organization,
    EntityType.PROTAGONIST: normalize_attribute_key_for_protagonist,
    EntityType.AI: normalize_attribute_key_for_ai,
}


def _normalize_enum_value(
    value: Any,
    synonyms: dict[str, str],
    enum_class: type[Enum],
    field_name: str,
) -> str:
    """Normalize a value to a valid enum value."""
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
            f"[Normalizer] Unknown {field_name}='{value}' → fallback '{fallback}'"
        )
        return fallback

    if key != result:
        logger.info(f"[Normalizer] {field_name}: '{value}' → '{result}'")

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


def normalize_commitment_type(value: Any) -> str:
    return _normalize_enum_value(
        value, COMMITMENT_TYPE_SYNONYMS, CommitmentType, "commitment_type"
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


def get_attribute_visibility(key: AttributeKey) -> AttributeVisibility:
    """Return the default visibility of an attribute."""
    return ATTRIBUTE_DEFAULT_VISIBILITY.get(key, AttributeVisibility.CONDITIONAL)


def validate_attribute_for_entity(key: AttributeKey, entity_type: EntityType) -> bool:
    """Validate that a key is allowed for an entity type."""
    valid_keys = VALID_ATTRIBUTE_KEYS_BY_ENTITY.get(entity_type, set())
    if key not in valid_keys:
        raise ValueError(
            f"Attribute '{key.value}' is not valid for entity type '{entity_type.value}'. "
            f"Valid keys: {sorted(k.value for k in valid_keys)}"
        )
    return True


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
# BASE MODELS
# =============================================================================


class Skill(BaseModel):
    """A skill with level 1-5"""

    name: Tag  # 50 chars
    level: int = Field(..., ge=1, le=5)


class Attribute(BaseModel):
    """A key-value attribute for any entity."""

    key: AttributeKey
    value: str
    details: dict | None = None

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        return normalize_attribute_key(v)


class AttributeWithVisibility(BaseModel):
    """Attribute with explicit visibility flag."""

    key: AttributeKey
    value: str
    details: dict | None = None
    known_by_protagonist: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        # Without entity context, use generic normalizer
        return normalize_attribute_key(v)


# =============================================================================
# TYPED ATTRIBUTE MODELS (with entity-specific validation)
# =============================================================================


class CharacterAttribute(BaseModel):
    """Attribute for CHARACTER entity with specific normalization."""

    key: AttributeKey
    value: str
    details: dict | None = None
    known_by_protagonist: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        return normalize_attribute_key_for_character(v)


class LocationAttribute(BaseModel):
    """Attribute for LOCATION entity with specific normalization."""

    key: AttributeKey
    value: str
    details: dict | None = None
    known_by_protagonist: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        return normalize_attribute_key_for_location(v)


class ObjectAttribute(BaseModel):
    """Attribute for OBJECT entity with specific normalization."""

    key: AttributeKey
    value: str
    details: dict | None = None
    known_by_protagonist: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        return normalize_attribute_key_for_object(v)


class OrganizationAttribute(BaseModel):
    """Attribute for ORGANIZATION entity with specific normalization."""

    key: AttributeKey
    value: str
    details: dict | None = None
    known_by_protagonist: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        return normalize_attribute_key_for_organization(v)


class ProtagonistAttribute(BaseModel):
    """Attribute for PROTAGONIST entity with specific normalization."""

    key: AttributeKey
    value: str
    details: dict | None = None
    known_by_protagonist: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        return normalize_attribute_key_for_protagonist(v)


class AIAttribute(BaseModel):
    """Attribute for AI entity with specific normalization."""

    key: AttributeKey
    value: str
    details: dict | None = None
    known_by_protagonist: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, v: Any) -> AttributeKey:
        return normalize_attribute_key_for_ai(v)


# Mapping for typed attribute classes
TYPED_ATTRIBUTE_CLASSES: dict[EntityType, type[BaseModel]] = {
    EntityType.CHARACTER: CharacterAttribute,
    EntityType.LOCATION: LocationAttribute,
    EntityType.OBJECT: ObjectAttribute,
    EntityType.ORGANIZATION: OrganizationAttribute,
    EntityType.PROTAGONIST: ProtagonistAttribute,
    EntityType.AI: AIAttribute,
}

# =============================================================================
# TEMPORAL VALIDATION
# =============================================================================


class TemporalValidationMixin:
    """Mixin for models needing temporal coherence validation"""

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

    #
    # @staticmethod
    # def is_temporally_valid(
    #     arrival_cycle: int | None, founding_cycle: int | None, context: str = ""
    # ) -> bool:
    #     if arrival_cycle is not None and founding_cycle is not None:
    #         if arrival_cycle < founding_cycle:
    #             logger.warning(
    #                 f"[Temporal] {context}: arrival_cycle ({arrival_cycle}) "
    #                 f"before founding_cycle ({founding_cycle}) - filtering"
    #             )
    #             return False
    #     return True
