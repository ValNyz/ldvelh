"""
LDVELH - Schema Package
Réexporte tous les modèles pour un import facile
"""

# Core - Enums, types, base models
from .core import (
    EntityType,
    RelationType,
    CertaintyLevel,
    FactType,
    FactDomain,
    ParticipantRole,
    CommitmentType,
    ArcDomain,
    DepartureReason,
    Moment,
    Cycle,
    EntityRef,
    TemporalValidationMixin,
    Skill,
    Attribute,
)

# Relations
from .relations import (
    RelationSocialData,
    RelationProfessionalData,
    RelationSpatialData,
    RelationOwnershipData,
    RelationData,
    # Groupings
    SOCIAL_RELATIONS,
    PROFESSIONAL_RELATIONS,
    SPATIAL_RELATIONS,
    OWNERSHIP_RELATIONS,
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
    FORBIDDEN_AI_NAMES,
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
    # Core
    "EntityType",
    "RelationType",
    "CertaintyLevel",
    "FactType",
    "FactDomain",
    "ParticipantRole",
    "CommitmentType",
    "ArcDomain",
    "DepartureReason",
    "Moment",
    "Cycle",
    "EntityRef",
    "TemporalValidationMixin",
    "Skill",
    "Attribute",
    # Relations
    "RelationSocialData",
    "RelationProfessionalData",
    "RelationSpatialData",
    "RelationOwnershipData",
    "RelationData",
    "create_relation",
    "SOCIAL_RELATIONS",
    "PROFESSIONAL_RELATIONS",
    "SPATIAL_RELATIONS",
    "OWNERSHIP_RELATIONS",
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
