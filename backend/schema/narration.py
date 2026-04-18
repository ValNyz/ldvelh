"""
LDVELH - Narration Schema
Input/Output models for the narrator LLM
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .core import (
    ArcDomain,
    EntityRef,
    Name,
    Phrase,
    Tag,
    Text,
)


# =============================================================================
# CONTEXT BUILDING BLOCKS (Narrator input)
# =============================================================================


class ProtagonistState(BaseModel):
    """Current protagonist state"""

    name: str
    credits: int
    hobbies: list[str]
    current_occupation: Optional[str] = None
    employer: Optional[str] = None
    gender: Optional[str] = None
    description: Optional[str] = None
    backstory: Optional[str] = None
    origin: Optional[str] = None


class InventoryItem(BaseModel):
    """An item in the inventory"""

    name: str
    category: str
    quantity: int = 1
    emotional: bool = False  # Has emotional significance


class LocationSummary(BaseModel):
    """Location summary"""

    name: str
    type: str
    sector: str
    atmosphere: str
    accessible: bool = True
    ambient: str | None = None


class ArcSummary(BaseModel):
    """Lightweight arc summary (used in NPC context)"""

    domain: ArcDomain
    title: str
    situation_brief: str
    intensity: int  # 1-5


class NPCLightSummary(BaseModel):
    """Lightweight NPC summary for context"""

    name: str
    occupation: str | None
    species: str = "human"
    relationship_level: int | None
    usual_location: str | None
    known: bool
    ambient: str | None = None


class NPCSummary(NPCLightSummary):
    """Detailed NPC summary for context"""

    traits: list[str]  # 2-3 main traits
    relationship_to_protagonist: Optional[str] = None  # "colleague", "neighbor", etc.
    relationship_level: Optional[int] = None  # 0-10 if known
    active_arcs: list[ArcSummary] = Field(default_factory=list)
    last_seen: Optional[str] = None  # "cycle 3, at the cafe"
    notes: Optional[str] = None  # Important known info
    ambient: str | None = None


class OrganizationSummary(BaseModel):
    """Organization summary for context"""

    name: str
    org_type: str | None
    domain: str | None
    protagonist_relation: str | None  # e.g. "employed_by"
    ambient: str | None = None


class ArcStep(BaseModel):
    """A milestone step within an arc"""

    title: str
    status: str = "pending"  # pending, active, completed, failed, skipped
    description: str = ""
    risks: list[str] = Field(default_factory=list)


class ActiveArcSummary(BaseModel):
    """Summary of an active narrative arc"""

    type: str  # ArcDomain value
    title: str
    description_brief: str
    involved: list[str]  # Entity names involved
    owner: str | None = None  # Entity name of the arc owner
    owner_type: str | None = None  # "protagonist", "character", "location"
    objective: str | None = None  # Goal formulated as intention
    steps: list[ArcStep] = Field(default_factory=list)
    deadline_cycle: Optional[int] = None
    urgency: str = "normal"  # low, normal, high, critical


class EventSummary(BaseModel):
    """Upcoming event summary"""

    title: str
    planned_cycle: int
    planned_time: Optional[str] = None
    location: Optional[str] = None
    participants: list[str] = Field(default_factory=list)
    type: str  # appointment, deadline, etc.


class Fact(BaseModel):
    """Fact summary for narrator context"""

    cycle: int
    description: str
    importance: int  # 1-5
    involves: list[str] = Field(default_factory=list)


class CycleSummary(BaseModel):
    """Cycle summary (from chronology table)"""

    summary: Text
    cycle: int
    date: Tag | None
    events: list[Phrase] = Field(default_factory=list)


class CompanionSummary(BaseModel):
    """Summary of the protagonist's companion (AI, animal, spirit, object, etc.)"""

    name: str
    voice_description: Optional[str] = None
    personality_traits: list[str] = Field(default_factory=list)
    quirk: Optional[str] = None


# =============================================================================
# NARRATION CONTEXT (Complete input)
# =============================================================================


