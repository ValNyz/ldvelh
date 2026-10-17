"""
Comprehensive tests for llm_providers.py, cost tracking and the usage ledger.

All LLM calls are mocked — no real API calls are made.
Uses pytest + pytest-asyncio + unittest.mock (AsyncMock / MagicMock / patch).
"""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from services.llm_providers import (
    LLMProvider,
    LLMUsage,
    CompletionResult,
    ToolResult,
    ModelPricing,
    StructuredOutputMode,
    AnthropicProvider,
    MistralProvider,
    OpenAICompatibleProvider,
    WandbProvider,
    NebiusProvider,
    NousResearchProvider,
    get_provider,
    get_provider_catalog,
    _CLASSES,
    _providers,
)
from llm.session import LLMSession
from llm.usage import UsageLedger, call_cost, cost_from_stored


# =============================================================================
# HELPERS
# =============================================================================


def _make_usage(inp=100, out=50, cache_write=0, cache_read=0):
    """Build an LLMUsage with short args."""
    return LLMUsage(
        input_tokens=inp,
        output_tokens=out,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
    )


def _mock_provider(name="anthropic", model="claude-sonnet-4-6"):
    """Build a fully mocked LLMProvider with sane defaults."""
    provider = MagicMock(spec=LLMProvider)
    provider.provider_name = name
    provider.supports_cache_control = (name == "anthropic")
    provider.MODEL_MAIN = model
    provider.model_name.return_value = model
    # Default to TOOL_USE for anthropic, TEXT for others
    if name == "anthropic":
        provider.structured_output_mode = StructuredOutputMode.TOOL_USE
    else:
        provider.structured_output_mode = StructuredOutputMode.TEXT
    return provider


SAMPLE_GAME_ID = UUID("00000000-0000-0000-0000-000000000001")


# =============================================================================
# SECTION 1: LLM PROVIDERS
# =============================================================================


class TestLLMUsageAndDataclasses:
    """Basic dataclass sanity checks."""

    def test_llm_usage_defaults(self):
        u = LLMUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.cache_creation_input_tokens == 0
        assert u.cache_read_input_tokens == 0

    def test_completion_result(self):
        r = CompletionResult(content="hello", usage=_make_usage())
        assert r.content == "hello"
        assert r.usage.input_tokens == 100

    def test_tool_result(self):
        r = ToolResult(
            tool_name="extract",
            tool_input={"key": "value"},
            usage=_make_usage(),
        )
        assert r.tool_name == "extract"
        assert r.tool_input["key"] == "value"

    def test_model_pricing_defaults(self):
        p = ModelPricing()
        assert p.input == 0.0 and p.output == 0.0
        assert p.cache_write == 0.0 and p.cache_read == 0.0


class TestPricingLookup:
    """Tests for the central pricing module (services.pricing)."""

    def test_unknown_model_returns_zero_pricing(self):
        from services.pricing import lookup_pricing
        p = lookup_pricing("this-model-does-not-exist", provider="some-provider")
        assert p.input == 0.0
        assert p.output == 0.0

    def test_empty_model_returns_zero_pricing(self):
        from services.pricing import lookup_pricing
        p = lookup_pricing("")
        assert p.input == 0.0

    def test_anthropic_claude_sonnet_priced(self):
        """A model known to be in the vendored litellm file must resolve."""
        from services.pricing import lookup_pricing, is_loaded
        if not is_loaded():
            pytest.skip("pricing file not vendored")
        p = lookup_pricing("claude-sonnet-4-6")
        assert p.input > 0
        assert p.output > p.input  # output is always pricier than input

    def test_mistral_prefix_fallback(self):
        """litellm uses 'mistral/<model>' keys; lookup tries the prefix."""
        from services.pricing import lookup_pricing, is_loaded
        if not is_loaded():
            pytest.skip("pricing file not vendored")
        # mistral-large-latest is keyed as "mistral/mistral-large-latest" in litellm
        p = lookup_pricing("mistral-large-latest", provider="mistral")
        assert p.input > 0

    def test_cache_rates_loaded_when_present(self):
        """Anthropic models expose cache_read pricing in the litellm file."""
        from services.pricing import lookup_pricing, is_loaded
        if not is_loaded():
            pytest.skip("pricing file not vendored")
        p = lookup_pricing("claude-sonnet-4-6")
        # Cache reads should be cheaper than full input
        assert 0 < p.cache_read < p.input

    def test_wandb_prices_match_official_pricing(self):
        """wandb entries are hand-curated to match W&B's official pricing
        (https://wandb.ai/site/inference). litellm's upstream data was
        10x off for these models; the JSON has been corrected manually."""
        from services.pricing import lookup_pricing, is_loaded
        if not is_loaded():
            pytest.skip("pricing file not vendored")
        # Spot-check a few representative models against W&B's published rates
        p = lookup_pricing("deepseek-ai/DeepSeek-V3.1", provider="wandb")
        assert p.input == pytest.approx(0.55)
        assert p.output == pytest.approx(1.65)

        p = lookup_pricing("Qwen/Qwen3-Coder-480B-A35B-Instruct", provider="wandb")
        assert p.input == pytest.approx(1.0)
        assert p.output == pytest.approx(1.5)

        p = lookup_pricing("openai/gpt-oss-20b", provider="wandb")
        assert p.input == pytest.approx(0.05)
        assert p.output == pytest.approx(0.20)

    def test_wandb_new_models_present(self):
        """Models added manually (not in upstream litellm) must resolve."""
        from services.pricing import lookup_pricing, is_loaded
        if not is_loaded():
            pytest.skip("pricing file not vendored")
        p = lookup_pricing("deepseek-ai/DeepSeek-V4-Pro", provider="wandb")
        assert p.input == pytest.approx(1.74)
        assert p.output == pytest.approx(3.48)

        p = lookup_pricing("moonshotai/Kimi-K2.6", provider="wandb")
        assert p.input == pytest.approx(0.95)
        assert p.output == pytest.approx(4.0)

    def test_normalize_rate_per_token_multiplied(self):
        """Values below the per-token ceiling are multiplied by 1M."""
        from services.pricing import _normalize_rate
        assert _normalize_rate(0.000003) == pytest.approx(3.0)  # frontier rate

    def test_normalize_rate_per_million_passthrough(self):
        """Safety net: values above the per-token ceiling are assumed to
        already be per-million (defends against other providers with the
        same data-shape mistake)."""
        from services.pricing import _normalize_rate
        assert _normalize_rate(3.0) == 3.0  # already per-million

    def test_normalize_rate_none_and_zero(self):
        from services.pricing import _normalize_rate
        assert _normalize_rate(None) == 0.0
        assert _normalize_rate(0) == 0.0


