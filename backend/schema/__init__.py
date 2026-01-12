"""
LDVELH - Schema Package (EAV Architecture)
Central exports for all schema models
"""

# =============================================================================
# CORE - Enums, types, base models, attribute definitions
# =============================================================================
from .core import (
    # Enums
    ArcDomain,
    AttributeKey,
    AttributeVisibility,
    CommitmentType,
    DepartureReason,
    EntityType,
    ENTITY_TYPED_TABLES,
    EventType,
    FactType,
    Moment,
    OrgSize,
    ParticipantRole,
    RelationCategory,
    RelationType,
    # Text types (truncated strings)
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
    # Typed attribute classes (entity-specific normalization)
    CharacterAttribute,
    LocationAttribute,
    ObjectAttribute,
    OrganizationAttribute,
    ProtagonistAttribute,
    AIAttribute,
    TYPED_ATTRIBUTE_CLASSES,
    # Mappings
    ATTRIBUTE_NORMALIZERS,
    ATTRIBUTE_DEFAULT_VISIBILITY,
    ATTRIBUTE_SYNONYMS_BY_ENTITY,
    ALL_ATTRIBUTE_SYNONYMS,
    VALID_ATTRIBUTE_KEYS_BY_ENTITY,
    # Normalizers - generic
    normalize_attribute_key,
    get_attribute_visibility,
    validate_attribute_for_entity,
    # Normalizers - typed (entity-specific)
    normalize_attribute_key_for_character,
    normalize_attribute_key_for_location,
    normalize_attribute_key_for_object,
    normalize_attribute_key_for_organization,
    normalize_attribute_key_for_protagonist,
    normalize_attribute_key_for_ai,
    # Normalizers - other enums
    normalize_arc_domain,
    normalize_commitment_type,
    normalize_departure_reason,
    normalize_entity_type,
    normalize_fact_type,
    normalize_moment,
    normalize_org_size,
    normalize_participant_role,
    normalize_relation_type,
)

# =============================================================================
# SYNONYMS - LLM output normalization dictionaries
# =============================================================================
from .synonyms import (
    # Enum synonyms
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
    # Attribute synonyms by entity type
    SHARED_ATTRIBUTE_SYNONYMS,
    CHARACTER_ATTRIBUTE_SYNONYMS,
    LOCATION_ATTRIBUTE_SYNONYMS,
    OBJECT_ATTRIBUTE_SYNONYMS,
    ORGANIZATION_ATTRIBUTE_SYNONYMS,
    PROTAGONIST_ATTRIBUTE_SYNONYMS,
    AI_ATTRIBUTE_SYNONYMS,
    # JSON key synonyms
    KEY_SYNONYMS,
    # Utility functions
    normalize_key,
    normalize_dict_keys,
)

# =============================================================================
# ENTITIES - Entity data models (EAV-based)
# =============================================================================
from .entities import (
    CharacterData,
    EntityData,
    LocationData,
    ObjectData,
    OrganizationData,
    PersonalAIData,
    ProtagonistData,
    WorldData,
    # Utility functions
    attrs_from_dict,
    attrs_to_dict,
)

# =============================================================================
# RELATIONS - Relation models with typed sub-tables
# =============================================================================
from .relations import (
    RelationData,
    RelationOwnershipData,
    RelationProfessionalData,
    RelationSocialData,
    RelationSpatialData,
)

# =============================================================================
# NARRATIVE - Story elements (facts, arcs, commitments)
# =============================================================================
from .narrative import (
    CharacterArc,
    CommitmentCreation,
    FactData,
    FactParticipant,
    NarrativeArcData,
)

# =============================================================================
# NARRATION - Narrator I/O models and context summaries
# =============================================================================
from .narration import (
    NarrationContext,
    NarrationHints,
    NarrationOutput,
    # Context summary models (used in NarrationContext)
    ArcSummary,
    CommitmentSummary,
    EventSummary,
    GaugeState,
    InventoryItem,
    LocationSummary,
    MessageSummary,
    NPCLightSummary,
    NPCSummary,
    OrganizationSummary,
    PersonalAISummary,
    ProtagonistState,
    Fact,
)

# =============================================================================
# EXTRACTION - LLM extraction output models (unified EAV format)
# =============================================================================
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
)

# =============================================================================
# WORLD GENERATION - Initial world creation models
# =============================================================================
from .world_generation import (
    ArrivalEventData,
    WorldGeneration,
    # Note: WorldData is imported from .entities
)


