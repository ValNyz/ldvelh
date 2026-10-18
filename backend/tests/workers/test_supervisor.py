"""workers.supervisor: per-game background jobs, chained and bounded (#19, #94)."""

import asyncio
import gc
import logging
import warnings
from uuid import uuid4

import pytest
from pydantic import BaseModel

from workers import supervisor

TIMEOUT = 5.0


async def _settle(rounds: int = 20) -> None:
    """Let every ready task run until it blocks."""
    for _ in range(rounds):
        await asyncio.sleep(0)


async def _blocked(event: asyncio.Event, log: list | None = None, name: str = "") -> str:
    if log is not None:
        log.append(f"start {name}")
    await event.wait()
    if log is not None:
        log.append(f"end {name}")
    return name


async def test_jobs_of_one_game_run_in_order():
    g = uuid4()
    log: list[str] = []
    events = [asyncio.Event() for _ in range(3)]
    for i, event in enumerate(events):
        supervisor.enqueue(g, "post_turn", _blocked(event, log, str(i)))
    await _settle()
    events[2].set()
    events[1].set()
    await _settle()
    assert log == ["start 0"]
    events[0].set()
    await supervisor.wait_idle(g, timeout=TIMEOUT)
    assert log == ["start 0", "end 0", "start 1", "end 1", "start 2", "end 2"]


async def test_games_run_in_parallel():
    release = asyncio.Event()
    log: list[str] = []
    supervisor.enqueue(uuid4(), "post_turn", _blocked(release, log, "a"))
    supervisor.enqueue(uuid4(), "post_turn", _blocked(release, log, "b"))
    await _settle()
    assert sorted(log) == ["start a", "start b"]
    release.set()
    await supervisor.wait_idle(timeout=TIMEOUT)


async def test_running_games_are_bounded():
    supervisor.reset(max_running_games=2)
    log: list[str] = []
    events = [asyncio.Event() for _ in range(4)]
    for i, event in enumerate(events):
        supervisor.enqueue(uuid4(), "post_turn", _blocked(event, log, str(i)))
    await _settle()
    started = [entry.split()[1] for entry in log if entry.startswith("start")]
    assert len(started) == 2
    events[int(started[0])].set()
    await _settle()
    assert len([entry for entry in log if entry.startswith("start")]) == 3
    for event in events:
        event.set()
    await supervisor.wait_idle(timeout=TIMEOUT)


async def test_task_is_named_and_referenced():
    g = uuid4()
    release = asyncio.Event()
    task = supervisor.enqueue(g, "post_turn", _blocked(release))
    assert task.get_name() == f"post_turn:{g}"
    assert supervisor.pending(g) == 1
    assert supervisor.pending() == 1
    release.set()
    await task
    assert supervisor.pending(g) == 0
    assert g not in supervisor._jobs


async def test_failure_is_logged_with_game_and_kind(caplog):
    caplog.set_level(logging.ERROR)
    g = uuid4()

    async def boom():
        raise RuntimeError("boom")

    task = supervisor.enqueue(g, "post_turn", boom())
    with pytest.raises(RuntimeError):
        await task
    record = next(r for r in caplog.records if "post_turn" in r.getMessage())
    assert str(g) in record.getMessage()
    assert "boom" in caplog.text  # the traceback of a plain error is kept
    assert supervisor.pending(g) == 0


class _Narration(BaseModel):
    count: int


async def test_failure_with_story_text_is_summarised(caplog):
    caplog.set_level(logging.WARNING)
    g = uuid4()

    async def invalid():
        _Narration.model_validate({"count": "Mira la contrebandière"})

    task = supervisor.enqueue(g, "post_turn", invalid())
    await asyncio.wait({task})
    await _settle()
    assert any("post_turn" in r.getMessage() for r in caplog.records)
    assert "Mira la contrebandière" not in caplog.text


async def test_wait_idle_covers_jobs_enqueued_meanwhile():
    g = uuid4()
    log: list[str] = []

    async def second():
        await asyncio.sleep(0.01)
        log.append("second")

    async def first():
        await asyncio.sleep(0.01)
        supervisor.enqueue(g, "director", second())
        log.append("first")

    supervisor.enqueue(g, "post_turn", first())
    waited = await supervisor.wait_idle(g, timeout=TIMEOUT)
    assert supervisor.pending(g) == 0
    assert log == ["first", "second"]
    assert len(waited) == 2


async def test_wait_idle_times_out():
    g = uuid4()
    release = asyncio.Event()
    task = supervisor.enqueue(g, "post_turn", _blocked(release))
    with pytest.raises(TimeoutError):
        await supervisor.wait_idle(g, timeout=0.05)
    assert not task.done()
    release.set()
    await task


