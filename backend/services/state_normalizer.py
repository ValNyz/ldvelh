"""
LDVELH - State Normalizer
Normalizes game state for the frontend API.
"""

from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from config import DEFAULT_STATS


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class InventoryItem(BaseModel):
    """Normalized inventory item"""

    id: Optional[UUID] = None
    name: str
    quantity: int = 1
    location: str = "sur_soi"
    category: str = "misc"
    condition: str = "bon"
    base_value: Optional[int] = None
    lent_to: Optional[str] = None


class PlayerState(BaseModel):
    """Normalized protagonist stats"""

    credits: int = Field(default=DEFAULT_STATS["credits"])
    inventory: list[InventoryItem] = Field(default_factory=list)
    engine_stats: Optional[dict] = None


class GameSessionState(BaseModel):
    """Normalized game session state"""

    id: Optional[UUID] = None
    name: str = "Nouvelle partie"
    current_cycle: int = 1
    day: str = "Lundi"
    game_date: Optional[str] = None
    time: Optional[str] = None
    current_location: Optional[str] = None
    npcs_present: list[str] = Field(default_factory=list)
    status: str = "active"
    engine: Optional[str] = None
    engine_locked: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AIState(BaseModel):
    """Normalized personal AI state"""

    name: Optional[str] = None
    personality: list[str] = Field(default_factory=list)
    voice: Optional[str] = None
    quirk: Optional[str] = None
    relationship: Optional[int] = None


class GameState(BaseModel):
    """Full normalized game state"""

    game: Optional[GameSessionState] = None
    player: PlayerState = Field(default_factory=PlayerState)
    ai: Optional[AIState] = None


# =============================================================================
# NORMALIZERS
# =============================================================================


def normalize_inventory_item(item: Any) -> InventoryItem:
    """
    Normalize an inventory item.
    Supports legacy format (string) and current format (dict/row).
    """
    if isinstance(item, str):
        return InventoryItem(name=item)

    data = dict(item) if hasattr(item, "keys") else item

    return InventoryItem(
        id=data.get("id"),
        name=data.get("name", "?"),
        quantity=data.get("quantity", 1),
        location=data.get("location", "sur_soi"),
        category=data.get("category", "misc"),
        condition=data.get("condition", "bon"),
        base_value=data.get("base_value"),
        lent_to=data.get("lent_to"),
    )


def normalize_player(data: Optional[dict]) -> PlayerState:
    """Normalize protagonist data."""
    if not data:
        return PlayerState()

    raw_inventory = data.get("inventory") or []
    inventory = [normalize_inventory_item(item) for item in raw_inventory]

    return PlayerState(
        credits=int(data.get("credits", DEFAULT_STATS["credits"])),
        inventory=inventory,
        engine_stats=data.get("engine_stats"),
    )


def normalize_game_session(data: Optional[dict]) -> Optional[GameSessionState]:
    """Normalize game session data."""
    if not data:
        return None

    return GameSessionState(
        id=data.get("id"),
        name=data.get("name", "Nouvelle partie"),
        current_cycle=data.get("current_cycle", 1),
        game_date=data.get("game_date"),
        time=data.get("time"),
        current_location=data.get("current_location"),
        npcs_present=data.get("npcs_present") or [],
        status=data.get("status", "active"),
        engine=data.get("engine"),
        engine_locked=data.get("engine_locked"),
        created_at=str(data["created_at"]) if data.get("created_at") else None,
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
    )


def normalize_ai(data: Optional[dict]) -> Optional[AIState]:
    """Normalize personal AI data."""
    if not data:
        return None

    raw_personality = data.get("personality") or []

    if isinstance(raw_personality, str):
        personality = [raw_personality] if raw_personality else []
    elif isinstance(raw_personality, list):
        personality = raw_personality
    else:
        personality = []

    return AIState(
        name=data.get("name"),
        personality=personality,
        voice=data.get("voice"),
        quirk=data.get("quirk"),
        relationship=data.get("relationship"),
    )


