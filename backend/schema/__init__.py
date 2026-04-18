"""
LDVELH - Schema Package
Central exports for all schema models.
Dedicated tables + entity_registry architecture.
"""

# =============================================================================
# CORE - Enums, types, base models
# =============================================================================
from .core import (
    # Enums
    ArcDomain,
    DepartureReason,
    EntityType,
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
    Skill,
    TemporalValidationMixin,
    # Normalizers
    normalize_arc_domain,
    normalize_departure_reason,
    normalize_entity_type,
    normalize_fact_type,
    normalize_moment,
    normalize_org_size,
    normalize_participant_role,
    normalize_relation_type,
)

# =============================================================================
# ENTITIES - Entity data models (dedicated tables)
# =============================================================================
from .entities import (
    CharacterData,
    CompanionData,
    LocationData,
    ObjectData,
    OrganizationData,
    ProtagonistData,
    WorldData,
)

# =============================================================================
# RELATIONS - Simplified relation model
# =============================================================================
from .relations import (
    RelationData,
)

# =============================================================================
# NARRATIVE - Facts, arcs, events
# =============================================================================
from .narrative import (
    ArcResolution,
    EventScheduled,
    FactData,
    FactParticipant,
    NarrativeArcData,
)

# =============================================================================
# NARRATION - Narrator I/O models and context summaries
# =============================================================================
from .narration import (
    NarrationContext,
    NarrationOutput,
    # Live delta models
    CreditDelta,
    EntityReveal,
    InventoryHint,
    # Context summary models
    ArcSummary,
    ActiveArcSummary,
    CompanionSummary,
    CycleSummary,
    DayTransition,
    EventSummary,
    Fact,
    InventoryItem,
    LocationSummary,
    NPCLightSummary,
    NPCSummary,
    OrganizationSummary,
    ProtagonistState,
    TimeProgression,
)

# =============================================================================
# EXTRACTION - LLM extraction output models (direct fields, no EAV)
# =============================================================================
from .extraction import (
    # Extraction type enum
    ExtractionType,
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
    InventoryChange,
    # Narrative elements
    ArcCreation,
    ArcResolutionExtraction,
    EventScheduledExtraction,
    # Complete extraction (legacy — used by populator)
    NarrativeExtraction,
    NarrativeWithExtraction,
    # Specialized extraction outputs
    CharactersExtraction,
    LocationsExtraction,
    OrganizationsExtraction,
    InventoryExtraction,
    NarrativeArcsExtraction,
    # Progression extraction outputs (engine-specific)
    D6ProgressionExtraction,
    D6SkillUpgrade,
    FateAspectRename,
    FateMilestoneExtraction,
    NarrativeTraitEvolution,
)

# =============================================================================
# ENGINE - Game engine types, character data, roll models
# =============================================================================
from .engine import (
    EngineType,
    WorldConfig,
    # Fate Core
    FateAspect,
    FateCharacterData,
    FateConsequences,
    FateSkill,
    FateStunt,
    # D6 System
    D6CharacterData,
    D6Skill,
    D6WoundLevel,
    # Narrative
    NarrativeCharacterData,
    NarrativeTrait,
    # NPC engine data
    NPCD6Data,
    NPCFateData,
    NPCNarrativeData,
    # Mechanical pipeline
    MechanicalDecision,
    MechanicalResult,
    RollResult,
)

# =============================================================================
# DIRECTOR - Narrative planning models
# =============================================================================
from .director import (
    ArcUpdate,
    DirectorOutput,
    DirectorPlan,
    PlannedEvent,
)

# =============================================================================
# WORLD GENERATION - Initial world creation models
# =============================================================================
from .world_generation import (
    ArrivalEventData,
    WorldGeneration,
)

# =============================================================================
# SSE PAYLOAD - Typed API contract for SSE done events
# =============================================================================
from .sse_payload import (
    AISummary,
    ArrivalSummary,
    NarratorDeltasStored,
    ProtagonistSummary,
    SSEDonePayload,
    SSEGameState,
    SSEMeta,
    SSEUIHints,
    WorldInfo,
    WorldSummary,
)


