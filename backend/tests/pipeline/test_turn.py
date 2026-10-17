"""run_turn chains the steps, stops at HALT and lets errors through."""

from uuid import uuid4

import pytest

from domain.game import GameSnapshot
from pipeline import turn
from pipeline.context import TurnContext, TurnRequest
from pipeline.errors import TurnError
from pipeline.steps.arbitrate import HALT, Arbitration


def _ctx() -> TurnContext:
    game_id = uuid4()
    snapshot = GameSnapshot(id=game_id, world_created=True, current_cycle=1,
                            current_time="08h00", current_location_name="Bar")
    return TurnContext(request=TurnRequest(game_id=game_id, user_id=None, message="Je regarde."),
                       snapshot=snapshot, session=None, sink=None, pool=None, engine=None,
                       ref="test")


class _Spy:
    def __init__(self, result=None, error: Exception | None = None):
        self.calls = 0
        self.result = result
        self.error = error

    async def __call__(self, *args):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def steps(monkeypatch):
    spies = {
        "load_turn": _Spy(result=object()),
        "arbitrate": _Spy(result=Arbitration(mechanical=None, resumed_roll_id=None)),
        "narrate": _Spy(result=object()),
        "commit_turn": _Spy(result=object()),
        "respond": _Spy(),
        "schedule_background": _Spy(),
    }
    for name, spy in spies.items():
        monkeypatch.setattr(turn, name, spy)
    return spies


async def test_run_turn_runs_every_step_in_order(steps):
    await turn.run_turn(_ctx())
    assert all(spy.calls == 1 for spy in steps.values())


async def test_run_turn_stops_at_halt(steps):
    steps["arbitrate"].result = HALT
    await turn.run_turn(_ctx())
    assert steps["narrate"].calls == 0
    assert steps["commit_turn"].calls == 0  # no message saved
    assert steps["respond"].calls == 0


async def test_run_turn_propagates_errors(steps):
    steps["narrate"].error = TurnError("narration_invalid", "Réponse inutilisable.")
    with pytest.raises(TurnError):
        await turn.run_turn(_ctx())
    assert steps["commit_turn"].calls == 0
