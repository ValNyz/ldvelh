"""
Unit tests for state_normalizer.py
High priority: core serialization layer for frontend API.
"""

from decimal import Decimal
from uuid import UUID

from config import DEFAULT_STATS
from services.state_normalizer import (
    normalize_inventory_item,
    normalize_player,
    normalize_game_session,
    normalize_ai,
    normalize_game_state,
    merge_game_states,
    game_state_to_dict,
    InventoryItem,
    PlayerState,
    GameSessionState,
    AIState,
    GameState,
)


# =============================================================================
# TESTS INVENTORY
# =============================================================================


class TestNormalizeInventoryItem:
    """Tests for normalize_inventory_item"""

    def test_string_input(self):
        """Legacy format: just a name string"""
        item = normalize_inventory_item("Lampe torche")
        assert item.name == "Lampe torche"
        assert item.quantity == 1
        assert item.location == "sur_soi"
        assert item.category == "misc"

    def test_dict_input(self):
        """Dict format with English keys"""
        data = {
            "name": "Access Card",
            "quantity": 3,
            "location": "pocket",
            "category": "tool",
            "condition": "good",
        }
        item = normalize_inventory_item(data)
        assert item.name == "Access Card"
        assert item.quantity == 3
        assert item.location == "pocket"
        assert item.category == "tool"
        assert item.condition == "good"

    def test_missing_fields_use_defaults(self):
        """Missing fields use defaults"""
        item = normalize_inventory_item({"name": "Thing"})
        assert item.quantity == 1
        assert item.location == "sur_soi"
        assert item.category == "misc"
        assert item.condition == "bon"

    def test_with_uuid(self):
        """Item with UUID"""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        item = normalize_inventory_item({"id": uid, "name": "Item"})
        assert item.id == uid


# =============================================================================
# TESTS PLAYER
# =============================================================================


class TestNormalizePlayer:
    """Tests for normalize_player"""

    def test_none_input(self):
        """None -> defaults"""
        state = normalize_player(None)
        assert state.energy == DEFAULT_STATS["energy"]
        assert state.morale == DEFAULT_STATS["morale"]
        assert state.health == DEFAULT_STATS["health"]
        assert state.credits == DEFAULT_STATS["credits"]
        assert state.inventory == []

    def test_empty_dict(self):
        """Empty dict -> defaults"""
        state = normalize_player({})
        assert state.energy == DEFAULT_STATS["energy"]

    def test_english_keys(self):
        """English keys"""
        state = normalize_player(
            {
                "energy": 3.5,
                "morale": 2.0,
                "health": 4.5,
                "credits": 500,
            }
        )
        assert state.energy == 3.5
        assert state.morale == 2.0
        assert state.health == 4.5
        assert state.credits == 500

    def test_decimal_conversion(self):
        """Decimal -> float"""
        state = normalize_player(
            {
                "energy": Decimal("3.75"),
                "morale": Decimal("2.50"),
            }
        )
        assert state.energy == 3.75
        assert isinstance(state.energy, float)
        assert state.morale == 2.50

    def test_with_inventory_strings(self):
        """Inventory with legacy format (strings)"""
        state = normalize_player({"inventory": ["Lampe", "Clé", "Carte"]})
        assert len(state.inventory) == 3
        assert state.inventory[0].name == "Lampe"
        assert state.inventory[1].name == "Clé"

    def test_with_inventory_dicts(self):
        """Inventory with dict format"""
        state = normalize_player(
            {
                "inventory": [
                    {"name": "Lampe", "quantity": 1},
                    {"name": "Clé", "quantity": 2},
                ]
            }
        )
        assert len(state.inventory) == 2
        assert state.inventory[1].quantity == 2


# =============================================================================
# TESTS GAME SESSION
# =============================================================================


class TestNormalizeGameSession:
    """Tests for normalize_game_session"""

    def test_none_input(self):
        """None -> None"""
        assert normalize_game_session(None) is None

    def test_minimal_input(self):
        """Minimal input"""
        session = normalize_game_session({"name": "Ma partie"})
        assert session.name == "Ma partie"
        assert session.current_cycle == 1
        assert session.status == "active"

    def test_english_keys(self):
        """English keys"""
        session = normalize_game_session(
            {
                "name": "Adventure",
                "current_cycle": 5,
                "game_date": "Lundi 3 janvier",
                "time": "14h30",
                "current_location": "Bar du port",
            }
        )
        assert session.current_cycle == 5
        assert session.game_date == "Lundi 3 janvier"
        assert session.time == "14h30"
        assert session.current_location == "Bar du port"

    def test_npcs_present(self):
        """NPCs present list"""
        session = normalize_game_session({"npcs_present": ["Alice", "Bob"]})
        assert session.npcs_present == ["Alice", "Bob"]