# =============================================================================
# __all__ - Public API
# =============================================================================
__all__ = [
    # =========================================================================
    # CORE - Enums
    # =========================================================================
    "ArcDomain",
    "DepartureReason",
    "EntityType",
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
    # CORE - Type aliases & base models
    # =========================================================================
    "Cycle",
    "EntityRef",
    "Skill",
    "TemporalValidationMixin",
    # =========================================================================
    # CORE - Normalizers
    # =========================================================================
    "normalize_arc_domain",
    "normalize_departure_reason",
    "normalize_entity_type",
    "normalize_fact_type",
    "normalize_moment",
    "normalize_org_size",
    "normalize_participant_role",
    "normalize_relation_type",
    # =========================================================================
    # ENTITIES
    # =========================================================================
    "CharacterData",
    "CompanionData",
    "LocationData",
    "ObjectData",
    "OrganizationData",
    "ProtagonistData",
    "WorldData",
    # =========================================================================
    # RELATIONS
    # =========================================================================
    "RelationData",
    # =========================================================================
    # NARRATIVE
    # =========================================================================
    "ArcResolution",
    "EventScheduled",
    "FactData",
    "FactParticipant",
    "NarrativeArcData",
    # =========================================================================
    # NARRATION
    # =========================================================================
    "NarrationContext",
    "NarrationOutput",
    "CreditDelta",
    "EntityReveal",
    "InventoryHint",
    "ArcSummary",
    "ActiveArcSummary",
    "CompanionSummary",
    "CycleSummary",
    "DayTransition",
    "EventSummary",
    "Fact",
    "InventoryItem",
    "LocationSummary",
    "NPCLightSummary",
    "NPCSummary",
    "OrganizationSummary",
    "ProtagonistState",
    "TimeProgression",
    # =========================================================================
    # EXTRACTION
    # =========================================================================
    "ExtractionType",
    "EntityCreation",
    "EntityRemoval",
    "EntityUpdate",
    "ObjectCreation",
    "RelationCreation",
    "RelationEnd",
    "RelationUpdate",
    "CreditTransaction",
    "InventoryChange",
    "ArcCreation",
    "ArcResolutionExtraction",
    "EventScheduledExtraction",
    "NarrativeExtraction",
    "NarrativeWithExtraction",
    "CharactersExtraction",
    "LocationsExtraction",
    "OrganizationsExtraction",
    "InventoryExtraction",
    "NarrativeArcsExtraction",
    "D6ProgressionExtraction",
    "D6SkillUpgrade",
    "FateAspectRename",
    "FateMilestoneExtraction",
    "NarrativeTraitEvolution",
    # =========================================================================
    # ENGINE
    # =========================================================================
    "EngineType",
    "WorldConfig",
    "FateAspect",
    "FateCharacterData",
    "FateConsequences",
    "FateSkill",
    "FateStunt",
    "D6CharacterData",
    "D6Skill",
    "D6WoundLevel",
    "NarrativeCharacterData",
    "NarrativeTrait",
    "NPCD6Data",
    "NPCFateData",
    "NPCNarrativeData",
    "MechanicalDecision",
    "MechanicalResult",
    "RollResult",
    # =========================================================================
    # DIRECTOR
    # =========================================================================
    "DirectorOutput",
    "DirectorPlan",
    "PlannedEvent",
    # =========================================================================
    # WORLD GENERATION
    # =========================================================================
    "ArrivalEventData",
    "WorldGeneration",
    # =========================================================================
    # SSE PAYLOAD
    # =========================================================================
    "AISummary",
    "ArrivalSummary",
    "NarratorDeltasStored",
    "ProtagonistSummary",
    "SSEDonePayload",
    "SSEGameState",
    "SSEMeta",
    "SSEUIHints",
    "WorldInfo",
    "WorldSummary",
]
