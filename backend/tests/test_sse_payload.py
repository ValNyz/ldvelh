"""
Tests for SSE payload models.
Verifies consistent contract between init and light modes.
"""

from schema.sse_payload import (
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


class TestSSEGameState:
    def test_defaults(self):
        gs = SSEGameState()
        assert gs.game is None
        assert gs.player is None
        assert gs.ai is None
        assert gs.world_created is False

    def test_with_data(self):
        gs = SSEGameState(
            game={"current_cycle": 3, "time": "10h00"},
            player={"energy": 4.0, "credits": 1200},
            ai={"name": "ARIA"},
            world_created=True,
        )
        assert gs.game["current_cycle"] == 3
        assert gs.player["energy"] == 4.0
        assert gs.ai["name"] == "ARIA"


class TestWorldInfo:
    def test_minimal(self):
        wi = WorldInfo(
            world=WorldSummary(name="Station X"),
            protagonist=ProtagonistSummary(name="Valentin"),
            ai=AISummary(name="ARIA"),
        )
        assert wi.world.name == "Station X"
        assert wi.npc_count == 0
        assert wi.arrival is None

    def test_full(self):
        wi = WorldInfo(
            world=WorldSummary(name="Escale", atmosphere="industrial", sectors=["A", "B"]),
            protagonist=ProtagonistSummary(
                name="Valentin", origin="Earth", departure_reason="fresh_start", credits=1400
            ),
            ai=AISummary(name="ARIA", personality=["sarcastic"], quirk="References"),
            npc_count=5,
            location_count=7,
            org_count=2,
            inventory_count=3,
            arrival=ArrivalSummary(location="Terminal 7", date="Lundi 1er", time="08h00"),
            arrival_event={"arrival_method": "navette"},
        )
        assert wi.npc_count == 5
        assert wi.arrival.location == "Terminal 7"
        assert wi.arrival_event["arrival_method"] == "navette"


class TestSSEDonePayload:
    def test_init_mode(self):
        payload = SSEDonePayload(
            game_state=SSEGameState(
                game={"current_cycle": 1},
                player={"energy": 4.0, "credits": 1400},
                world_created=True,
            ),
            world_info=WorldInfo(
                world=WorldSummary(name="Station X"),
                protagonist=ProtagonistSummary(name="Valentin"),
                ai=AISummary(name="ARIA"),
                npc_count=5,
                location_count=7,
            ),
        )
        d = payload.model_dump(exclude_none=True)
        assert "world_info" in d
        assert "meta" not in d
        assert "ui" not in d
        assert d["game_state"]["world_created"] is True
        assert d["world_info"]["npc_count"] == 5

    def test_light_mode(self):
        payload = SSEDonePayload(
            game_state=SSEGameState(
                game={"current_cycle": 3, "time": "10h00"},
                player={"energy": 3.5},
                world_created=True,
            ),
            meta=SSEMeta(narration_cost={"input_tokens": 1000, "cost_usd": 0.01}),
            ui=SSEUIHints(inventory_hints=[{"item_name": "Key", "action": "acquire"}]),
        )
        d = payload.model_dump(exclude_none=True)
        assert "world_info" not in d
        assert d["meta"]["narration_cost"]["input_tokens"] == 1000
        assert len(d["ui"]["inventory_hints"]) == 1

    def test_game_state_shape_identical(self):
        """Both modes produce the same game_state structure."""
        init_gs = SSEGameState(game={"id": "a"}, player={}, ai={}, world_created=True)
        light_gs = SSEGameState(game={"id": "b"}, player={}, ai={}, world_created=True)
        init_keys = set(init_gs.model_dump().keys())
        light_keys = set(light_gs.model_dump().keys())
        assert init_keys == light_keys

    def test_exclude_none_removes_optionals(self):
        payload = SSEDonePayload(
            game_state=SSEGameState(world_created=False),
        )
        d = payload.model_dump(exclude_none=True)
        assert "world_info" not in d
        assert "meta" not in d
        assert "ui" not in d
        # game_state always present
        assert "game_state" in d

    def test_light_mode_no_meta_when_no_cost(self):
        payload = SSEDonePayload(
            game_state=SSEGameState(world_created=True),
        )
        d = payload.model_dump(exclude_none=True)
        assert "meta" not in d


class TestNarratorDeltasStored:
    def test_defaults(self):
        d = NarratorDeltasStored()
        assert d.credit_delta is None
        assert d.extraction_triggers == []
        assert d.cost is None

    def test_with_data(self):
        d = NarratorDeltasStored(
            credit_delta={"amount": -15, "description": "cafe"},
            inventory_hints=[{"item_name": "Key", "action": "acquire"}],
            entity_reveals=[{"entity_type": "character", "current_name": "Alice"}],
            extraction_triggers=["characters", "narrative_arcs"],
            cost={"input_tokens": 500, "output_tokens": 200, "model": "claude-sonnet-4-6"},
        )
        assert d.credit_delta["amount"] == -15
        assert d.extraction_triggers == ["characters", "narrative_arcs"]

    def test_exclude_none(self):
        d = NarratorDeltasStored(
            inventory_hints=[{"item_name": "Key", "action": "acquire"}],
        )
        dumped = d.model_dump(exclude_none=True)
        assert "credit_delta" not in dumped
        assert "cost" not in dumped
        assert len(dumped["inventory_hints"]) == 1
