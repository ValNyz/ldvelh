"""Anthropic provider on the Claude 5 family: model list, request rules, pricing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.llm_providers import AnthropicProvider
from services.pricing import lookup_pricing

CLAUDE_5 = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1"]


def _response(*blocks):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(content=list(blocks), usage=usage)


def _provider(model):
    provider = AnthropicProvider(api_key="k", model=model)
    provider.client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    return provider


class TestModelList:
    def test_offers_exactly_the_claude_5_family(self):
        assert sorted(AnthropicProvider.MODELS) == sorted(CLAUDE_5)

    def test_defaults(self):
        provider = AnthropicProvider(api_key="k")
        assert provider.MODEL_MAIN == "claude-sonnet-5-5"
        assert provider.model_name("mechanical") == "claude-haiku-5-5"

    def test_unknown_or_retired_model_falls_back_to_default(self):
        # A player preference saved before the switch still works.
        assert AnthropicProvider(api_key="k", model="claude-sonnet-4-6").MODEL_MAIN == "claude-sonnet-5-5"


class TestRequestRules:
    @pytest.mark.parametrize("model", CLAUDE_5)
    async def test_no_sampling_parameters(self, model):
        provider = _provider(model)
        provider.client.messages.create.return_value = _response(SimpleNamespace(type="text", text="{}"))
        await provider.complete("sys", [{"role": "user", "content": "x"}], temperature=0.3, max_tokens=500)
        kwargs = provider.client.messages.create.await_args.kwargs
        assert "temperature" not in kwargs and "top_p" not in kwargs

    async def test_sonnet_runs_without_up_front_thinking(self):
        provider = _provider("claude-sonnet-5-5")
        provider.client.messages.create.return_value = _response(SimpleNamespace(type="text", text="{}"))
        await provider.complete("sys", [], temperature=0.7, max_tokens=4000)
        kwargs = provider.client.messages.create.await_args.kwargs
        assert kwargs["extra_body"]["thinking"] == {"type": "between_tools"}
        assert kwargs["max_tokens"] == 4000

    async def test_haiku_thinking_disabled(self):
        provider = _provider("claude-haiku-5-5")
        provider.client.messages.create.return_value = _response(SimpleNamespace(type="text", text="{}"))
        await provider.complete("sys", [], temperature=0.2, max_tokens=500)
        kwargs = provider.client.messages.create.await_args.kwargs
        assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}
        assert kwargs["max_tokens"] == 500

    @pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-fable-5-1"])
    async def test_always_thinking_models_get_room_to_think(self, model):
        provider = _provider(model)
        provider.client.messages.create.return_value = _response(SimpleNamespace(type="text", text="{}"))
        await provider.complete("sys", [], temperature=0.2, max_tokens=500)
        kwargs = provider.client.messages.create.await_args.kwargs
        assert "thinking" not in kwargs.get("extra_body", {})
        assert kwargs["max_tokens"] == 500 + AnthropicProvider.THINKING_HEADROOM

    async def test_text_is_read_after_thinking_blocks(self):
        provider = _provider("claude-opus-5-5")
        provider.client.messages.create.return_value = _response(
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="text", text='{"ok": true}'),
        )
        result = await provider.complete("sys", [], temperature=0.2, max_tokens=500)
        assert result.content == '{"ok": true}'

    async def test_tool_choice_is_never_forced(self):
        provider = _provider("claude-sonnet-5-5")
        provider.client.messages.create.return_value = _response(
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="tool_use", name="extract_characters", input={"characters": []}),
        )
        result = await provider.complete_with_tools(
            "sys", [], [{"name": "extract_characters"}],
            {"type": "tool", "name": "extract_characters"}, temperature=0.3, max_tokens=3000)
        assert provider.client.messages.create.await_args.kwargs["tool_choice"] == {"type": "auto"}
        assert result.tool_input == {"characters": []}


class TestPricing:
    @pytest.mark.parametrize("model,inp,out,write,read", [
        ("claude-sonnet-5-5", 2.0, 10.0, 2.5, 0.10),
        ("claude-opus-5-5", 4.0, 20.0, 5.0, 0.20),
        ("claude-haiku-5-5", 0.10, 0.50, 0.125, 0.01),
        ("claude-fable-5-1", 10.0, 50.0, 12.5, 0.25),
    ])
    def test_claude_5_prices(self, model, inp, out, write, read):
        p = lookup_pricing(model, "anthropic")
        assert (p.input, p.output, p.cache_write, p.cache_read) == (inp, out, write, read)