class NarrationContext(BaseModel):
    """Complete context provided to the narrator"""

    # === TIME ===
    current_cycle: int
    current_date: str  # "Mercredi 15 Mars 2847"
    current_time: str  # "14h30"

    # === SPACE ===
    current_location: LocationSummary
    connected_locations: list[LocationSummary] = Field(
        default_factory=list,
        description="Locations directly accessible from current location",
    )

    # === PROTAGONIST ===
    protagonist: ProtagonistState
    inventory: list[InventoryItem] = Field(default_factory=list)

    # === COMPANION ===
    companion: Optional[CompanionSummary] = Field(
        default=None,
        description="The protagonist's companion (name, traits, quirk)",
    )

    # === ORGANIZATIONS ===
    organizations: list[OrganizationSummary]

    # === NPCs ===
    all_npcs: list[NPCLightSummary]
    npcs_present: list[NPCSummary] = Field(
        default_factory=list, description="NPCs currently present at the location"
    )
    npcs_relevant: list[NPCSummary] = Field(
        default_factory=list,
        description="Known relevant NPCs (mentioned, expected, nearby)",
    )

    # === NARRATIVE ===
    active_arcs: list[ActiveArcSummary] = Field(
        default_factory=list, description="Active narrative arcs"
    )
    upcoming_events: list[EventSummary] = Field(
        default_factory=list, description="Upcoming events in the next cycles"
    )

    # === FACTS ===
    facts: list[Fact] = Field(
        default_factory=list, description="Recent important facts (importance >= 4)"
    )

    # === NARRATIVE SEEDS ===
    active_seeds: list[dict] = Field(
        default_factory=list, description="Active narrative seeds (unresolved hooks)"
    )

    # === HISTORY ===
    cycle_summaries: list[CycleSummary] = Field(
        default_factory=list,
        description="Summaries of cycles before conversation window",
    )

    # === REQUESTED ENTITY DETAILS (prefetched from info_requests) ===
    requested_entity_details: dict[str, dict] = Field(
        default_factory=dict,
        description="Detailed info on entities requested by narrator at previous turn",
    )

    # === PLAYER INPUT ===
    player_input: str = Field(..., description="What the player said/chose")

    # === ENGINE ===
    engine_type: str = "none"
    engine_stats: Optional[dict] = Field(
        default=None, description="Engine-specific stats (Fate stress, D6 wounds, etc.)"
    )

    # === GENRE ===
    genre: Optional[dict] = Field(
        default=None, description="Genre config from DB (tone, friction, atmosphere)"
    )

    # === META ===
    world_name: str
    world_description: str = ""
    world_atmosphere: str
    tone_notes: str = ""

    # === DIRECTOR ===
    director_guidance: str | None = Field(
        default=None,
        description="Latest Director plan guidance for the narrator",
    )
    director_tension: int | None = Field(
        default=None,
        description="Director's tension level (1-5)",
    )
    director_planned_events: list[dict] = Field(
        default_factory=list,
        description="Events planned by the Director for upcoming cycles",
    )


# =============================================================================
# NARRATION OUTPUT
# =============================================================================


class TimeProgression(BaseModel):
    """Time progression"""

    new_time: str = Field(..., description="New time: 'HHhMM'")
    ellipse: bool = Field(
        default=False,
        description="True if significant time skip (narrative ellipsis)",
    )
    ellipse_summary: Phrase | None = None  # 150 chars


class DayTransition(BaseModel):
    """Transition to a new day"""

    new_cycle: int
    new_date: str  # "Jeudi 16 Mars 2847"
    night_summary: Phrase | None = None  # 150 chars


class CreditDelta(BaseModel):
    """Live credit change output by the narrator"""

    amount: int  # Positive = gain, negative = expense
    description: str = Field(..., max_length=100)  # "café au Terminal 7"


class InventoryHint(BaseModel):
    """Lightweight inventory change — formalized at batch extraction time"""

    action: Literal["acquire", "lose", "use"]
    item_name: str = Field(..., max_length=100)
    item_description: str = Field(..., max_length=200)  # For frontend display
    quantity: int = 1


class EntityReveal(BaseModel):
    """An entity whose identity/existence was revealed to the protagonist"""

    entity_type: Literal["character", "location"] = "character"
    current_name: Name  # Name used until now (unknown_name or description)
    real_name: Name | None = None  # Actual name if revealed (characters only)