def normalize_game_state(
    game_data: Optional[dict] = None,
    player_data: Optional[dict] = None,
    ai_data: Optional[dict] = None,
    flat_data: Optional[dict] = None,
) -> GameState:
    """
    Normalize the full game state.

    Can receive either structured data (game_data, player_data, ai_data),
    or a flat dict (flat_data) to parse.
    """
    if flat_data:
        if "game" in flat_data or "player" in flat_data:
            game_data = flat_data.get("game")
            player_data = flat_data.get("player")
            ai_data = flat_data.get("ai")
        else:
            game_data = extract_game_fields(flat_data)
            player_data = extract_player_fields(flat_data)

    return GameState(
        game=normalize_game_session(game_data),
        player=normalize_player(player_data),
        ai=normalize_ai(ai_data),
    )


def extract_game_fields(data: dict) -> dict:
    """Extract game session fields from a flat dict."""
    keys = [
        "id",
        "name",
        "time",
        "current_location",
        "npcs_present",
        "current_cycle",
        "day",
        "game_date",
        "status",
        "engine",
        "engine_locked",
        "created_at",
        "updated_at",
    ]
    return {k: data[k] for k in keys if k in data}


def extract_player_fields(data: dict) -> dict:
    """Extract player fields from a flat dict."""
    keys = [
        "credits",
        "inventory",
        "engine_stats",
    ]
    return {k: data[k] for k in keys if k in data}


# =============================================================================
# MERGE HELPERS
# =============================================================================


def merge_game_states(prev: GameState, update: dict) -> GameState:
    """
    Merge an existing state with a partial update.
    Useful for SSE updates that contain only some fields.
    """
    update_state = normalize_game_state(flat_data=update)

    update_game_keys = set()
    update_player_keys = set()
    update_ai_keys = set()

    if "game" in update and update["game"]:
        update_game_keys = set(update["game"].keys())
    if "player" in update and update["player"]:
        update_player_keys = set(update["player"].keys())
    if "ai" in update and update["ai"]:
        update_ai_keys = set(update["ai"].keys())

    # Merge game session
    new_game = None
    if prev.game or update_state.game:
        prev_dict = prev.game.model_dump() if prev.game else {}
        if update_state.game and update_game_keys:
            update_dict = update_state.game.model_dump()
            update_dict = {
                k: v
                for k, v in update_dict.items()
                if k in update_game_keys and v is not None
            }
            merged = {**prev_dict, **update_dict}
        else:
            merged = prev_dict
        new_game = GameSessionState(**merged)

    # Merge player
    new_player = merge_player(
        prev.player, update_state.player, update_player_keys
    )

    # Merge AI
    new_ai = None
    if prev.ai or update_state.ai:
        prev_dict = prev.ai.model_dump() if prev.ai else {}
        if update_state.ai and update_ai_keys:
            update_dict = update_state.ai.model_dump()
            update_dict = {
                k: v
                for k, v in update_dict.items()
                if k in update_ai_keys and v is not None
            }
            merged = {**prev_dict, **update_dict}
            new_ai = AIState(**merged)
        else:
            new_ai = prev.ai

    return GameState(game=new_game, player=new_player, ai=new_ai)


def merge_player(
    prev: PlayerState, update: PlayerState, update_keys: set[str] | None = None
) -> PlayerState:
    """
    Merge player stats.
    Only updates keys explicitly present in update_keys.
    """
    if update_keys is None:
        return PlayerState(
            credits=update.credits
            if update.credits != DEFAULT_STATS["credits"]
            else prev.credits,
            inventory=update.inventory if update.inventory else prev.inventory,
            engine_stats=update.engine_stats if update.engine_stats else prev.engine_stats,
        )

    return PlayerState(
        credits=update.credits if "credits" in update_keys else prev.credits,
        inventory=update.inventory
        if "inventory" in update_keys
        else prev.inventory,
        engine_stats=update.engine_stats
        if "engine_stats" in update_keys
        else prev.engine_stats,
    )


# =============================================================================
# SERIALIZATION HELPERS
# =============================================================================


def game_state_to_dict(state: GameState) -> dict:
    """Convert a GameState to a dict for JSON serialization."""
    return state.model_dump(exclude_none=True, mode="json")


def game_state_to_json(state: GameState) -> str:
    """Convert a GameState to a JSON string."""
    return state.model_dump_json(exclude_none=True)
