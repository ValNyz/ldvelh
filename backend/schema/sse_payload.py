"""
LDVELH - SSE Payload Schema
Typed models for SSE done event payloads.
Ensures consistent contract between backend and frontend.
"""

from pydantic import BaseModel, Field


# =============================================================================
# GAME STATE (canonical shape — same for init and light)
# =============================================================================


class SSEGameState(BaseModel):
    """Canonical game state sent in every done payload."""

    game: dict | None = None
    player: dict | None = None
    ai: dict | None = None
    world_created: bool = False


# =============================================================================
# WORLD INFO (init-only presentation data)
# =============================================================================


class WorldSummary(BaseModel):
    name: str
    atmosphere: str = ""
    sectors: list[str] = Field(default_factory=list)


class ProtagonistSummary(BaseModel):
    name: str
    origin: str = ""
    departure_reason: str = ""
    credits: int = 0


class AISummary(BaseModel):
    name: str
    personality: list[str] = Field(default_factory=list)
    quirk: str = ""


class ArrivalSummary(BaseModel):
    location: str
    date: str | None = None
    time: str | None = None
    mood: str | None = None
    immediate_need: str | None = None


class WorldInfo(BaseModel):
    """Init-only: presentation data for WorldGenerationScreen."""

    world: WorldSummary
    protagonist: ProtagonistSummary
    ai: AISummary
    npc_count: int = 0
    location_count: int = 0
    org_count: int = 0
    inventory_count: int = 0
    arrival: ArrivalSummary | None = None
    arrival_event: dict | None = None  # Raw arrival_event from LLM


# =============================================================================
# META + UI HINTS
# =============================================================================


class SSEMeta(BaseModel):
    """Debug and billing metadata."""

    narration_cost: dict | None = None


class SSEUIHints(BaseModel):
    """UI-level hints (inventory changes for display)."""

    inventory_hints: list[dict] = Field(default_factory=list)


# =============================================================================
# NARRATOR DELTAS (typed model for messages.narrator_deltas JSONB)
# =============================================================================


class NarratorDeltasStored(BaseModel):
    """
    Typed model for the messages.narrator_deltas JSONB column.
    No DB schema change — this is validation and documentation.

    Three logical sections:
    1. Game mechanics — immediate state changes applied by the narrator
       (gauge_deltas, credit_delta, inventory_hints, entity_reveals)
    2. Extraction hints — metadata for batch extraction pipeline
       (hints)
    3. Billing — cost tracking per message
       (cost, extraction_cost)
    """

    # -- Game mechanics (applied immediately) --
    gauge_deltas: list[dict] = Field(default_factory=list)
    credit_delta: dict | None = None
    inventory_hints: list[dict] = Field(default_factory=list)
    entity_reveals: list[dict] = Field(default_factory=list)
    # -- Extraction hints --
    hints: dict | None = None
    # -- Billing --
    cost: dict | None = None
    extraction_cost: dict | None = None


# =============================================================================
# TOP-LEVEL SSE DONE PAYLOAD
# =============================================================================


class SSEDonePayload(BaseModel):
    """
    Top-level payload for SSE 'done' events.
    Used by both init and light mode.
    """

    game_state: SSEGameState
    world_info: WorldInfo | None = None  # Init-only
    meta: SSEMeta | None = None
    ui: SSEUIHints | None = None