class TestProviderRegistry:
    """Tests for get_provider, get_provider_catalog, _CLASSES."""

    def setup_method(self):
        # Clear cached providers to avoid cross-test leakage
        _providers.clear()

    def test_known_providers_registered(self):
        assert "anthropic" in _CLASSES
        assert "mistral" in _CLASSES
        assert "wandb" in _CLASSES
        assert "nebius" in _CLASSES
        assert "nous" in _CLASSES

    @patch("services.llm_providers.get_settings")
    def test_get_provider_anthropic(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="test-key")
        p = get_provider("anthropic")
        assert isinstance(p, AnthropicProvider)
        assert p.provider_name == "anthropic"

    @patch("services.llm_providers.get_settings")
    def test_get_provider_caches_singleton(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="test-key")
        p1 = get_provider("anthropic")
        p2 = get_provider("anthropic")
        assert p1 is p2  # Same instance

    @patch("services.llm_providers.get_settings")
    def test_get_provider_with_api_key_creates_fresh(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="server-key")
        p1 = get_provider("anthropic")
        p2 = get_provider("anthropic", api_key="user-key")
        assert p1 is not p2  # Fresh instance for user key

    def test_get_provider_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider("nonexistent")

    def test_get_provider_catalog_shape(self):
        catalog = get_provider_catalog()
        assert "providers" in catalog
        for name in ["anthropic", "mistral", "wandb", "nebius", "nous"]:
            assert name in catalog["providers"]
            entry = catalog["providers"][name]
            assert "models" in entry
            assert "default_model" in entry
            assert isinstance(entry["models"], list)
        # Anthropic is the only provider with a hardcoded MODELS dict (no live
        # discovery endpoint); the others fetch their model list at runtime.
        assert len(catalog["providers"]["anthropic"]["models"]) > 0