# =============================================================================
# TESTS AI
# =============================================================================


class TestNormalizeAI:
    """Tests for normalize_ai"""

    def test_none_input(self):
        """None -> None"""
        assert normalize_ai(None) is None

    def test_minimal_input(self):
        """Minimal input"""
        ai = normalize_ai({"name": "ARIA"})
        assert ai.name == "ARIA"
        assert ai.personality == []

    def test_personality_as_list(self):
        """Personality as list"""
        ai = normalize_ai(
            {"name": "ARIA", "personality": ["sarcastic", "loyal", "curious"]}
        )
        assert ai.personality == ["sarcastic", "loyal", "curious"]

    def test_personality_as_string(self):
        """Personality as string (legacy) -> list"""
        ai = normalize_ai({"name": "ARIA", "personality": "sarcastic"})
        assert ai.personality == ["sarcastic"]

    def test_all_fields(self):
        """All fields"""
        ai = normalize_ai(
            {
                "name": "ARIA",
                "personality": ["sarcastic"],
                "voice": "warm",
                "relationship": 5,
            }
        )
        assert ai.name == "ARIA"
        assert ai.voice == "warm"
        assert ai.relationship == 5


# =============================================================================
# TESTS FULL GAME STATE
# =============================================================================


class TestNormalizeGameState:
    """Tests for normalize_game_state"""

    def test_empty_input(self):
        """No data -> defaults"""
        state = normalize_game_state()
        assert state.game is None
        assert state.player.energy == DEFAULT_STATS["energy"]
        assert state.ai is None

    def test_structured_input(self):
        """Structured input (game_data, player_data, ai_data)"""
        state = normalize_game_state(
            game_data={"name": "Test", "current_cycle": 2},
            player_data={"energy": 3.0, "credits": 1000},
            ai_data={"name": "ARIA"},
        )
        assert state.game.name == "Test"
        assert state.game.current_cycle == 2
        assert state.player.energy == 3.0
        assert state.player.credits == 1000
        assert state.ai.name == "ARIA"

    def test_flat_input_already_structured(self):
        """flat_data already structured with game/player keys"""
        state = normalize_game_state(
            flat_data={
                "game": {"name": "Flat Test"},
                "player": {"credits": 500},
                "ai": {"name": "BOT"},
            }
        )
        assert state.game.name == "Flat Test"
        assert state.player.credits == 500
        assert state.ai.name == "BOT"

    def test_flat_input_raw(self):
        """flat_data raw (from DB directly)"""
        state = normalize_game_state(
            flat_data={
                "name": "Direct",
                "energy": 2.5,
                "credits": 800,
            }
        )
        assert state.player.energy == 2.5
        assert state.player.credits == 800


# =============================================================================
# TESTS MERGE
# =============================================================================


class TestMergeGameStates:
    """Tests for merge_game_states"""

    def test_merge_partial_update(self):
        """Partial update"""
        prev = GameState(
            game=GameSessionState(name="Test", current_cycle=1, current_location="Bar"),
            player=PlayerState(energy=4.0, credits=1000),
        )
        merged = merge_game_states(prev, {"game": {"current_cycle": 2}})

        # Updated values
        assert merged.game.current_cycle == 2
        # Preserved values
        assert merged.game.name == "Test"
        assert merged.game.current_location == "Bar"
        assert merged.player.credits == 1000

    def test_merge_preserves_ai(self):
        """Merge preserves AI if not in update"""
        prev = GameState(
            player=PlayerState(),
            ai=AIState(name="ARIA", personality=["cool"]),
        )
        merged = merge_game_states(prev, {"player": {"credits": 500}})

        assert merged.ai.name == "ARIA"
        assert merged.ai.personality == ["cool"]


# =============================================================================
# TESTS SERIALIZATION
# =============================================================================


class TestGameStateToDict:
    """Tests for game_state_to_dict"""

    def test_excludes_none(self):
        """None values are excluded"""
        state = GameState(
            game=GameSessionState(name="Test"),
            player=PlayerState(),
        )
        d = game_state_to_dict(state)

        # ai is None, should not appear
        assert "ai" not in d or d.get("ai") is None

    def test_serializes_inventory(self):
        """Inventory is properly serialized"""
        state = GameState(
            player=PlayerState(inventory=[InventoryItem(name="Clé", quantity=2)]),
        )
        d = game_state_to_dict(state)

        assert len(d["player"]["inventory"]) == 1
        assert d["player"]["inventory"][0]["name"] == "Clé"
        assert d["player"]["inventory"][0]["quantity"] == 2

    def test_uuid_serialization(self):
        """UUIDs are converted to strings"""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        state = GameState(
            game=GameSessionState(id=uid, name="Test"),
            player=PlayerState(),
        )
        d = game_state_to_dict(state)

        assert d["game"]["id"] == str(uid)
