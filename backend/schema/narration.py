"""
LDVELH - Narration Schema
Input/Output models for the narrator LLM
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

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


class GaugeState(BaseModel):
    """State of a protagonist gauge"""

    value: float = Field(..., ge=0, le=5)
    trend: Optional[str] = None  # "up", "down", "stable"


class ProtagonistState(BaseModel):
    """Current protagonist state"""

    name: str
    credits: int
    energy: GaugeState
    morale: GaugeState
    health: GaugeState
    hobbies: list[str]
    current_occupation: Optional[str] = None
    employer: Optional[str] = None


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


class ActiveArcSummary(BaseModel):
    """Summary of an active narrative arc"""

    type: str  # ArcDomain value
    title: str
    description_brief: str
    involved: list[str]  # Entity names involved
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


class PersonalAssistantSummary(BaseModel):
    """Summary of Valentin's personal AI assistant"""

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

    # === PERSONAL ASSISTANT ===
    personal_ai: Optional[PersonalAssistantSummary] = Field(
        default=None,
        description="Valentin's personal AI assistant (name, traits, quirk)",
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

    # === META ===
    world_name: str
    world_atmosphere: str
    tone_notes: str = ""


# =============================================================================
# NARRATION HINTS (Signals for the extractor)
# =============================================================================


class NarrationHints(BaseModel):
    """Hints from the narrator to guide extraction"""

    # New entities mentioned/introduced
    new_entities_mentioned: list[str] = Field(
        default_factory=list,
        description="Names of new NPCs, locations, objects mentioned for the first time",
    )

    # Detected changes
    relationships_changed: bool = Field(
        default=False,
        description="A relationship has evolved (friendship, tension, romance, professional...)",
    )
    protagonist_state_changed: bool = Field(
        default=False, description="Gauges, credits, inventory, skills have changed"
    )
    information_learned: bool = Field(
        default=False, description="The protagonist learned something new"
    )

    # Narrative
    arc_advanced: list[str] = Field(
        default_factory=list,
        description="Titles of arcs that have progressed",
    )
    arc_resolved: list[str] = Field(
        default_factory=list, description="Titles of arcs that were resolved"
    )
    new_arc_created: bool = Field(
        default=False,
        description="A new secret, foreshadowing, setup, or arc was introduced",
    )

    # Events
    event_scheduled: bool = Field(
        default=False, description="An appointment or future event was scheduled"
    )
    event_occurred: bool = Field(
        default=False, description="A scheduled event occurred"
    )

    @property
    def needs_extraction(self) -> bool:
        """Determine if extraction is needed"""
        return any(
            [
                self.new_entities_mentioned,
                self.relationships_changed,
                self.protagonist_state_changed,
                self.information_learned,
                self.arc_advanced,
                self.arc_resolved,
                self.new_arc_created,
                self.event_scheduled,
                self.event_occurred,
            ]
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


class GaugeDelta(BaseModel):
    """Live gauge change output by the narrator"""

    gauge: Literal["energy", "morale", "health"]
    delta: float = Field(default=0, ge=-3.0, le=3.0)  # ±0.5 common, ±1.5 exceptional


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

    # === NARRATION ===
    narrative_text: str = Field(
        ...,
        min_length=100,
        description="Narrative text in Markdown. Becky Chambers tone.",
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

    # === CHOICES ===
    suggested_actions: list[Phrase] = Field(
        default_factory=list,
        description="Suggested possible actions (2-5 ideally)",
    )

    # === LIVE STATE DELTAS ===
    gauge_deltas: list[GaugeDelta] = Field(
        default_factory=list, description="Gauge changes to apply immediately"
    )
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

    # === HINTS FOR EXTRACTION ===
    hints: NarrationHints = Field(default_factory=NarrationHints)

    # === META ===
    scene_mood: Tag | None = None  # 50 chars - mood in 2-3 words
    narrator_notes: Text | None = None  # 300 chars - internal notes
