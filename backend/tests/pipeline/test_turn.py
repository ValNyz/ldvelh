"""run_turn chains the steps, stops at HALT and lets errors through."""

from uuid import uuid4

import pytest

from domain.game import GameSnapshot
from pipeline import turn
from pipeline.context import TurnContext, TurnRequest
from pipeline.errors import TurnError
from pipeline.steps.arbitrate import HALT, Arbitration
from pipeline.steps.narrate import Narrated


class _Session:
    provider_name = "scripted"

    def model_for(self, purpose):
        return "scripted-model"


class _Pool:
    """The commit's connection: acquired before the shielded commit, released after it."""

    async def acquire(self):
        return object()

    async def release(self, conn):
        pass


def _ctx() -> TurnContext:
    game_id = uuid4()
    snapshot = GameSnapshot(id=game_id, world_created=True, current_cycle=1,
                            current_time="08h00", current_location_name="Bar")
    return TurnContext(request=TurnRequest(game_id=game_id, user_id=uuid4(), message="Je regarde."),
                       snapshot=snapshot, session=_Session(), sink=None, pool=_Pool(), engine=None,
                       ref="test")


class _Spy:
    def __init__(self, name: str, log: list[str], result=None, error: Exception | None = None):
        self.name = name
        self.log = log
        self.calls = 0
        self.result = result
        self.error = error

    async def __call__(self, *args):
        self.calls += 1
        self.log.append(self.name)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def call_log() -> list[str]:
    """Names of the steps, in the order run_turn called them."""
    return []


@pytest.fixture
def steps(monkeypatch, call_log):
    results = {
        "load_turn": object(),
        "arbitrate": Arbitration(mechanical=None, resumed_roll_id=None),
        "narrate": Narrated(narration=None, display_text="", cost=None),
        "commit_turn": object(),
        "respond": None,
        "schedule_background": None,
    }
    spies = {name: _Spy(name, call_log, result=result) for name, result in results.items()}
    for name, spy in spies.items():
        monkeypatch.setattr(turn, name, spy)
    return spies


async def test_run_turn_runs_every_step_in_order(steps, call_log):
    await turn.run_turn(_ctx())
    assert call_log == ["load_turn", "arbitrate", "narrate", "commit_turn", "respond",
                        "schedule_background"]


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


@pytest.mark.parametrize("failing", ["respond", "schedule_background", "_log_summary"])
async def test_failure_after_commit_becomes_saved_display_failed(steps, monkeypatch, failing):
    if failing == "_log_summary":
        def broken(*args):
            raise RuntimeError("log handler down")
        monkeypatch.setattr(turn, "_log_summary", broken)
    else:
        steps[failing].error = RuntimeError("db hiccup")
    with pytest.raises(TurnError) as raised:
        await turn.run_turn(_ctx())
    assert raised.value.code == "saved_display_failed"
    assert raised.value.recoverable is False
    assert isinstance(raised.value.__cause__, RuntimeError)


async def test_commit_failure_stays_a_plain_error(steps):
    steps["commit_turn"].error = RuntimeError("disk full")
    with pytest.raises(RuntimeError):
        await turn.run_turn(_ctx())
    assert steps["respond"].calls == 0
