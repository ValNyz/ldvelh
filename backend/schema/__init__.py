"""
LDVELH - Schema Package (EAV Architecture)
Central exports for all schema models
"""

# Core enums and types
from .core import (
    # Enums
    ArcDomain,
    AttributeKey,
    AttributeVisibility,
    CommitmentType,
    DepartureReason,
    EntityType,
    FactType,
    Moment,
    OrgSize,
    ParticipantRole,
    RelationCategory,
    RelationType,
    # Text types
    Backstory,
    FullText,
    Label,
    LongText,
    Mood,
    Name,
    Phrase,
    ShortText,
    Tag,
    Text,
    # Type aliases
    Cycle,
    EntityRef,
    # Base models
    Attribute,
    AttributeWithVisibility,
    Skill,
    TemporalValidationMixin,
    # Mappings
    ATTRIBUTE_NORMALIZERS,
    ATTRIBUTE_DEFAULT_VISIBILITY,
    VALID_ATTRIBUTE_KEYS_BY_ENTITY,
    # Normalizers
    normalize_attribute_key,
    get_attribute_visibility,
    normalize_arc_domain,
    normalize_commitment_type,
    normalize_departure_reason,
    normalize_entity_type,
    normalize_fact_type,
    normalize_moment,
    normalize_org_size,
    normalize_participant_role,
    normalize_relation_type,
    validate_attribute_for_entity,
)

# Synonyms
from .synonyms import (
    ARC_DOMAIN_SYNONYMS,
    # ATTRIBUTE_KEY_SYNONYMS,
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

# Entity models (simplified EAV)
from .entities import (
    CharacterData,
    EntityData,
    LocationData,
    ObjectData,
    OrganizationData,
    PersonalAIData,
    ProtagonistData,
    WorldData,
    attrs_from_dict,
    attrs_to_dict,
)

# Relation models
from .relations import (
    RelationOwnershipData,
    RelationProfessionalData,
    RelationData,
    RelationSocialData,
    RelationSpatialData,
)

# Narrative models
from .narrative import (
    CharacterArc,
    CommitmentCreation,
    FactData,
    FactParticipant,
    NarrativeArcData,
    # Context sub-models
)

from .narration import NarrationContext, NarrationHints, NarrationOutput

# Extraction models (unified EAV format)
from .extraction import (
    # Entity changes
    EntityCreation,
    EntityRemoval,
    EntityUpdate,
    ObjectCreation,
    # Relation changes
    RelationCreation,
    RelationEnd,
    RelationUpdate,
    # Protagonist changes
    CreditTransaction,
    GaugeChange,
    InventoryChange,
    # Narrative elements
    CommitmentCreationExtraction,
    CommitmentResolutionExtraction,
    EventScheduledExtraction,
    # Complete extraction
    NarrativeExtraction,
    NarrativeWithExtraction,
    CommitmentSummary,
    EventSummary,
    GaugeState,
    InventoryItem,
    LocationSummary,
    MessageSummary,
    NPCSummary,
    ArcSummary,
    PersonalAISummary,
    ProtagonistState,
    RecentFact,
)

from .world_generation import ArrivalEventData, WorldGeneration, WorldData


__all__ = [
    # === CORE ===
    # Enums
    "ArcDomain",
    "AttributeKey",
    "AttributeVisibility",
    "CommitmentType",
    "DepartureReason",
    "EntityType",
    "FactType",
    "Moment",
    "OrgSize",
    "ParticipantRole",
    "RelationCategory",
    "RelationType",
    "ATTRIBUTE_NORMALIZERS"
    # Text types
    "Backstory",
    "FullText",
    "Label",
    "LongText",
    "Mood",
    "Name",
    "Phrase",
    "ShortText",
    "Tag",
    "Text",
    # Type aliases
    "Cycle",
    "EntityRef",
    # Base models
    "Attribute",
    "AttributeWithVisibility",
    "Skill",
    "TemporalValidationMixin",
    # Mappings
    "ATTRIBUTE_DEFAULT_VISIBILITY",
    "VALID_ATTRIBUTE_KEYS_BY_ENTITY",
    # Normalizers
    "normalize_attribute_key",
    "get_attribute_visibility",
    "normalize_arc_domain",
    "normalize_commitment_type",
    "normalize_departure_reason",
    "normalize_entity_type",
    "normalize_fact_type",
    "normalize_key",
    "normalize_moment",
    "normalize_org_size",
    "normalize_participant_role",
    "normalize_relation_type",
    "validate_attribute_for_entity",
    # === SYNONYMS ===
    "ARC_DOMAIN_SYNONYMS",
    "ATTRIBUTE_KEY_SYNONYMS",
    "COMMITMENT_TYPE_SYNONYMS",
    "DEPARTURE_REASON_SYNONYMS",
    "ENTITY_TYPE_SYNONYMS",
    "FACT_TYPE_SYNONYMS",
    "MOMENT_SYNONYMS",
    "ORG_SIZE_SYNONYMS",
    "PARTICIPANT_ROLE_SYNONYMS",
    "RELATION_TYPE_SYNONYMS",
    # === ENTITIES ===
    "CharacterData",
    "EntityData",
    "LocationData",
    "ObjectData",
    "OrganizationData",
    "PersonalAIData",
    "ProtagonistData",
    "WorldData",
    "attrs_from_dict",
    "attrs_to_dict",
    # === RELATIONS ===
    "RelationData",
    "RelationType",
    "RelationCategory",
    "RelationSpatialData",
    "RelationSocialData",
    "RelationProfessionalData",
    "RelationOwnershipData",
    # === NARRATIVE ===
    "ArrivalEventData",
    "CharacterArc",
    "CommitmentCreation",
    "FactData",
    "FactParticipant",
    "NarrationContext",
    "NarrationHints",
    "NarrativeArcData",
    "WorldGeneration",
    # Context sub-models
    "ArcSummary",
    "CommitmentSummary",
    "EventSummary",
    "GaugeState",
    "InventoryItem",
    "LocationSummary",
    "MessageSummary",
    "NPCSummary",
    "PersonalAISummary",
    "ProtagonistState",
    "RecentFact",
    # === EXTRACTION ===
    "CommitmentCreationExtraction",
    "CommitmentResolutionExtraction",
    "CreditTransaction",
    "EntityCreation",
    "EntityRemoval",
    "EntityUpdate",
    "EventScheduledExtraction",
    "GaugeChange",
    "InventoryChange",
    "NarrativeExtraction",
    "NarrativeWithExtraction",
    "ObjectCreation",
    "RelationCreation",
    "RelationEnd",
    "RelationUpdate",
]
