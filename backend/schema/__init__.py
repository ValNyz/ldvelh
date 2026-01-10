"""
LDVELH - Schema Package
Réexporte tous les modèles pour un import facile
"""

# Core - Enums, types, base models
from .core import (
    # Truncated string types
    Label,
    Tag,
    Mood,
    Name,
    Phrase,
    ShortText,
    Text,
    LongText,
    FullText,
    Backstory,
    # Enums
    EntityType,
    RelationCategory,
    RelationType,
    CertaintyLevel,
    FactType,
    ParticipantRole,
    CommitmentType,
    ArcDomain,
    DepartureReason,
    Moment,
    OrgSize,
    # Type aliases
    Cycle,
    EntityRef,
    # Mixins
    TemporalValidationMixin,
    # Base models
    Skill,
    Attribute,
    # Normalizers
    normalize_entity_type,
    normalize_relation_type,
    normalize_certainty,
    normalize_fact_type,
    normalize_participant_role,
    normalize_commitment_type,
    normalize_arc_domain,
    normalize_departure_reason,
    normalize_moment,
    normalize_org_size,
)

# Relations
from .relations import (
    RelationSocialData,
    RelationProfessionalData,
    RelationSpatialData,
    RelationOwnershipData,
    RelationData,
    # Factory
    create_relation,
)

# Narrative
from .narrative import (
    CharacterArc,
    FactParticipant,
    FactData,
    BeliefData,
    CommitmentCreation,
    CommitmentResolution,
    EventScheduled,
    NarrativeArcData,
)

# Entities
from .entities import (
    WorldData,
    ProtagonistData,
    PersonalAIData,
    CharacterData,
    LocationData,
    ObjectData,
    OrganizationData,
    create_minimal_character,
)

# Extraction
from .extraction import (
    EntityCreation,
    EntityUpdate,
    EntityRemoval,
    ObjectCreation,
    RelationCreation,
    RelationUpdate,
    RelationEnd,
    GaugeChange,
    CreditTransaction,
    InventoryChange,
    CommitmentCreationExtraction,
    CommitmentResolutionExtraction,
    EventScheduledExtraction,
    NarrativeExtraction,
    NarrativeWithExtraction,
)

# World Generation
from .world_generation import (
    ArrivalEventData,
    WorldGeneration,
)

# Narration (I/O pour le narrateur)
from .narration import (
    GaugeState,
    ProtagonistState,
    InventoryItem,
    LocationSummary,
    ArcSummary,
    NPCSummary,
    CommitmentSummary,
    EventSummary,
    RecentFact,
    MessageSummary,
    PersonalAISummary,
    NarrationContext,
    NarrationHints,
    TimeProgression,
    DayTransition,
    NarrationOutput,
)

__all__ = [
    # Truncated string types
    "Label",
    "Tag",
    "Mood",
    "Name",
    "Phrase",
    "ShortText",
    "Text",
    "LongText",
    "FullText",
    "Backstory",
    # Core enums
    "EntityType",
    "RelationCategory",
    "RelationType",
    "CertaintyLevel",
    "FactType",
    "ParticipantRole",
    "CommitmentType",
    "ArcDomain",
    "DepartureReason",
    "Moment",
    "OrgSize",
    # Type aliases
    "Cycle",
    "EntityRef",
    # Mixins
    "TemporalValidationMixin",
    # Base models
    "Skill",
    "Attribute",
    # Normalizers
    "normalize_entity_type",
    "normalize_relation_type",
    "normalize_certainty",
    "normalize_fact_type",
    "normalize_participant_role",
    "normalize_commitment_type",
    "normalize_arc_domain",
    "normalize_departure_reason",
    "normalize_moment",
    "normalize_org_size",
    # Relations
    "RelationSocialData",
    "RelationProfessionalData",
    "RelationSpatialData",
    "RelationOwnershipData",
    "RelationData",
    "create_relation",
    # Narrative
    "CharacterArc",
    "FactParticipant",
    "FactData",
    "BeliefData",
    "CommitmentCreation",
    "CommitmentResolution",
    "EventScheduled",
    "NarrativeArcData",
    # Entities
    "WorldData",
    "ProtagonistData",
    "PersonalAIData",
    "FORBIDDEN_AI_NAMES",
    "CharacterData",
    "LocationData",
    "ObjectData",
    "OrganizationData",
    "create_minimal_character",
    # Extraction
    "EntityCreation",
    "EntityUpdate",
    "EntityRemoval",
    "ObjectCreation",
    "RelationCreation",
    "RelationUpdate",
    "RelationEnd",
    "GaugeChange",
    "CreditTransaction",
    "InventoryChange",
    "CommitmentCreationExtraction",
    "CommitmentResolutionExtraction",
    "EventScheduledExtraction",
    "NarrativeExtraction",
    "NarrativeWithExtraction",
    # World Generation
    "ArrivalEventData",
    "WorldGeneration",
    # Narration
    "GaugeState",
    "ProtagonistState",
    "InventoryItem",
    "LocationSummary",
    "ArcSummary",
    "NPCSummary",
    "CommitmentSummary",
    "EventSummary",
    "RecentFact",
    "MessageSummary",
    "PersonalAISummary",
    "NarrationContext",
    "NarrationHints",
    "TimeProgression",
    "DayTransition",
    "NarrationOutput",
]
