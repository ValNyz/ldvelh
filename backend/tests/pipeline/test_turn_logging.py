"""Turn logs: no prompt or story text at INFO, prompts at DEBUG behind LOG_PROMPTS, one summary line."""

import json
import logging

import pytest

from config import get_settings
from tests.characterization import payloads
from tests.characterization.conftest import _seeded_random, harness, llm_mode, scripted_llm, world_game  # noqa: F401

SYSTEM_PROMPT_MARKER = "Maître du Jeu"
NARRATIVE_TEXT = json.loads(payloads.NARRATION)["narrative_text"]


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


async def test_one_turn_summary_line(harness, world_game, turn_logs):
    turn_logs.clear()
    await _play(harness, world_game)
    lines = [r.getMessage() for r in turn_logs.records
             if r.levelno == logging.INFO and r.getMessage().startswith("[TURN] game=")]
    assert len(lines) == 1, lines
    assert "engine=none" in lines[0]
    assert " ms=" in lines[0] and " cost=$" in lines[0]
