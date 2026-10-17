"""Narrator stream: chunks or progress on the sink, result returned, no callback (#44, #45)."""

import json
import logging

import pytest

from llm.session import LLMSession
from pipeline.errors import to_turn_error
from pipeline.narration_stream import NarrationStream, ProviderCallFailed, stream_narration
from tests.characterization.scripted_llm import ScriptedLLMProvider

NARRATOR = "Tu es le **Maître du Jeu**"
WORLD_BUILDER = "Tu es un créateur de mondes"
MESSAGES = [{"role": "user", "content": "test"}]


class _RecordingSink:
    def __init__(self):
        self.events: list[tuple[str, tuple]] = []

    def __getattr__(self, name):
        if not name.startswith("send_"):
            raise AttributeError(name)

        async def record(*args, **kwargs):
            self.events.append((name, args))
        return record

    def of(self, name: str) -> list[tuple]:
        return [args for event, args in self.events if event == name]


def _session(responses: dict) -> tuple[LLMSession, ScriptedLLMProvider]:
    provider = ScriptedLLMProvider(responses)
    return LLMSession.from_provider(provider), provider


async def test_narration_streams_chunks_and_returns_parsed():
    text = "Hello world. A narrative story about space. This is a long enough text."
    session, _ = _session({"narration": json.dumps({"narrative_text": text})})
    sink = _RecordingSink()
    result = await stream_narration(session, sink, system_prompt=NARRATOR, messages=MESSAGES,
                                    world_gen=False)
    assert isinstance(result, NarrationStream)
    assert result.parsed == {"narrative_text": text}
    assert result.display_text == text
    assert "".join(args[0] for args in sink.of("send_chunk")) == text
    assert sink.of("send_progress") == []


async def test_world_gen_sends_progress_not_chunks():
    raw = json.dumps({"world": {"name": "Test Station"}, "pad": " " * 600})
    session, _ = _session({"world_gen": raw})
    sink = _RecordingSink()
    result = await stream_narration(session, sink, system_prompt=WORLD_BUILDER, messages=MESSAGES,
                                    world_gen=True, temperature=1.0)
    assert sink.of("send_progress")
    assert sink.of("send_progress")[-1] == (raw,)
    assert sink.of("send_chunk") == []
    assert result.parsed["world"]["name"] == "Test Station"
    assert result.display_text is None
    assert result.raw == raw


async def test_provider_failure_raises_without_sending():
    session, provider = _session({})
    provider.fail_on["narration"] = RuntimeError("API down")
    sink = _RecordingSink()
    with pytest.raises(ProviderCallFailed) as info:
        await stream_narration(session, sink, system_prompt=NARRATOR, messages=MESSAGES,
                               world_gen=False)
    assert info.value.provider == "scripted"
    assert isinstance(info.value.__cause__, RuntimeError)
    assert sink.of("send_error") == []


async def test_unparsable_output_returns_partial_text():
    session, _ = _session({"narration": 'garbage {"narrative_text": "Some narrative about broken JSON'})
    sink = _RecordingSink()
    result = await stream_narration(session, sink, system_prompt=NARRATOR, messages=MESSAGES,
                                    world_gen=False)
    assert result.parsed is None
    assert result.display_text == "Some narrative about broken JSON"


async def test_cost_is_returned():
    session, _ = _session({"narration": json.dumps({"narrative_text": "Bonjour."})})
    result = await stream_narration(session, _RecordingSink(), system_prompt=NARRATOR,
                                    messages=MESSAGES, world_gen=False)
    assert result.cost["input_tokens"] == 100
    assert result.cost["output_tokens"] == 50


async def test_ledger_failure_is_internal_not_a_provider_error(monkeypatch):
    session, _ = _session({"narration": json.dumps({"narrative_text": "Bonjour."})})

    def broken_record(*args, **kwargs):
        raise ValueError("ledger row rejected")

    monkeypatch.setattr(session.ledger, "record", broken_record)
    with pytest.raises(Exception) as info:
        await stream_narration(session, _RecordingSink(), system_prompt=NARRATOR,
                               messages=MESSAGES, world_gen=False)
    assert not isinstance(info.value, ProviderCallFailed)
    assert to_turn_error(info.value, "anthropic", "abc").code == "internal"


async def test_consumer_error_is_internal_provider_error_is_not():
    session, provider = _session({})
    provider.fail_on["narration"] = RuntimeError("API down")
    with pytest.raises(ProviderCallFailed) as info:
        await stream_narration(session, _RecordingSink(), system_prompt=NARRATOR,
                               messages=MESSAGES, world_gen=False)
    assert to_turn_error(info.value, "anthropic", "abc").code == "provider_error"


STORY_FRAGMENT = "Le dragon de verre murmure"


async def test_parse_failure_logs_length_at_error_and_excerpt_at_debug(caplog, log_prompts):
    raw = f'garbage {{"narrative_text": "{STORY_FRAGMENT}'
    session, _ = _session({"narration": raw})
    with caplog.at_level(logging.DEBUG):
        await stream_narration(session, _RecordingSink(), system_prompt=NARRATOR,
                               messages=MESSAGES, world_gen=False)
    messages = [(r.levelno, r.getMessage()) for r in caplog.records]
    errors = [m for level, m in messages if level >= logging.ERROR and "[LLM]" in m]
    assert errors == [f"[LLM] JSON parse FAILED. Raw output: {len(raw)} chars"]
    debug = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(STORY_FRAGMENT in m for m in debug)


async def test_parse_failure_excerpt_is_not_logged_without_log_prompts(caplog):
    session, _ = _session({"narration": f'garbage {{"narrative_text": "{STORY_FRAGMENT}'})
    with caplog.at_level(logging.DEBUG):
        await stream_narration(session, _RecordingSink(), system_prompt=NARRATOR,
                               messages=MESSAGES, world_gen=False)
    assert STORY_FRAGMENT not in caplog.text
