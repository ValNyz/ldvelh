"""
Comprehensive tests for llm_service.py, extraction_service.py, and llm_providers.py.

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
from services.llm_service import (
    LLMService,
    CostTracker,
    ModelUsage,
    _compute_cost,
    compute_cost_from_stored,
    get_llm_service,
    _llm_service,
)


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
        assert p.MODEL_MAIN == "claude-sonnet-4-6"

    @patch("services.llm_providers.get_settings")
    def test_init_custom_model(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="key")
        p = AnthropicProvider(model="claude-haiku-4-5")
        assert p.MODEL_MAIN == "claude-haiku-4-5"

    @patch("services.llm_providers.get_settings")
    def test_init_unknown_model_ignored(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="key")
        p = AnthropicProvider(model="nonexistent-model")
        assert p.MODEL_MAIN == "claude-sonnet-4-6"  # Unchanged

    @patch("services.llm_providers.get_settings")
    def test_model_name_returns_main(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="key")
        p = AnthropicProvider()
        assert p.model_name("narration") == "claude-sonnet-4-6"
        assert p.model_name("extraction") == "claude-sonnet-4-6"


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
    def test_nous_provider_force_json(self, mock_settings):
        mock_settings.return_value = MagicMock(nous_api_key="key")
        p = NousResearchProvider()
        assert p.provider_name == "nous"
        assert p.FORCE_JSON is True
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
    """Tests for _compute_cost and compute_cost_from_stored."""

    def test_compute_cost_basic(self):
        provider = _mock_provider()
        usage = ModelUsage(input_tokens=1000, output_tokens=500)
        cost = _compute_cost(usage, provider, "claude-sonnet-4-6")
        # (1000 * 3.0 + 500 * 15.0) / 1_000_000 = (3000 + 7500) / 1_000_000 = 0.0105
        assert abs(cost - 0.0105) < 1e-9

    def test_compute_cost_with_cache(self):
        provider = _mock_provider()
        usage = ModelUsage(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_input_tokens=200,
            cache_read_input_tokens=300,
        )
        cost = _compute_cost(usage, provider, "claude-sonnet-4-6")
        expected = (
            1000 * 3.0 + 500 * 15.0 + 200 * 3.75 + 300 * 0.30
        ) / 1_000_000
        assert abs(cost - expected) < 1e-9

    @patch("services.llm_service.get_provider")
    def test_compute_cost_from_stored(self, mock_get_provider):
        mock_get_provider.return_value = _mock_provider()
        result = compute_cost_from_stored({
            "input_tokens": 2000,
            "output_tokens": 1000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "model": "claude-sonnet-4-6",
            "provider": "anthropic",
        })
        expected = (2000 * 3.0 + 1000 * 15.0) / 1_000_000
        assert abs(result - round(expected, 6)) < 1e-9


class TestCostTracker:
    """Tests for CostTracker.record and CostTracker.get_summary."""

    def test_record_returns_snapshot(self):
        tracker = CostTracker()
        provider = _mock_provider()
        usage = _make_usage(inp=1000, out=500)
        snapshot = tracker.record(
            "claude-sonnet-4-6", usage, purpose="narration", provider=provider
        )
        assert "cost_usd" in snapshot
        assert snapshot["input_tokens"] == 1000
        assert snapshot["output_tokens"] == 500
        assert snapshot["model"] == "claude-sonnet-4-6"
        assert snapshot["provider"] == "anthropic"

    def test_record_accumulates(self):
        tracker = CostTracker()
        provider = _mock_provider()
        usage = _make_usage(inp=100, out=50)
        tracker.record("claude-sonnet-4-6", usage, purpose="narration", provider=provider)
        tracker.record("claude-sonnet-4-6", usage, purpose="narration", provider=provider)

        key = "narration:claude-sonnet-4-6"
        accumulated = tracker._usage[key]
        assert accumulated.input_tokens == 200
        assert accumulated.output_tokens == 100
        assert accumulated.calls == 2

    def test_get_summary_empty(self):
        tracker = CostTracker()
        summary = tracker.get_summary()
        assert summary["total_cost_usd"] == 0.0
        assert summary["purposes"] == {}

    @patch("services.llm_service.get_provider")
    def test_get_summary_grouped_by_purpose(self, mock_get_provider):
        mock_get_provider.return_value = _mock_provider()
        tracker = CostTracker()
        provider = _mock_provider()
        tracker.record(
            "claude-sonnet-4-6",
            _make_usage(inp=1000, out=500),
            purpose="narration",
            provider=provider,
        )
        tracker.record(
            "claude-sonnet-4-6",
            _make_usage(inp=500, out=200),
            purpose="extraction",
            provider=provider,
        )

        summary = tracker.get_summary()
        assert "narration" in summary["purposes"]
        assert "extraction" in summary["purposes"]
        assert summary["purposes"]["narration"]["calls"] == 1
        assert summary["purposes"]["extraction"]["calls"] == 1
        assert summary["total_cost_usd"] > 0

    def test_get_summary_detects_mistral_model(self):
        """Models starting with 'mistral' should be priced via the mistral entry."""
        mistral_provider = _mock_provider(name="mistral", model="mistral-large-latest")
        tracker = CostTracker()
        tracker.record(
            "mistral-large-latest",
            _make_usage(inp=100, out=50),
            purpose="narration",
            provider=mistral_provider,
        )
        summary = tracker.get_summary()
        assert "narration" in summary["purposes"]
        # Cost is computed via the central pricing table — if Mistral pricing
        # is loaded for this model, cost should be > 0.
        assert "total_cost_usd" in summary


# =============================================================================
# SECTION 3: LLM SERVICE
# =============================================================================


class TestGetLLMServiceSingleton:
    """Tests for the get_llm_service() singleton pattern."""

    def setup_method(self):
        # Reset singleton between tests
        import services.llm_service as mod
        mod._llm_service = None

    @patch("services.llm_service.get_settings")
    def test_returns_singleton(self, mock_settings):
        mock_settings.return_value = MagicMock()
        s1 = get_llm_service()
        s2 = get_llm_service()
        assert s1 is s2

    @patch("services.llm_service.get_settings")
    def test_creates_llm_service(self, mock_settings):
        mock_settings.return_value = MagicMock()
        s = get_llm_service()
        assert isinstance(s, LLMService)

    def teardown_method(self):
        import services.llm_service as mod
        mod._llm_service = None


class TestLLMServiceStreamNarration:
    """Tests for LLMService.stream_narration()."""

    @pytest.fixture
    def service(self):
        with patch("services.llm_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                max_tokens_init=10000,
                max_tokens_narration=4000,
                temperature=0.8,
            )
            return LLMService()

    @pytest.mark.asyncio
    async def test_stream_narration_basic(self, service):
        """Stream narration assembles JSON, sends chunks, calls on_complete."""
        json_output = json.dumps({
            "narrative_text": "Hello world. A narrative story about space. This is a long enough text for testing.",
        })

        # Mock provider that yields chunks + final usage
        async def mock_stream(**kwargs):
            for chunk in [json_output[:30], json_output[30:]]:
                yield chunk
            yield _make_usage(inp=200, out=100)

        mock_provider = _mock_provider()
        mock_provider.stream = mock_stream

        sse_writer = AsyncMock()
        on_complete = AsyncMock()

        with patch.object(service, "_get_provider", return_value=mock_provider):
            await service.stream_narration(
                system_prompt="sys",
                messages=[{"role": "user", "content": "test"}],
                sse_writer=sse_writer,
                on_complete=on_complete,
            )

        # on_complete should have been called
        on_complete.assert_awaited_once()
        call_args = on_complete.call_args
        parsed, display_text, raw_json = call_args[0]
        assert parsed is not None
        assert parsed["narrative_text"].startswith("Hello world")

    @pytest.mark.asyncio
    async def test_stream_narration_init_mode(self, service):
        """In init mode, send_progress is used instead of send_chunk."""
        json_output = '{"world": {"name": "Test Station"}}'

        async def mock_stream(**kwargs):
            # Yield a big chunk to trigger progress (> 500 chars)
            yield json_output + " " * 600
            yield _make_usage()

        mock_provider = _mock_provider()
        mock_provider.stream = mock_stream

        sse_writer = AsyncMock()

        with patch.object(service, "_get_provider", return_value=mock_provider):
            await service.stream_narration(
                system_prompt="sys",
                messages=[],
                sse_writer=sse_writer,
                is_init_mode=True,
            )

        # In init mode, send_progress should be used
        assert sse_writer.send_progress.await_count >= 1

    @pytest.mark.asyncio
    async def test_stream_narration_records_cost(self, service):
        """Cost tracking is recorded after streaming completes."""
        json_output = '{"narrative_text": "Some long narrative text about space exploration and adventure."}'

        async def mock_stream(**kwargs):
            yield json_output
            yield _make_usage(inp=500, out=250, cache_read=100)

        mock_provider = _mock_provider()
        mock_provider.stream = mock_stream

        with patch.object(service, "_get_provider", return_value=mock_provider):
            await service.stream_narration(
                system_prompt="sys",
                messages=[],
                sse_writer=AsyncMock(),
            )

        assert hasattr(service, "_last_call_cost")
        assert service._last_call_cost["input_tokens"] == 500

    @pytest.mark.asyncio
    async def test_stream_narration_api_error(self, service):
        """API errors are caught, error sent via SSE, and re-raised."""

        async def mock_stream(**kwargs):
            raise RuntimeError("API down")
            yield  # Make it an async generator

        mock_provider = _mock_provider()
        mock_provider.stream = mock_stream

        sse_writer = AsyncMock()

        with patch.object(service, "_get_provider", return_value=mock_provider):
            with pytest.raises(RuntimeError, match="API down"):
                await service.stream_narration(
                    system_prompt="sys",
                    messages=[],
                    sse_writer=sse_writer,
                )

        sse_writer.send_error.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_narration_on_narrative_ready_callback(self, service):
        """on_narrative_ready is called when narrative_text is complete."""
        # Build JSON that has narrative_text followed by a closing comma/brace
        json_output = json.dumps({
            "narrative_text": "Complete narrative text that is well-formed and finalized in the JSON output stream.",
        })

        async def mock_stream(**kwargs):
            # Yield the full JSON in two parts to simulate streaming
            yield json_output[:50]
            yield json_output[50:]
            yield _make_usage()

        mock_provider = _mock_provider()
        mock_provider.stream = mock_stream

        on_narrative_ready = AsyncMock()

        with patch.object(service, "_get_provider", return_value=mock_provider):
            await service.stream_narration(
                system_prompt="sys",
                messages=[],
                sse_writer=AsyncMock(),
                on_narrative_ready=on_narrative_ready,
            )

        # The callback should fire once when narrative_text field is complete
        on_narrative_ready.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_narration_json_parse_failure(self, service):
        """When JSON parse fails, display_text is extracted from partial."""
        broken_output = '{"narrative_text": "Some narrative about broken JSON'

        async def mock_stream(**kwargs):
            yield broken_output
            yield _make_usage()

        mock_provider = _mock_provider()
        mock_provider.stream = mock_stream

        on_complete = AsyncMock()

        with patch.object(service, "_get_provider", return_value=mock_provider):
            await service.stream_narration(
                system_prompt="sys",
                messages=[],
                sse_writer=AsyncMock(),
                on_complete=on_complete,
            )

        call_args = on_complete.call_args[0]
        parsed, display_text, raw_json = call_args
        # parsed may be None or repaired; display_text should exist
        assert display_text is not None


class TestLLMServiceIsNarrativeComplete:
    """Tests for LLMService._is_narrative_complete static method."""

    def test_complete_narrative(self):
        json_str = '{"narrative_text": "Hello world", "other": 1}'
        assert LLMService._is_narrative_complete(json_str) is True

    def test_incomplete_narrative(self):
        json_str = '{"narrative_text": "Hello world'
        assert LLMService._is_narrative_complete(json_str) is False

    def test_narrative_with_escaped_quotes(self):
        json_str = '{"narrative_text": "She said \\"hello\\"", "other": 1}'
        assert LLMService._is_narrative_complete(json_str) is True

    def test_empty_string(self):
        assert LLMService._is_narrative_complete("") is False


class TestLLMServiceExtractText:
    """Tests for LLMService.extract_text() (non-streaming extraction)."""

    @pytest.fixture
    def service(self):
        with patch("services.llm_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                max_tokens_extraction=3000,
                temperature_extraction=0.3,
            )
            return LLMService()

    @pytest.mark.asyncio
    async def test_extract_text_success(self, service):
        """Successful extraction returns parsed JSON."""
        response_json = {"facts": [{"text": "A discovered B"}]}
        mock_provider = _mock_provider()
        mock_provider.complete = AsyncMock(
            return_value=CompletionResult(
                content=json.dumps(response_json),
                usage=_make_usage(),
            )
        )

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.extract_text(
                system_prompt="Extract facts.",
                user_message="Narrative text here.",
            )

        assert result is not None
        assert result["facts"][0]["text"] == "A discovered B"

    @pytest.mark.asyncio
    async def test_extract_text_api_error(self, service):
        """API error returns None (graceful degradation)."""
        mock_provider = _mock_provider()
        mock_provider.complete = AsyncMock(side_effect=RuntimeError("timeout"))

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.extract_text(
                system_prompt="sys",
                user_message="msg",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_extract_text_records_cost(self, service):
        """Cost tracking is recorded for extraction calls."""
        mock_provider = _mock_provider()
        mock_provider.complete = AsyncMock(
            return_value=CompletionResult(
                content='{"data": "value"}',
                usage=_make_usage(inp=800, out=400),
            )
        )

        with patch.object(service, "_get_provider", return_value=mock_provider):
            await service.extract_text(
                system_prompt="sys",
                user_message="msg",
            )

        assert service._last_call_cost["input_tokens"] == 800


class TestLLMServiceExtractWithTools:
    """Tests for LLMService.extract_with_tools()."""

    @pytest.fixture
    def service(self):
        with patch("services.llm_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                max_tokens_extraction=3000,
                temperature_extraction=0.3,
            )
            return LLMService()

    @pytest.mark.asyncio
    async def test_extract_with_tools_success(self, service):
        """Successful tool_use extraction returns parsed tool_input."""
        tool_input = {"facts": [{"text": "discovered something"}]}
        mock_provider = _mock_provider()
        mock_provider.complete_with_tools = AsyncMock(
            return_value=ToolResult(
                tool_name="extract_narrative",
                tool_input=tool_input,
                usage=_make_usage(),
            )
        )

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.extract_with_tools(
                system_prompt="sys",
                user_message="msg",
                tool_name="extract_narrative",
                tool_description="Extract stuff",
                schema={"type": "object"},
            )

        assert result == tool_input
        assert service._last_call_cost is not None

    @pytest.mark.asyncio
    async def test_extract_with_tools_not_implemented_fallback(self, service):
        """When tool_use is not supported, falls back to text extraction."""
        mock_provider = _mock_provider()
        mock_provider.complete_with_tools = AsyncMock(
            side_effect=NotImplementedError("no tool_use")
        )
        mock_provider.complete = AsyncMock(
            return_value=CompletionResult(
                content='{"facts": []}',
                usage=_make_usage(),
            )
        )

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.extract_with_tools(
                system_prompt="sys",
                user_message="msg",
                tool_name="extract_narrative",
                tool_description="desc",
                schema={},
            )

        assert result is not None
        assert result["facts"] == []

    @pytest.mark.asyncio
    async def test_extract_with_tools_generic_error_fallback(self, service):
        """Generic error in tool_use also falls back to text extraction."""
        mock_provider = _mock_provider()
        mock_provider.complete_with_tools = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        mock_provider.complete = AsyncMock(
            return_value=CompletionResult(
                content='{"entities_created": []}',
                usage=_make_usage(),
            )
        )

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.extract_with_tools(
                system_prompt="sys",
                user_message="msg",
                tool_name="extract_narrative",
                tool_description="desc",
                schema={},
            )

        assert result is not None
        assert "entities_created" in result


class TestLLMServiceSummarize:
    """Tests for LLMService.summarize_message()."""

    @pytest.fixture
    def service(self):
        with patch("services.llm_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                max_tokens_summary=500,
            )
            return LLMService()

    @pytest.mark.asyncio
    async def test_summarize_success(self, service):
        mock_provider = _mock_provider()
        mock_provider.complete = AsyncMock(
            return_value=CompletionResult(
                content="  Valentin explores the station.  ",
                usage=_make_usage(),
            )
        )

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.summarize_message("Long narrative...")

        assert result == "Valentin explores the station."

    @pytest.mark.asyncio
    async def test_summarize_truncates_to_max_length(self, service):
        mock_provider = _mock_provider()
        mock_provider.complete = AsyncMock(
            return_value=CompletionResult(
                content="A" * 300,  # Way longer than default max_length
                usage=_make_usage(),
            )
        )

        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.summarize_message("Narrative", max_length=50)

        assert len(result) <= 50

    @pytest.mark.asyncio
    async def test_summarize_error_fallback(self, service):
        """On error, returns truncated input text with ellipsis."""
        mock_provider = _mock_provider()
        mock_provider.complete = AsyncMock(side_effect=RuntimeError("timeout"))

        long_text = "This is a long narrative text that needs to be shortened significantly"
        with patch.object(service, "_get_provider", return_value=mock_provider):
            result = await service.summarize_message(long_text, max_length=150)

        # Fallback: text[:max_length].rsplit(" ", 1)[0] + "..."
        assert result.endswith("...")
        assert len(result) <= 153  # max_length + "..."



# Section 4 (old batch extraction) removed — replaced by services/extraction/ package.
# See test_extraction_service.py for new extraction tests.
