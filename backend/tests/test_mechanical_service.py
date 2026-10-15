"""Mechanical step: per-provider model selection and failure signalling (#10)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.engine import get_engine
from services.engine.mechanical_service import MechanicalStepUnavailable, run_mechanical_step
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


def _llm_service(parsed):
    service = MagicMock()
    service.extract_text = AsyncMock(return_value=parsed)
    service._last_call_cost = None
    return service


DECISION = {"requires_test": False, "reason": "Action triviale."}


class TestRunMechanicalStep:
    @pytest.mark.asyncio
    async def test_mistral_call_uses_mistral_model_and_mechanical_settings(self):
        service = _llm_service(DECISION)
        await run_mechanical_step(
            engine=get_engine("fate_core"), engine_stats={}, player_message="Je force la porte",
            context_summary="", world_difficulty="moderate", llm_service=service,
            provider_name="mistral", api_key="k", model="mistral-small-latest",
        )
        kwargs = service.extract_text.await_args.kwargs
        assert kwargs["model"] == "mistral-small-latest"
        assert kwargs["purpose"] == "mechanical"
        assert kwargs["max_tokens"] == 500
        assert kwargs["temperature"] == 0.2

    @pytest.mark.asyncio
    async def test_anthropic_call_still_uses_haiku(self):
        service = _llm_service(DECISION)
        await run_mechanical_step(
            engine=get_engine("d6"), engine_stats={}, player_message="Je saute",
            context_summary="", world_difficulty="moderate", llm_service=service,
            provider_name="anthropic", api_key="k", model="claude-sonnet-5-5",
        )
        assert service.extract_text.await_args.kwargs["model"] == "claude-haiku-5-5"

    @pytest.mark.asyncio
    async def test_failed_call_raises_unavailable_instead_of_silent_skip(self):
        service = _llm_service(None)
        with pytest.raises(MechanicalStepUnavailable):
            await run_mechanical_step(
                engine=get_engine("fate_core"), engine_stats={}, player_message="Je force la porte",
                context_summary="", world_difficulty="moderate", llm_service=service,
                provider_name="mistral", api_key="k",
            )

    @pytest.mark.asyncio
    async def test_engine_without_mechanical_step_returns_none(self):
        service = _llm_service(json.dumps(DECISION))
        result = await run_mechanical_step(
            engine=get_engine("narrative"), engine_stats={}, player_message="x",
            context_summary="", world_difficulty="moderate", llm_service=service,
        )
        assert result is None
        service.extract_text.assert_not_awaited()
