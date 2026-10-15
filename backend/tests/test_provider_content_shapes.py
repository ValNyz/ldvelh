"""Providers tolerate list-shaped and empty message content (live probe findings)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from services.llm_providers import (
    LLMUsage,
    MistralProvider,
    OpenAICompatibleProvider,
    _content_text,
)


def test_none_is_empty_text():
    assert _content_text(None) == ""


def test_plain_string_unchanged():
    assert _content_text("bonjour") == "bonjour"


def test_list_of_chunks_keeps_text_only():
    chunks = [
        SimpleNamespace(type="thinking", thinking="..."),
        SimpleNamespace(type="text", text="Bon"),
        {"type": "text", "text": "jour"},
        {"type": "thinking", "thinking": "..."},
    ]
    assert _content_text(chunks) == "Bonjour"


def _usage():
    return SimpleNamespace(prompt_tokens=3, completion_tokens=2)


def _chunk(content, usage=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))], usage=usage)


async def _aiter(items):
    for item in items:
        yield item


async def test_mistral_stream_handles_list_content():
    provider = MistralProvider(api_key="k")
    events = [
        SimpleNamespace(data=_chunk([SimpleNamespace(type="thinking", thinking="x")])),
        SimpleNamespace(data=_chunk([SimpleNamespace(type="text", text="Bon")])),
        SimpleNamespace(data=_chunk(None, usage=_usage())),
    ]
    provider.client = SimpleNamespace(chat=SimpleNamespace(stream_async=AsyncMock(return_value=_aiter(events))))
    out = [x async for x in provider.stream("sys", [], 0.5, 100)]
    assert out[0] == "Bon"
    assert len(out) == 2 and isinstance(out[1], LLMUsage)


async def test_mistral_complete_handles_list_content():
    provider = MistralProvider(api_key="k")
    message = SimpleNamespace(content=[{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "ok"}])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=_usage())
    provider.client = SimpleNamespace(chat=SimpleNamespace(complete_async=AsyncMock(return_value=response)))
    result = await provider.complete("sys", [], 0.5, 100)
    assert result.content == "ok"


def _openai_provider(response):
    provider = OpenAICompatibleProvider(api_key="k", base_url="http://localhost")
    provider.MODEL_MAIN = "m"
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    return provider


async def test_openai_complete_none_content_is_empty():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))], usage=_usage())
    result = await _openai_provider(response).complete("sys", [], 0.5, 100)
    assert result.content == ""


async def test_openai_complete_with_schema_none_content_is_empty():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))], usage=_usage())
    result = await _openai_provider(response).complete_with_schema("sys", [], "s", {}, 0.5, 100)
    assert result.content == ""


async def test_openai_stream_skips_empty_text():
    chunks = [_chunk(None), _chunk([{"type": "text", "text": "Hi"}]), _chunk("", usage=_usage())]
    out = [x async for x in _openai_provider(_aiter(chunks)).stream("sys", [], 0.5, 100)]
    assert out[0] == "Hi" and len(out) == 2