class TestProviderCatalogAsync:
    """Tests for get_provider_catalog_async (live model fetch + pricing filter)."""

    def setup_method(self):
        # Clear the model-list cache between tests
        from services.llm_providers import _MODEL_CACHE
        _MODEL_CACHE.clear()

    @pytest.mark.asyncio
    async def test_no_user_keys_returns_anthropic_models_others_empty(self):
        from services.llm_providers import get_provider_catalog_async
        result = await get_provider_catalog_async(user_keys=None)
        assert "providers" in result
        # Anthropic: hardcoded list, enriched with pricing
        anthropic_models = result["providers"]["anthropic"]["models"]
        assert len(anthropic_models) > 0
        for m in anthropic_models:
            assert "id" in m and "input_price" in m and "output_price" in m
            assert m["input_price"] > 0
        # Others: empty without a key
        for name in ["mistral", "wandb", "nebius", "nous"]:
            assert result["providers"][name]["models"] == []

    @pytest.mark.asyncio
    @patch("services.llm_providers.get_settings")
    async def test_unpriced_models_filtered_out(self, mock_settings):
        """Models with no entry in the pricing table are dropped from the response."""
        from services.llm_providers import get_provider_catalog_async, MistralProvider
        from unittest.mock import AsyncMock

        mock_settings.return_value = MagicMock(mistral_api_key="key")

        # Mock the provider's list_models to return a known model + a fake one
        with patch.object(
            MistralProvider, "list_models",
            new=AsyncMock(return_value=[
                {"id": "mistral-large-latest", "label": "mistral-large-latest"},
                {"id": "completely-fake-model-id-not-in-pricing", "label": "fake"},
            ]),
        ):
            result = await get_provider_catalog_async(
                user_keys={"mistral": "fake-key"},
            )

        mistral_models = result["providers"]["mistral"]["models"]
        ids = {m["id"] for m in mistral_models}
        # The fake model is dropped (no pricing entry)
        assert "completely-fake-model-id-not-in-pricing" not in ids
        # mistral-large-latest IS in litellm's table (as mistral/mistral-large-latest)
        assert "mistral-large-latest" in ids

    @pytest.mark.asyncio
    @patch("services.llm_providers.get_settings")
    async def test_cache_hit_skips_second_fetch(self, mock_settings):
        """A second call within TTL doesn't re-hit the provider API."""
        from services.llm_providers import get_provider_catalog_async, MistralProvider
        from unittest.mock import AsyncMock

        mock_settings.return_value = MagicMock(mistral_api_key="key")

        fetch_mock = AsyncMock(return_value=[
            {"id": "mistral-large-latest", "label": "mistral-large-latest"},
        ])
        with patch.object(MistralProvider, "list_models", new=fetch_mock):
            await get_provider_catalog_async(user_keys={"mistral": "key1"})
            await get_provider_catalog_async(user_keys={"mistral": "key1"})

        # Same key, two calls -> list_models invoked only once
        assert fetch_mock.call_count == 1

    @pytest.mark.asyncio
    @patch("services.llm_providers.get_settings")
    async def test_provider_failure_returns_empty_list(self, mock_settings):
        """If the live fetch errors, the catalog still returns a (empty) entry."""
        from services.llm_providers import get_provider_catalog_async, MistralProvider
        from unittest.mock import AsyncMock

        mock_settings.return_value = MagicMock(mistral_api_key="key")

        with patch.object(
            MistralProvider, "list_models",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ):
            result = await get_provider_catalog_async(
                user_keys={"mistral": "bad-key"},
            )
        assert result["providers"]["mistral"]["models"] == []


class TestAnthropicProvider:
    """Tests for AnthropicProvider init, properties, pricing."""

    @patch("services.llm_providers.get_settings")
    def test_init_default_key(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="server-key")
        p = AnthropicProvider()
        assert p.provider_name == "anthropic"
        assert p.supports_cache_control is True
        assert p.MODEL_MAIN == "claude-sonnet-5-5"

    @patch("services.llm_providers.get_settings")
    def test_init_custom_model(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="key")
        p = AnthropicProvider(model="claude-haiku-5-5")
        assert p.MODEL_MAIN == "claude-haiku-5-5"

    @patch("services.llm_providers.get_settings")
    def test_init_unknown_model_ignored(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="key")
        p = AnthropicProvider(model="nonexistent-model")
        assert p.MODEL_MAIN == "claude-sonnet-5-5"  # Unchanged

    @patch("services.llm_providers.get_settings")
    def test_model_name_returns_main(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="key")
        p = AnthropicProvider()
        assert p.model_name("narration") == "claude-sonnet-5-5"
        assert p.model_name("extraction") == "claude-sonnet-5-5"


class TestMistralProvider:
    """Tests for MistralProvider init, properties, pricing."""

    @patch("services.llm_providers.get_settings")
    def test_init_and_properties(self, mock_settings):
        mock_settings.return_value = MagicMock(mistral_api_key="key")
        p = MistralProvider()
        assert p.provider_name == "mistral"
        assert p.supports_cache_control is False
        assert p.MODEL_MAIN == "mistral-large-latest"

