"""Narrator stream: chunks or progress on the sink, result returned, no callback (#44, #45)."""

import json

import pytest

from llm.session import LLMSession
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
