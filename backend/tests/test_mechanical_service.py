"""Mechanical step: per-provider model selection and failure signalling (#10)."""

import pytest

from services.engine import get_engine
from services.engine.mechanical_service import MechanicalStepUnavailable, run_mechanical_step
from llm.session import LLMSession
from tests.helpers import RecordingLedger
from tests.test_llm_session import FakeProvider
from services.llm_providers import AnthropicProvider, MistralProvider, get_provider


class TestMechanicalModelName:
    def test_anthropic_uses_haiku_for_mechanical(self):
        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5-5")
        assert provider.model_name("mechanical") == "claude-haiku-5-5"
        assert provider.model_name("narration") == "claude-sonnet-5-5"

    def test_other_providers_fall_back_to_main_model(self):
        provider = MistralProvider(api_key="k", model="mistral-small-latest")
        assert provider.model_name("mechanical") == "mistral-small-latest"

    def test_no_provider_gets_an_anthropic_id_for_mechanical(self):
        for name in ("mistral", "wandb", "nebius", "nous"):
            provider = get_provider(name, api_key="k")
            assert not provider.model_name("mechanical").startswith("claude-"), name


DECISION_JSON = '{"requires_test": false, "reason": "x"}'


class TestRunMechanicalStep:
    @pytest.mark.asyncio
    async def test_uses_mechanical_purpose_and_settings(self):
        provider = FakeProvider(text=DECISION_JSON)
        seen = {}
        original = provider.complete

        async def spy(**kwargs):
            seen.update(kwargs)
            return await original(**kwargs)

        provider.complete = spy
        ledger = RecordingLedger()
        session = LLMSession.from_provider(provider, ledger)
        await run_mechanical_step(get_engine("fate_core"), {}, "Je force la porte", "", "moderate", session)
        assert (seen["max_tokens"], seen["temperature"]) == (500, 0.2)
        assert ledger.purposes == ["mechanical"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("requires_test", [False, True])
    async def test_arbiter_reason_is_not_logged_at_info(self, caplog, requires_test):
        reason = "Le chevalier hésite devant le dragon de verre."
        text = ('{"requires_test": %s, "skill": "Athlétisme", "skill_value": 2, "difficulty": 2, '
                '"difficulty_label": "Correct", "reason": "%s"}'
                % (str(requires_test).lower(), reason))
        session = LLMSession.from_provider(FakeProvider(text=text))
        with caplog.at_level("DEBUG"):
            await run_mechanical_step(get_engine("fate_core"), {}, "Je force", "", "moderate", session)
        assert not any(reason in r.getMessage() for r in caplog.records if r.levelno >= 20)
        assert any(reason in r.getMessage() for r in caplog.records if r.levelno == 10)

    @pytest.mark.asyncio
    async def test_failed_call_raises_unavailable(self):
        session = LLMSession.from_provider(FakeProvider(fail=RuntimeError("down")))
        with pytest.raises(MechanicalStepUnavailable):
            await run_mechanical_step(get_engine("fate_core"), {}, "x", "", "moderate", session)

    @pytest.mark.asyncio
    async def test_engine_without_mechanical_step_returns_none(self):
        provider = FakeProvider()
        assert await run_mechanical_step(get_engine("narrative"), {}, "x", "", "moderate",
                                         LLMSession.from_provider(provider)) is None
        assert provider.calls == []