class TestOpenAICompatibleProviders:
    """Tests for WandbProvider, NebiusProvider, NousResearchProvider."""

    @patch("services.llm_providers.get_settings")
    def test_wandb_provider(self, mock_settings):
        mock_settings.return_value = MagicMock(wandb_api_key="key")
        p = WandbProvider()
        assert p.provider_name == "wandb"
        assert p.supports_cache_control is False
        assert "Qwen" in p.MODEL_MAIN

    @patch("services.llm_providers.get_settings")
    def test_nebius_provider(self, mock_settings):
        mock_settings.return_value = MagicMock(nebius_api_key="key")
        p = NebiusProvider()
        assert p.provider_name == "nebius"

    @patch("services.llm_providers.get_settings")
    def test_nous_provider(self, mock_settings):
        mock_settings.return_value = MagicMock(nous_api_key="key")
        p = NousResearchProvider()
        assert p.provider_name == "nous"
        assert p.MODEL_MAIN == "Hermes-4-405B"

    @patch("services.llm_providers.get_settings")
    def test_nous_custom_model(self, mock_settings):
        mock_settings.return_value = MagicMock(nous_api_key="key")
        p = NousResearchProvider(model="Hermes-4-70B")
        assert p.MODEL_MAIN == "Hermes-4-70B"

    @pytest.mark.asyncio
    async def test_base_complete_with_tools_raises(self):
        """OpenAICompatibleProvider.complete_with_tools raises NotImplementedError."""
        provider = MagicMock(spec=OpenAICompatibleProvider)
        provider.provider_name = "openai_compatible"
        # Call the real base class method (async)
        with pytest.raises(NotImplementedError):
            await LLMProvider.complete_with_tools(
                provider,
                system_prompt="sys",
                messages=[],
                tools=[],
                tool_choice={},
                temperature=0.5,
                max_tokens=100,
            )


# =============================================================================
# SECTION 2: COST TRACKING
# =============================================================================


class TestComputeCost:
    """Tests for call_cost and cost_from_stored."""

    def test_compute_cost_basic(self):
        usage = _make_usage(inp=1000, out=500)
        cost = call_cost(usage, "anthropic", "claude-sonnet-4-6")
        # (1000 * 3.0 + 500 * 15.0) / 1_000_000 = (3000 + 7500) / 1_000_000 = 0.0105
        assert abs(cost - 0.0105) < 1e-9

    def test_compute_cost_with_cache(self):
        usage = LLMUsage(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_input_tokens=200,
            cache_read_input_tokens=300,
        )
        cost = call_cost(usage, "anthropic", "claude-sonnet-4-6")
        expected = (
            1000 * 3.0 + 500 * 15.0 + 200 * 3.75 + 300 * 0.30
        ) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_cost_from_stored(self):
        result = cost_from_stored({
            "input_tokens": 2000,
            "output_tokens": 1000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
        })
        expected = (2000 * 3.0 + 1000 * 15.0) / 1_000_000
        assert abs(result - round(expected, 6)) < 1e-9


class TestUsageLedger:
    """Tests for UsageLedger.record and UsageLedger.get_summary."""

    def test_record_returns_snapshot(self):
        tracker = UsageLedger()
        usage = _make_usage(inp=1000, out=500)
        snapshot = tracker.record("narration", "anthropic", "claude-sonnet-4-6", usage)
        assert "cost_usd" in snapshot
        assert snapshot["input_tokens"] == 1000
        assert snapshot["output_tokens"] == 500
        assert snapshot["model"] == "claude-sonnet-4-6"
        assert snapshot["provider"] == "anthropic"

    def test_record_accumulates(self):
        tracker = UsageLedger()
        usage = _make_usage(inp=100, out=50)
        tracker.record("narration", "anthropic", "claude-sonnet-4-6", usage)
        tracker.record("narration", "anthropic", "claude-sonnet-4-6", usage)

        accumulated = tracker._totals[("narration", "anthropic", "claude-sonnet-4-6")]
        assert accumulated.input_tokens == 200
        assert accumulated.output_tokens == 100
        assert accumulated.calls == 2

    def test_get_summary_empty(self):
        tracker = UsageLedger()
        summary = tracker.get_summary()
        assert summary["total_cost_usd"] == 0.0
        assert summary["purposes"] == {}

    def test_get_summary_grouped_by_purpose(self):
        tracker = UsageLedger()
        tracker.record("narration", "anthropic", "claude-sonnet-4-6", _make_usage(inp=1000, out=500))
        tracker.record("extraction", "anthropic", "claude-sonnet-4-6", _make_usage(inp=500, out=200))

        summary = tracker.get_summary()
        assert "narration" in summary["purposes"]
        assert "extraction" in summary["purposes"]
        assert summary["purposes"]["narration"]["calls"] == 1
        assert summary["purposes"]["extraction"]["calls"] == 1
        assert summary["total_cost_usd"] > 0

    def test_get_summary_detects_mistral_model(self):
        """Mistral calls are priced via the mistral entry."""
        tracker = UsageLedger()
        tracker.record("narration", "mistral", "mistral-large-latest", _make_usage(inp=100, out=50))
        summary = tracker.get_summary()
        assert "narration" in summary["purposes"]
        assert "total_cost_usd" in summary


# Section 3 (LLMService) removed: narration streaming is tested in tests/pipeline/.
# Section 4 (old batch extraction) removed — replaced by services/extraction/ package.
# See test_extraction_service.py for new extraction tests.
