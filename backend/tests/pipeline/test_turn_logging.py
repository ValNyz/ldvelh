"""Turn logs: no prompt or story text at INFO, prompts at DEBUG behind LOG_PROMPTS, one summary line."""

import json
import logging
import re
from types import SimpleNamespace

import pytest

from config import get_settings
from services.engine import fate_core
from tests.characterization import payloads
from tests.characterization.scripted_llm import USAGE

SYSTEM_PROMPT_MARKER = "Maître du Jeu"
NARRATIVE_TEXT = json.loads(payloads.NARRATION)["narrative_text"]

pytestmark = pytest.mark.usefixtures("seeded_random")


@pytest.fixture
def turn_logs(caplog):
    # main.py's basicConfig lives on the root logger; caplog's handler sits there too.
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.fixture
def log_prompts(monkeypatch):
    monkeypatch.setenv("LOG_PROMPTS", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


async def _play(harness, game_id):
    await harness.chat(game_id, "Je regarde autour de moi.")
    await harness.drain()


async def test_no_prompt_or_story_text_at_info(harness, world_game, turn_logs):
    turn_logs.clear()
    await _play(harness, world_game)
    for record in turn_logs.records:
        if record.levelno >= logging.INFO:
            message = record.getMessage()
            assert SYSTEM_PROMPT_MARKER not in message, message[:200]
            assert NARRATIVE_TEXT not in message, message[:200]


async def test_prompts_logged_at_debug_when_enabled(harness, world_game, turn_logs, log_prompts):
    turn_logs.clear()
    await _play(harness, world_game)
    assert any(r.levelno == logging.DEBUG and SYSTEM_PROMPT_MARKER in r.getMessage()
               for r in turn_logs.records)


async def test_prompts_not_logged_by_default(harness, world_game, turn_logs):
    turn_logs.clear()
    await _play(harness, world_game)
    assert not any(SYSTEM_PROMPT_MARKER in r.getMessage() for r in turn_logs.records)


def _summary_lines(turn_logs) -> list[str]:
    return [r.getMessage() for r in turn_logs.records
            if r.levelno == logging.INFO and r.getMessage().startswith("[TURN] ")]


async def test_one_turn_summary_line(harness, world_game, turn_logs):
    turn_logs.clear()
    await _play(harness, world_game)
    lines = _summary_lines(turn_logs)
    assert len(lines) == 1, lines
    # The scripted narration stream reports USAGE (100 in, 50 out); history is the arrival pair.
    assert lines[0].startswith(
        f"[TURN] game={world_game} engine=none provider=anthropic model=scripted-model "
        f"history=2 in={USAGE.input_tokens} out={USAGE.output_tokens} cache_read=0 cost=$"
    ), lines[0]
    assert re.search(r" cost=\$\d+\.\d{4} ms=\d+$", lines[0]), lines[0]


async def test_no_summary_line_when_the_turn_halts(harness, fate_game, turn_logs, monkeypatch):
    """A roll awaiting aspects (HALT) is not a completed turn: no [TURN] line."""
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4)
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    turn_logs.clear()
    events = await harness.chat(fate_game, "Je tente un saut impossible.")
    await harness.drain()
    assert "roll_pending" in harness.summarize(events)
    assert _summary_lines(turn_logs) == []

