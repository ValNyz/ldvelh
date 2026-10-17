"""Turn logs: no prompt or story text at INFO, prompts at DEBUG behind LOG_PROMPTS, one summary line."""

import json
import logging
import re
from types import SimpleNamespace

import pytest

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


async def test_halted_turn_logs_a_halted_line(harness, fate_game, turn_logs, monkeypatch):
    """A roll awaiting aspects (HALT) logs its own [TURN] line: no tokens, no cost."""
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4)
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    turn_logs.clear()
    events = await harness.chat(fate_game, "Je tente un saut impossible.")
    await harness.drain()
    assert "roll_pending" in harness.summarize(events)
    lines = _summary_lines(turn_logs)
    assert len(lines) == 1, lines
    assert re.fullmatch(
        rf"\[TURN\] game={fate_game} engine=fate_core provider=anthropic "
        r"halted=roll_pending ms=\d+", lines[0]), lines[0]


async def test_deltas_log_shape_is_fixed(harness, world_game, turn_logs):
    """Debug line: both `credit` and `compel` keys are always present (null when absent)."""
    harness.llm._responses["narration"] = payloads.NARRATION_WITH_COMPEL
    turn_logs.clear()
    await _play(harness, world_game)
    lines = [r.getMessage() for r in turn_logs.records
             if r.levelno == logging.DEBUG and r.getMessage().startswith("[CHAT] Deltas applied: ")]
    assert len(lines) == 1, lines
    assert set(json.loads(lines[0].split(": ", 1)[1])) == {"credit", "compel"}
