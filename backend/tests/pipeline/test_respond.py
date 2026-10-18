"""Done payload of a narration turn: pure assembly of state, costs and UI hints."""

from uuid import uuid4

from domain.turn import NarrationState
from schema import NarrationOutput
from schema.engine import MechanicalDecision, MechanicalResult, RollResult
from pipeline.steps.commit import Committed
from pipeline.steps.narrate import Narrated
from pipeline.steps.respond import build_done_payload

STATE = NarrationState(cycle=2, time="10h30", location="Dock 7",
                       npcs_present=["Mira"], date="Jour 2")


def _client_state() -> dict:
    return {"game": {"current_cycle": 1, "time": "08h00", "current_location": "Bar"},
            "player": {"credits": 100, "engine_stats": None}, "ai": None,
            "world_created": True}


def _committed() -> Committed:
    return Committed(state=STATE, user_message_id=uuid4(), assistant_message_id=uuid4(),
                     narrator_deltas={})


def _narrated(cost: dict | None, hints: list[dict] | None = None) -> Narrated:
    narration = NarrationOutput.model_validate({
        "narrative_text": "Le quai est désert.",
        "time": {"new_time": "10h30", "ellipse": False},
        "current_location": "Dock 7",
        "inventory_hints": hints or [],
    })
    return Narrated(narration=narration, display_text="Le quai est désert.", cost=cost)


def _mechanical(cost: dict | None) -> MechanicalResult:
    return MechanicalResult(
        decision=MechanicalDecision(requires_test=True, skill="Tir"),
        roll=RollResult(dice=[1, 0, -1, 1], total=1, skill_total=3, outcome="success"),
        cost=cost,
    )


def test_done_payload_carries_state_costs_and_hints():
    hint = {"action": "acquire", "item_name": "Clé", "item_description": "Une clé rouillée"}
    payload = build_done_payload(_client_state(), _committed(), "none",
                                 _narrated({"cost_usd": 0.01}, [hint]),
                                 _mechanical({"cost_usd": 0.002}))
    assert payload.meta.narration_cost["cost_usd"] == 0.01
    assert payload.meta.mechanical_cost["cost_usd"] == 0.002
    assert len(payload.ui.inventory_hints) == 1
    assert payload.game_state.engine is None
    game = payload.game_state.game
    assert (game["current_cycle"], game["time"], game["current_location"]) == (2, "10h30", "Dock 7")
    assert game["npcs_present"] == ["Mira"] and game["game_date"] == "Jour 2"


def test_done_payload_without_costs_has_only_the_message_ids():
    payload = build_done_payload(_client_state(), _committed(), "fate_core",
                                 _narrated(None), None)
    assert payload.meta.narration_cost is None and payload.meta.mechanical_cost is None
    assert payload.ui is None
    assert payload.game_state.engine == "fate_core"


def test_done_payload_names_the_saved_messages():
    committed = _committed()
    payload = build_done_payload(_client_state(), committed, "none", _narrated(None), None)
    assert payload.meta.user_message_id == committed.user_message_id
    assert payload.meta.assistant_message_id == committed.assistant_message_id
    assert payload.meta.narration_cost is None
