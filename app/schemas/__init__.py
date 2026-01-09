"""
LDVELH - Schema Package
Réexporte tous les modèles pour un import facile
"""

# Core - Enums, types, base models
from .core import (
    ArcDomain,
    Attribute,
    CertaintyLevel,
    CommitmentType,
    Cycle,
    DepartureReason,
    EntityRef,
    EntityType,
    FactDomain,
    FactType,
    Moment,
    ParticipantRole,
    RelationType,
    Skill,
    TemporalValidationMixin,
)

# Entities
from .entities import (
    FORBIDDEN_AI_NAMES,
    CharacterData,
    LocationData,
    ObjectData,
    OrganizationData,
    PersonalAIData,
    ProtagonistData,
    WorldData,
    create_minimal_character,
)

# Extraction
from .extraction import (
    CreditTransaction,
    EntityCreation,
    EntityRemoval,
    EntityUpdate,
    GaugeChange,
    InventoryChange,
    NarrativeExtraction,
    NarrativeWithExtraction,
    RelationCreation,
    RelationEnd,
    RelationUpdate,
)

# Narrative
from .narrative import (
    BeliefData,
    CharacterArc,
    CommitmentCreation,
    CommitmentResolution,
    EventScheduled,
    FactData,
    FactParticipant,
    NarrativeArcData,
)

# Relations
from .relations import (
    OWNERSHIP_RELATIONS,
    PROFESSIONAL_RELATIONS,
    # Groupings
    SOCIAL_RELATIONS,
    SPATIAL_RELATIONS,
    RelationData,
    RelationOwnershipData,
    RelationProfessionalData,
    RelationSocialData,
    RelationSpatialData,
    # Factory
    create_relation,
)

# World Generation
from .world_generation import (
    ArrivalEventData,
    WorldGeneration,
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
]
