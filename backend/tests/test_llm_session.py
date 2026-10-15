"""LLMSession: per-purpose provider/model, explicit per-call cost, structured dispatch."""

import asyncio

import pytest

from llm.session import LLMCall, LLMSession, Purpose
from llm.usage import UsageLedger
from services.llm_providers import (
    CompletionResult, LLMProvider, LLMUsage, StructuredOutputMode, ToolResult,
)


class FakeProvider(LLMProvider):
    MODEL_MAIN = "fake-main"
    STRUCTURED_OUTPUT = StructuredOutputMode.TOOL_USE

    def __init__(self, text='{"ok": true}', usage=None, fail=None, mode=None, cache=False):
        self.text, self.usage, self.fail, self._cache = text, usage or LLMUsage(10, 5), fail, cache
        if mode:
            self.STRUCTURED_OUTPUT = mode
        self.calls = []

    async def stream(self, system_prompt, messages, temperature, max_tokens):
        self.calls.append("stream")
        yield self.text[:3]
        if self.fail:
            raise self.fail
        yield self.text[3:]
        yield self.usage

    async def complete(self, system_prompt, messages, temperature, max_tokens):
        self.calls.append("complete")
        if self.fail:
            raise self.fail
        return CompletionResult(content=self.text, usage=self.usage)

    async def complete_with_tools(self, system_prompt, messages, tools, tool_choice, temperature, max_tokens):
        self.calls.append("tools")
        return ToolResult(tool_name=tools[0]["name"], tool_input={"tool": True}, usage=self.usage)

    @property
    def supports_cache_control(self):
        return self._cache

    @property
    def provider_name(self):
        return "fake"


async def test_complete_json_returns_value_and_its_own_cost():
    ledger = UsageLedger()
    call = await LLMSession.from_provider(FakeProvider(), ledger).complete_json(
        Purpose.MECHANICAL, "sys", "user", 0.2, 500)
    assert call.value == {"ok": True}
    assert call.cost["input_tokens"] == 10 and call.cost["provider"] == "fake"
    assert "mechanical" in ledger.get_summary()["purposes"]


async def test_failed_call_has_no_cost():
    call = await LLMSession.from_provider(FakeProvider(fail=RuntimeError("down"))).complete_json(
        Purpose.RESOLVER, "sys", "user", 0.3, 100)
    assert call == LLMCall(value=None, cost=None)


async def test_concurrent_calls_keep_their_own_cost():
    ledger = UsageLedger()

    async def one(tokens):
        session = LLMSession.from_provider(FakeProvider(usage=LLMUsage(tokens, 0)), ledger)
        return await session.extract_structured("sys", "user", "t", "d", {}, 0.3, 100)

    calls = await asyncio.gather(one(100), one(200), one(300))
    assert [c.cost["input_tokens"] for c in calls] == [100, 200, 300]


async def test_stream_yields_text_then_exposes_cost():
    stream = LLMSession.from_provider(FakeProvider(text="abcdef")).stream(
        Purpose.NARRATION, "sys", [], 0.7, 100)
    assert [x async for x in stream] == ["abc", "def"]
    assert stream.cost["output_tokens"] == 5


async def test_stream_failure_records_nothing():
    ledger = UsageLedger()
    stream = LLMSession.from_provider(FakeProvider(fail=RuntimeError("down")), ledger).stream(
        Purpose.NARRATION, "sys", [], 0.7, 100)
    with pytest.raises(RuntimeError):
        async for _ in stream:
            pass
    assert stream.cost is None and ledger.get_summary()["total_cost_usd"] == 0


@pytest.mark.parametrize("mode,expected_call", [
    (StructuredOutputMode.TOOL_USE, "tools"),
    (StructuredOutputMode.TEXT, "complete"),
])
async def test_extract_structured_dispatches_on_mode(mode, expected_call):
    provider = FakeProvider(mode=mode)
    await LLMSession.from_provider(provider).extract_structured("sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == [expected_call]


async def test_json_schema_without_support_falls_back_to_text():
    provider = FakeProvider(mode=StructuredOutputMode.JSON_SCHEMA)
    call = await LLMSession.from_provider(provider).extract_structured("sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == ["complete"] and call.value == {"ok": True}


def test_caps_come_from_the_narration_provider():
    caps = LLMSession.from_provider(FakeProvider(cache=True)).caps
    assert caps.cache_control is True and caps.structured_output == StructuredOutputMode.TOOL_USE


def test_model_per_purpose_matches_before_p2():
    session = LLMSession("anthropic", api_key="k", user_model="claude-sonnet-4-6")
    assert session.model_for(Purpose.NARRATION) == "claude-sonnet-4-6"
    assert session.model_for(Purpose.MECHANICAL) == "claude-haiku-4-5"
    assert session.model_for(Purpose.RESOLVER) == "claude-sonnet-4-6"  # provider default
    mistral = LLMSession("mistral", api_key="k", user_model="mistral-small-latest")
    assert mistral.model_for(Purpose.MECHANICAL) == "mistral-small-latest"
    assert mistral.model_for(Purpose.DIRECTOR) == "mistral-large-latest"  # provider default


def test_session_has_no_request_lifecycle():
    # Background tasks keep using the session after the SSE response ends:
    # it must not own or close clients.
    session = LLMSession("anthropic", api_key="k")
    assert not hasattr(session, "close") and not hasattr(session, "__aexit__")


class _ToolFailsProvider(FakeProvider):
    def __init__(self, error, **kw):
        super().__init__(**kw)
        self.error = error

    async def complete_with_tools(self, *a, **kw):
        self.calls.append("tools")
        raise self.error


@pytest.mark.parametrize("error", [NotImplementedError("no tool_use"), RuntimeError("API error")])
async def test_tool_use_failure_falls_back_to_text(error):
    provider = _ToolFailsProvider(error, text='{"facts": []}')
    ledger = UsageLedger()
    call = await LLMSession.from_provider(provider, ledger).extract_structured(
        "sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == ["tools", "complete"]
    assert call.value == {"facts": []} and call.cost["input_tokens"] == 10


class _SchemaProvider(FakeProvider):
    STRUCTURED_OUTPUT = StructuredOutputMode.JSON_SCHEMA

    def __init__(self, schema_text, **kw):
        super().__init__(**kw)
        self.schema_text = schema_text

    async def complete_with_schema(self, system_prompt, messages, schema_name, schema,
                                   temperature, max_tokens):
        self.calls.append("schema")
        return CompletionResult(content=self.schema_text, usage=self.usage)


async def test_json_schema_success_returns_value_and_cost():
    ledger = UsageLedger()
    provider = _SchemaProvider('{"facts": [1]}')
    call = await LLMSession.from_provider(provider, ledger).extract_structured(
        "sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == ["schema"]
    assert call.value == {"facts": [1]} and call.cost["input_tokens"] == 10
    assert ledger.get_summary()["purposes"]["extraction"]["calls"] == 1


async def test_json_schema_invalid_json_is_still_recorded_then_text_fallback():
    ledger = UsageLedger()
    provider = _SchemaProvider("not json", text='{"ok": true}')
    call = await LLMSession.from_provider(provider, ledger).extract_structured(
        "sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == ["schema", "complete"]
    assert call.value == {"ok": True}
    assert ledger.get_summary()["purposes"]["extraction"]["calls"] == 2
