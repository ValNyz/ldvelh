"""ModelProfile: serialization and application by every provider."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from llm.profile import DEFAULT_PROFILE, ModelProfile
from services.llm_providers import (
    AnthropicProvider,
    MistralProvider,
    NebiusProvider,
    NousResearchProvider,
    WandbProvider,
    get_provider,
)


class TestModelProfile:
    def test_default_values(self):
        assert DEFAULT_PROFILE == ModelProfile(True, True, None, 0)

    def test_from_none_is_default(self):
        assert ModelProfile.from_dict(None) is DEFAULT_PROFILE

    def test_unknown_keys_ignored(self):
        p = ModelProfile.from_dict({"send_temperature": False, "bogus": 1})
        assert p.send_temperature is False and p.force_tool is True

    def test_round_trip(self):
        p = ModelProfile(False, False, {"type": "disabled"}, 100)
        assert ModelProfile.from_dict(p.to_dict()) == p


def _anthropic(profile=None, model="claude-sonnet-5-5"):
    p = AnthropicProvider(api_key="k", model=model, profile=profile)
    resp = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="t", input={}, id="1")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1,
                              cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )
    p.client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=resp)))
    return p


class TestAnthropic:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("force,expected", [(True, "tool"), (False, "auto")])
    async def test_tool_choice(self, force, expected):
        p = _anthropic(ModelProfile(send_temperature=False, force_tool=force))
        await p.complete_with_tools("s", [], [{"name": "t"}], {"type": "tool", "name": "t"}, 0.5, 100)
        kw = p.client.messages.create.call_args.kwargs
        assert kw["tool_choice"]["type"] == expected
        assert "temperature" not in kw

    def test_temperature_sent_only_when_enabled(self):
        assert "temperature" not in _anthropic(ModelProfile(send_temperature=False))._request_options(10, 0.3)
        assert _anthropic(ModelProfile(send_temperature=True))._request_options(10, 0.3)["temperature"] == 0.3

    def test_thinking_and_headroom_from_profile(self):
        p = _anthropic(ModelProfile(thinking={"type": "disabled"}, thinking_headroom=50))
        o = p._request_options(10)
        assert o["max_tokens"] == 60 and o["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_no_profile_keeps_claude5_fallback(self):
        o = _anthropic()._request_options(10)
        assert o["extra_body"] == {"thinking": {"type": "between_tools"}}
        assert "temperature" not in o
        assert _anthropic(model="claude-opus-5-5")._request_options(10)["max_tokens"] == 10 + AnthropicProvider.THINKING_HEADROOM

    def test_unknown_model_with_profile_is_accepted(self):
        assert _anthropic(ModelProfile(), model="claude-future-9").MODEL_MAIN == "claude-future-9"


def _chat_client():
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x"))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    return resp


class TestMistral:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("profile,has", [(None, True), (ModelProfile(send_temperature=False), False)])
    async def test_temperature(self, profile, has):
        p = MistralProvider(api_key="k", model="m", profile=profile)
        create = AsyncMock(return_value=_chat_client())
        p.client = SimpleNamespace(chat=SimpleNamespace(complete_async=create))
        await p.complete("s", [], 0.4, 10)
        assert ("temperature" in create.call_args.kwargs) is has


class TestOpenAICompatible:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("cls", [WandbProvider, NebiusProvider, NousResearchProvider])
    @pytest.mark.parametrize("profile,has", [(None, True), (ModelProfile(send_temperature=False), False)])
    async def test_temperature(self, cls, profile, has):
        p = cls(api_key="k", model="m", profile=profile)
        create = AsyncMock(return_value=_chat_client())
        p.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        await p.complete("s", [], 0.4, 10)
        assert ("temperature" in create.call_args.kwargs) is has
        if profile:
            await p.complete_with_schema("s", [], "n", {}, 0.4, 10)
            assert "temperature" not in create.call_args.kwargs


class TestGetProvider:
    def test_profile_passed_through(self):
        prof = ModelProfile(send_temperature=False)
        assert get_provider("mistral", api_key="k", model="m", profile=prof).profile is prof

    def test_profile_without_key_not_cached_singleton(self, monkeypatch):
        prof = ModelProfile(send_temperature=False)
        a = get_provider("mistral", model="m", profile=prof)
        assert a.profile is prof and get_provider("mistral").profile is None