# =============================================================================
# __all__ - Public API
# =============================================================================
__all__ = [
    # =========================================================================
    # CORE - Enums
    # =========================================================================
    "ArcDomain",
    "AttributeKey",
    "AttributeVisibility",
    "CommitmentType",
    "DepartureReason",
    "EntityType",
    "ENTITY_TYPED_TABLES",
    "EventType",
    "FactType",
    "Moment",
    "OrgSize",
    "ParticipantRole",
    "RelationCategory",
    "RelationType",
    # =========================================================================
    # CORE - Text types
    # =========================================================================
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
    # =========================================================================
    # CORE - Type aliases
    # =========================================================================
    "Cycle",
    "EntityRef",
    # =========================================================================
    # CORE - Base models
    # =========================================================================
    "Attribute",
    "AttributeWithVisibility",
    "Skill",
    "TemporalValidationMixin",
    # =========================================================================
    # CORE - Typed attribute classes
    # =========================================================================
    "CharacterAttribute",
    "LocationAttribute",
    "ObjectAttribute",
    "OrganizationAttribute",
    "ProtagonistAttribute",
    "AIAttribute",
    "TYPED_ATTRIBUTE_CLASSES",
    # =========================================================================
    # CORE - Mappings
    # =========================================================================
    "ATTRIBUTE_NORMALIZERS",
    "ATTRIBUTE_DEFAULT_VISIBILITY",
    "ATTRIBUTE_SYNONYMS_BY_ENTITY",
    "ALL_ATTRIBUTE_SYNONYMS",
    "VALID_ATTRIBUTE_KEYS_BY_ENTITY",
    # =========================================================================
    # CORE - Normalizers
    # =========================================================================
    "normalize_attribute_key",
    "get_attribute_visibility",
    "validate_attribute_for_entity",
    "normalize_attribute_key_for_character",
    "normalize_attribute_key_for_location",
    "normalize_attribute_key_for_object",
    "normalize_attribute_key_for_organization",
    "normalize_attribute_key_for_protagonist",
    "normalize_attribute_key_for_ai",
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
    # =========================================================================
    # SYNONYMS
    # =========================================================================
    "ARC_DOMAIN_SYNONYMS",
    "CERTAINTY_SYNONYMS",
    "COMMITMENT_TYPE_SYNONYMS",
    "DEPARTURE_REASON_SYNONYMS",
    "ENTITY_TYPE_SYNONYMS",
    "FACT_TYPE_SYNONYMS",
    "KEY_SYNONYMS",
    "MOMENT_SYNONYMS",
    "ORG_SIZE_SYNONYMS",
    "PARTICIPANT_ROLE_SYNONYMS",
    "RELATION_TYPE_SYNONYMS",
    "SHARED_ATTRIBUTE_SYNONYMS",
    "CHARACTER_ATTRIBUTE_SYNONYMS",
    "LOCATION_ATTRIBUTE_SYNONYMS",
    "OBJECT_ATTRIBUTE_SYNONYMS",
    "ORGANIZATION_ATTRIBUTE_SYNONYMS",
    "PROTAGONIST_ATTRIBUTE_SYNONYMS",
    "AI_ATTRIBUTE_SYNONYMS",
    "normalize_dict_keys",
    # =========================================================================
    # ENTITIES
    # =========================================================================
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
    # =========================================================================
    # RELATIONS
    # =========================================================================
    "RelationData",
    "RelationOwnershipData",
    "RelationProfessionalData",
    "RelationSocialData",
    "RelationSpatialData",
    # =========================================================================
    # NARRATIVE
    # =========================================================================
    "CharacterArc",
    "CommitmentCreation",
    "FactData",
    "FactParticipant",
    "NarrativeArcData",
    # =========================================================================
    # NARRATION
    # =========================================================================
    "NarrationContext",
    "NarrationHints",
    "NarrationOutput",
    # =========================================================================
    # EXTRACTION - Entity changes
    # =========================================================================
    "EntityCreation",
    "EntityRemoval",
    "EntityUpdate",
    "ObjectCreation",
    # =========================================================================
    # EXTRACTION - Relation changes
    # =========================================================================
    "RelationCreation",
    "RelationEnd",
    "RelationUpdate",
    # =========================================================================
    # EXTRACTION - Protagonist changes
    # =========================================================================
    "CreditTransaction",
    "GaugeChange",
    "InventoryChange",
    # =========================================================================
    # EXTRACTION - Narrative elements
    # =========================================================================
    "CommitmentCreationExtraction",
    "CommitmentResolutionExtraction",
    "EventScheduledExtraction",
    # =========================================================================
    # EXTRACTION - Complete models
    # =========================================================================
    "NarrativeExtraction",
    "NarrativeWithExtraction",
    # =========================================================================
    # EXTRACTION - Context summary models
    # =========================================================================
    "ArcSummary",
    "CommitmentSummary",
    "EventSummary",
    "GaugeState",
    "InventoryItem",
    "LocationSummary",
    "MessageSummary",
    "NPCLightSummary",
    "NPCSummary",
    "OrganizationSummary",
    "PersonalAISummary",
    "ProtagonistState",
    "Fact",
    # =========================================================================
    # WORLD GENERATION
    # =========================================================================
    "ArrivalEventData",
    "WorldGeneration",
]