async def test_cancel_game_cancels_pending_and_running():
    g = uuid4()
    release = asyncio.Event()
    started: list[str] = []
    coros = [_blocked(release, started, str(i)) for i in range(3)]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tasks = [supervisor.enqueue(g, "post_turn", coro) for coro in coros]
        await _settle()
        assert await supervisor.cancel_game(g, timeout=TIMEOUT) == 3
        assert supervisor.pending(g) == 0
        assert all(task.cancelled() for task in tasks)
        assert started == ["start 0"]
        assert all(coro.cr_frame is None for coro in coros)  # closed, never left pending
        del tasks, coros
        gc.collect()
    assert not [w for w in caught if issubclass(w.category, RuntimeWarning)]


async def test_cancel_before_first_step_closes_coroutine():
    g = uuid4()
    coro = _blocked(asyncio.Event())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        task = supervisor.enqueue(g, "post_turn", coro)
        assert await supervisor.cancel_game(g, timeout=TIMEOUT) == 1
        assert task.cancelled()
        assert coro.cr_frame is None
        del task, coro
        gc.collect()
    assert not [w for w in caught if issubclass(w.category, RuntimeWarning)]


async def test_cancelled_predecessor_does_not_unblock_successor_early():
    """Cancelling a queued job lets the next one wait for the still-running first job."""
    g = uuid4()
    log: list[str] = []
    first_release = asyncio.Event()
    supervisor.enqueue(g, "post_turn", _blocked(first_release, log, "0"))
    middle = supervisor.enqueue(g, "post_turn", _blocked(asyncio.Event(), log, "1"))
    supervisor.enqueue(g, "post_turn", _blocked(asyncio.Event(), log, "2"))
    await _settle()
    middle.cancel()
    await _settle()
    assert log == ["start 0"]
    first_release.set()
    await _settle()
    assert log == ["start 0", "end 0", "start 2"]
    await supervisor.cancel_game(g, timeout=TIMEOUT)


async def test_cancel_game_leaves_other_games_alone():
    g, other = uuid4(), uuid4()
    release = asyncio.Event()
    supervisor.enqueue(g, "post_turn", _blocked(release))
    kept = supervisor.enqueue(other, "post_turn", _blocked(release))
    await _settle()
    assert await supervisor.cancel_game(g, timeout=TIMEOUT) == 1
    assert supervisor.pending(other) == 1
    assert not kept.done()
    release.set()
    await kept
    assert kept.result() == ""


async def test_drain_waits_then_cancels_and_logs(caplog):
    caplog.set_level(logging.WARNING)
    fast_game, stuck_game = uuid4(), uuid4()

    async def fast():
        await asyncio.sleep(0.05)
        return "done"

    quick = supervisor.enqueue(fast_game, "post_turn", fast())
    stuck = supervisor.enqueue(stuck_game, "director", _blocked(asyncio.Event()))
    await supervisor.drain(timeout=0.2)
    assert quick.result() == "done"
    assert stuck.cancelled()
    assert any("Cancelled at shutdown" in r.getMessage() and "kind=director" in r.getMessage()
               and f"game={stuck_game}" in r.getMessage() for r in caplog.records)
    assert supervisor.pending() == 0


async def test_queue_depth_warning(caplog):
    caplog.set_level(logging.WARNING)
    g = uuid4()
    release = asyncio.Event()
    for _ in range(4):
        supervisor.enqueue(g, "post_turn", _blocked(release))
    assert any(f"[SUPERVISOR] game={g} queue depth=4" in r.getMessage() for r in caplog.records)
    release.set()
    await supervisor.wait_idle(g, timeout=TIMEOUT)


def test_zero_game_limit_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="at least 1"):
        supervisor.reset(max_running_games=0)

    class _Settings:
        supervisor_max_running_games = 0

    monkeypatch.setattr(supervisor, "get_settings", lambda: _Settings())
    with pytest.raises(ValueError, match="at least 1"):
        supervisor.reset()


@pytest.mark.parametrize("env_var, field, default, override, invalid, message", [
    ("SUPERVISOR_MAX_GAMES", "supervisor_max_running_games", 3, "5", "0",
     "SUPERVISOR_MAX_GAMES must be at least 1"),
    ("SUPERVISOR_DRAIN_TIMEOUT", "supervisor_drain_timeout", 20.0, "2.5", "0",
     "SUPERVISOR_DRAIN_TIMEOUT must be greater than 0"),
    ("SUPERVISOR_CANCEL_TIMEOUT", "supervisor_cancel_timeout", 10.0, "1.5", "-1",
     "SUPERVISOR_CANCEL_TIMEOUT must be greater than 0"),
])
def test_supervisor_settings_are_read_at_construction(monkeypatch, env_var, field, default,
                                                      override, invalid, message):
    from pydantic import ValidationError

    from config import Settings

    monkeypatch.delenv(env_var, raising=False)
    assert getattr(Settings(_env_file=None), field) == default
    monkeypatch.setenv(env_var, override)
    assert getattr(Settings(_env_file=None), field) == float(override)
    monkeypatch.setenv(env_var, invalid)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None)
    monkeypatch.delenv(env_var)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **{field: invalid})