class EventHint(BaseModel):
    """Lightweight event hint — formalized at batch extraction time"""

    title: str = Field(..., max_length=100)
    planned_time: str | None = None  # "HHhMM"
    planned_cycle: int | None = None
    location: str | None = None  # Location name


class NarrationOutput(BaseModel):
    """Complete narrator LLM output"""

    @model_validator(mode="before")
    @classmethod
    def truncate_long_strings(cls, data: dict) -> dict:
        """Truncate LLM strings that exceed field limits instead of crashing.

        The max_length constraints are guidelines for the LLM. If it exceeds
        them slightly, we truncate rather than reject the entire response.
        """
        if not isinstance(data, dict):
            return data

        # Truncate nested fields in lists of dicts
        _LIMITS = {
            "credit_delta": {"description": 100},
            "inventory_hints": {"item_name": 100, "item_description": 200},
            "events_mentioned": {"title": 100},
        }
        for field, limits in _LIMITS.items():
            value = data.get(field)
            if value is None:
                continue
            # Single dict (credit_delta)
            if isinstance(value, dict):
                for key, max_len in limits.items():
                    if key in value and isinstance(value[key], str) and len(value[key]) > max_len:
                        value[key] = value[key][:max_len - 3] + "..."
            # List of dicts (inventory_hints, events_mentioned)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for key, max_len in limits.items():
                            if key in item and isinstance(item[key], str) and len(item[key]) > max_len:
                                item[key] = item[key][:max_len - 3] + "..."

        # Truncate top-level string fields
        for field, max_len in [("scene_mood", 50), ("narrator_notes", 300)]:
            if field in data and isinstance(data[field], str) and len(data[field]) > max_len:
                data[field] = data[field][:max_len - 3] + "..."

        return data

    # === NARRATION ===
    narrative_length: str = Field(
        default="medium",
        description="Self-declared length: short (2-4 phrases), medium (5-8), long (8-12). Generated BEFORE narrative_text to guide length.",
    )
    narrative_text: str = Field(
        ...,
        min_length=1,
        description="Narrative text in Markdown.",
    )

    # === TIME ===
    time: TimeProgression
    day_transition: Optional[DayTransition] = Field(
        default=None, description="Filled only when transitioning to a new day"
    )

    # === SPACE ===
    current_location: EntityRef = Field(
        ..., description="EXACT name of the current location (must exist)"
    )

    # === NPCs ===
    npcs_present: list[EntityRef] = Field(
        default_factory=list, description="EXACT names of NPCs present in the scene"
    )

    # === LIVE STATE DELTAS ===
    credit_delta: Optional[CreditDelta] = Field(
        default=None, description="Credit change to apply immediately"
    )
    inventory_hints: list[InventoryHint] = Field(
        default_factory=list, description="Inventory changes (formalized at batch time)"
    )
    entity_reveals: list[EntityReveal] = Field(
        default_factory=list, description="Entities revealed to the protagonist"
    )

    # === STRUCTURED HINTS FOR PROCESS_LIGHT ===
    events_mentioned: list[EventHint] = Field(
        default_factory=list,
        description="Events scheduled or that occurred this turn",
    )

    # === INFO REQUESTS (prefetch for next turn) ===
    info_requests: list[EntityRef] = Field(
        default_factory=list,
        description="Entity names to load in detail for next turn context",
    )

    # === EXTRACTION TRIGGERS ===
    extraction_triggers: list[str] = Field(
        default_factory=list,
        description="Extractors to run: characters, locations, organizations, inventory, narrative_arcs",
    )

    # === FATE CORE: COMPEL ===
    compel_aspect: str | None = Field(
        default=None, description="Aspect being compelled (exact name, or null)"
    )
    compel_result: Literal["proposed", "accepted", "refused"] | None = Field(
        default=None, description="Compel state: proposed (new), accepted/refused (response to previous)"
    )

    # === META ===
    scene_mood: Tag | None = None  # 50 chars - mood in 2-3 words
    narrator_notes: Text | None = None  # 300 chars - internal notes
