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
    provider.get_pricing.return_value = ModelPricing(
        input=3.0, output=15.0, cache_write=3.75, cache_read=0.30,
    )
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
            assert len(entry["models"]) > 0


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
    def test_pricing_known_model(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="key")
        p = AnthropicProvider()
        pricing = p.get_pricing("claude-sonnet-4-6")
        assert pricing.input == 3.0
        assert pricing.output == 15.0

    @patch("services.llm_providers.get_settings")
    def test_pricing_fallback(self, mock_settings):
        mock_settings.return_value = MagicMock(anthropic_api_key="key")
        p = AnthropicProvider()
        pricing = p.get_pricing("unknown-model")
        # Falls back to sonnet-4-6 pricing
        assert pricing.input == 3.0

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

    @patch("services.llm_providers.get_settings")
    def test_pricing(self, mock_settings):
        mock_settings.return_value = MagicMock(mistral_api_key="key")
        p = MistralProvider()
        pricing = p.get_pricing("mistral-large-latest")
        assert pricing.input == 0.5
        assert pricing.output == 1.5
        assert pricing.cache_write == 0.0


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
        # Different pricing than wandb
        pricing = p.get_pricing(p.MODEL_MAIN)
        assert pricing.input == 0.20

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

    @patch("services.llm_service.get_provider")
    def test_get_summary_detects_mistral_model(self, mock_get_provider):
        """Models starting with 'mistral' should use the mistral provider for pricing."""
        mistral_provider = _mock_provider(name="mistral", model="mistral-large-latest")
        mistral_provider.get_pricing.return_value = ModelPricing(input=0.5, output=1.5)
        mock_get_provider.return_value = mistral_provider

        tracker = CostTracker()
        tracker.record(
            "mistral-large-latest",
            _make_usage(inp=100, out=50),
            purpose="narration",
            provider=mistral_provider,
        )
        summary = tracker.get_summary()
        assert "narration" in summary["purposes"]
        # Pricing should come from mistral provider
        mock_get_provider.assert_called_with("mistral")


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
            "suggested_actions": ["Look around"],
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
            "suggested_actions": ["Do something"],
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


# =============================================================================
# SECTION 4: EXTRACTION SERVICE
# =============================================================================


def _mock_pool():
    """Build a mock asyncpg pool with a working acquire() context manager.

    Every call to pool.acquire() returns a fresh context manager that yields
    the *same* mock_conn, so tests can inspect calls across multiple
    ``async with pool.acquire() as conn:`` blocks.
    """
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_conn.fetchrow = AsyncMock(return_value=None)

    pool = MagicMock()

    def _new_cm():
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    pool.acquire.side_effect = lambda: _new_cm()

    return pool, mock_conn


def _make_extraction_result():
    """Build a valid raw extraction result dict matching NarrativeExtraction schema."""
    return {
        "facts": [
            {
                "description": "Valentin discovered a hidden passage in the lower deck.",
                "fact_type": "event",
                "importance": 3,
                "participants": [],
                "cycle": 3,
                "semantic_key": "valentin:discover:passage",
            }
        ],
        "entities_created": [],
        "entities_updated": [],
        "objects_created": [],
        "relations_created": [],
        "relations_updated": [],
        "arcs_created": [],
        "arcs_updated": [],
        "arcs_resolved": [],
        "events_scheduled": [],
        "ambient_updates": [],
        "segment_summary": "Valentin found a hidden passage in the lower deck.",
    }


class TestRunBatchExtraction:
    """Tests for run_batch_extraction()."""

    def setup_method(self):
        # Clear the concurrent extraction guard between tests
        from services import extraction_service
        extraction_service._extracting_games.clear()
        extraction_service._RETRY_ATTEMPTED.clear()

    @pytest.mark.asyncio
    async def test_concurrent_extraction_guard(self):
        """Second call for same game_id is rejected while first is running."""
        from services.extraction_service import (
            _extracting_games,
            run_batch_extraction,
        )

        # Pretend game is already extracting
        key = str(SAMPLE_GAME_ID)
        _extracting_games.add(key)

        pool, _ = _mock_pool()
        result = await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=3)

        assert result is None
        _extracting_games.discard(key)

    @pytest.mark.asyncio
    async def test_game_not_found(self):
        """If game doesn't exist, returns None."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(return_value=None)

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=MagicMock(),
        ):
            result = await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=3)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_unextracted_messages(self):
        """If no messages to extract, updates tracking and returns skipped."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 1}
        )
        mock_reader.get_unextracted_messages = AsyncMock(return_value=[])

        mock_populator = AsyncMock()

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=mock_populator,
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=MagicMock(),
        ):
            result = await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=3)

        assert result is not None
        assert result["skipped"] is True
        assert result["reason"] == "no_messages"
        mock_populator.update_extracted_cycle.assert_awaited_once_with(mock_conn, 3)

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        """Full happy path: messages loaded, LLM called, KG populated."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 1}
        )
        mock_reader.get_unextracted_messages = AsyncMock(
            return_value=[
                {
                    "id": uuid4(),
                    "content": "Valentin walked into the bar.",
                    "narrator_deltas": {
                        "inventory_hints": [],
                        "hints": {"new_entities_mentioned": ["Ossek"]},
                    },
                },
            ]
        )
        mock_reader.get_entities = AsyncMock(
            return_value=[{"name": "Ossek"}, {"name": "Le Quart de Cycle"}]
        )
        mock_reader.get_active_arcs = AsyncMock(
            return_value=[{"title": "Mystery of the Station"}]
        )
        mock_reader.get_stub_locations = AsyncMock(return_value=["Hangar B"])

        mock_populator = AsyncMock()

        raw_result = _make_extraction_result()
        mock_llm = MagicMock()
        mock_llm.extract_structured = AsyncMock(return_value=raw_result)
        mock_llm._last_call_cost = {
            "cost_usd": 0.005,
            "input_tokens": 1000,
            "output_tokens": 500,
        }

        mock_extraction_populator = AsyncMock()
        mock_extraction_populator.load_registry = AsyncMock()
        mock_extraction_populator.process_extraction = AsyncMock(
            return_value={"facts_created": 1}
        )
        mock_extraction_populator.save_chronology_entry = AsyncMock()

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=mock_populator,
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=mock_llm,
        ), patch(
            "services.extraction_service.ExtractionPopulator",
            return_value=mock_extraction_populator,
        ):
            result = await run_batch_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=3
            )

        assert result is not None
        assert result["success"] is True
        assert "stats" in result
        assert "duration_ms" in result

        # Verify LLM was called
        mock_llm.extract_structured.assert_awaited_once()

        # Verify KG population was attempted
        mock_extraction_populator.process_extraction.assert_awaited_once()

        # Verify extraction tracking was updated
        mock_populator.update_extracted_cycle.assert_awaited_once_with(mock_conn, 3)

    @pytest.mark.asyncio
    async def test_empty_llm_response(self):
        """When LLM returns empty result, returns error status."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 0}
        )
        mock_reader.get_unextracted_messages = AsyncMock(
            return_value=[
                {"id": uuid4(), "content": "Some text", "narrator_deltas": None}
            ]
        )
        mock_reader.get_entities = AsyncMock(return_value=[])
        mock_reader.get_active_arcs = AsyncMock(return_value=[])
        mock_reader.get_stub_locations = AsyncMock(return_value=[])

        mock_llm = MagicMock()
        mock_llm.extract_structured = AsyncMock(return_value=None)
        mock_llm._last_call_cost = None

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=mock_llm,
        ):
            result = await run_batch_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=2
            )

        assert result == {"success": False, "error": "empty_llm_response"}

    @pytest.mark.asyncio
    async def test_validation_error_falls_back_to_raw(self):
        """When NarrativeExtraction validation fails, _process_raw_batch is used."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 0}
        )
        mock_reader.get_unextracted_messages = AsyncMock(
            return_value=[
                {"id": uuid4(), "content": "Narrative text", "narrator_deltas": None}
            ]
        )
        mock_reader.get_entities = AsyncMock(return_value=[])
        mock_reader.get_active_arcs = AsyncMock(return_value=[])
        mock_reader.get_stub_locations = AsyncMock(return_value=[])

        # Return an extraction result that passes iteration in step 6
        # (facts/relations_created are lists) but fails NarrativeExtraction
        # Pydantic validation. Use a fact with invalid structure that the
        # FactData model will reject (missing required semantic_key).
        bad_result = {
            "facts": [
                {
                    "description": "Something happened",
                    "fact_type": "event",
                    "cycle": 2,
                    # Missing required field: semantic_key
                }
            ],
            "relations_created": [],
            "entities_created": [],
            "segment_summary": "Summary",
        }
        mock_llm = MagicMock()
        mock_llm.extract_structured = AsyncMock(return_value=bad_result)
        mock_llm._last_call_cost = {"cost_usd": 0.003}

        mock_extraction_populator = AsyncMock()
        mock_extraction_populator.load_registry = AsyncMock()
        # process_extraction will not be called (validation fails first)
        # _process_raw_batch will be used instead
        mock_extraction_populator.save_chronology_entry = AsyncMock()

        mock_populator = AsyncMock()

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=mock_populator,
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=mock_llm,
        ), patch(
            "services.extraction_service.ExtractionPopulator",
            return_value=mock_extraction_populator,
        ), patch(
            "services.extraction_service._process_raw_batch",
            new_callable=AsyncMock,
            return_value={"facts_created": 0, "errors": ["fact: validation error"]},
        ) as mock_raw_batch:
            result = await run_batch_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=2
            )

        assert result["success"] is True
        mock_raw_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_exception_triggers_retry(self):
        """When extraction raises an exception, a retry is scheduled."""
        from services.extraction_service import (
            run_batch_extraction,
            _RETRY_ATTEMPTED,
        )

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(side_effect=RuntimeError("DB down"))

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=MagicMock(),
        ), patch(
            "asyncio.create_task"
        ) as mock_create_task:
            result = await run_batch_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=5
            )

        assert result["success"] is False
        assert "DB down" in result["error"]
        # Retry should be scheduled
        mock_create_task.assert_called_once()
        # Retry flag should be set
        assert f"{SAMPLE_GAME_ID}:5" in _RETRY_ATTEMPTED

    @pytest.mark.asyncio
    async def test_retry_only_once(self):
        """Retry is not scheduled if already attempted."""
        from services.extraction_service import (
            run_batch_extraction,
            _RETRY_ATTEMPTED,
        )

        retry_key = f"{SAMPLE_GAME_ID}:5"
        _RETRY_ATTEMPTED[retry_key] = True

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(side_effect=RuntimeError("still broken"))

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=MagicMock(),
        ), patch(
            "asyncio.create_task"
        ) as mock_create_task:
            result = await run_batch_extraction(
                pool, SAMPLE_GAME_ID, trigger_cycle=5
            )

        assert result["success"] is False
        # No retry scheduled (already attempted)
        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_guard_cleared_after_completion(self):
        """The _extracting_games guard is cleared even on failure."""
        from services.extraction_service import (
            _extracting_games,
            run_batch_extraction,
        )

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(return_value=None)

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=MagicMock(),
        ):
            await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=3)

        assert str(SAMPLE_GAME_ID) not in _extracting_games

    @pytest.mark.asyncio
    async def test_guard_cleared_after_exception(self):
        """The _extracting_games guard is cleared even on exception."""
        from services.extraction_service import (
            _extracting_games,
            run_batch_extraction,
        )

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(side_effect=RuntimeError("boom"))

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=MagicMock(),
        ), patch(
            "asyncio.create_task",
        ):
            await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=3)

        assert str(SAMPLE_GAME_ID) not in _extracting_games

    @pytest.mark.asyncio
    async def test_inventory_hints_collected(self):
        """Inventory hints from narrator_deltas are passed to _formalize_inventory_hints."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 0}
        )
        mock_reader.get_unextracted_messages = AsyncMock(
            return_value=[
                {
                    "id": uuid4(),
                    "content": "Valentin picks up a keycard.",
                    "narrator_deltas": {
                        "inventory_hints": [
                            {"item_name": "Keycard", "action": "acquire"}
                        ],
                        "hints": {"new_entities_mentioned": []},
                    },
                },
            ]
        )
        mock_reader.get_entities = AsyncMock(return_value=[])
        mock_reader.get_active_arcs = AsyncMock(return_value=[])
        mock_reader.get_stub_locations = AsyncMock(return_value=[])

        raw_result = _make_extraction_result()
        mock_llm = MagicMock()
        mock_llm.extract_structured = AsyncMock(return_value=raw_result)
        mock_llm._last_call_cost = None

        mock_extraction_populator = AsyncMock()
        mock_extraction_populator.load_registry = AsyncMock()
        mock_extraction_populator.process_extraction = AsyncMock(return_value={})
        mock_extraction_populator.save_chronology_entry = AsyncMock()

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=mock_llm,
        ), patch(
            "services.extraction_service.ExtractionPopulator",
            return_value=mock_extraction_populator,
        ), patch(
            "services.extraction_service._formalize_inventory_hints",
            new_callable=AsyncMock,
        ) as mock_formalize:
            await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=2)

        mock_formalize.assert_awaited_once()
        # Check that the keycard hint was passed
        call_args = mock_formalize.call_args
        hints_arg = call_args[0][2]  # Third positional arg
        assert len(hints_arg) == 1
        assert hints_arg[0]["item_name"] == "Keycard"

    @pytest.mark.asyncio
    async def test_cycle_injected_into_facts_and_relations(self):
        """Facts and relations without cycle get trigger_cycle injected."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 0}
        )
        mock_reader.get_unextracted_messages = AsyncMock(
            return_value=[
                {"id": uuid4(), "content": "Text", "narrator_deltas": None}
            ]
        )
        mock_reader.get_entities = AsyncMock(return_value=[])
        mock_reader.get_active_arcs = AsyncMock(return_value=[])
        mock_reader.get_stub_locations = AsyncMock(return_value=[])

        raw_result = {
            "facts": [
                {
                    "description": "A fact about the station operations",
                    "fact_type": "event",
                    "importance": 2,
                    "participants": [],
                    "semantic_key": "station:operate:normally",
                },
            ],
            "relations_created": [
                {"relation": {"source_ref": "A", "target_ref": "B", "relation_type": "knows"}, "cycle": None},
            ],
            "entities_created": [],
            "entities_updated": [],
            "objects_created": [],
            "relations_updated": [],
            "arcs_created": [],
            "arcs_updated": [],
            "arcs_resolved": [],
            "events_scheduled": [],
            "ambient_updates": [],
            "segment_summary": "Summary",
        }
        mock_llm = MagicMock()
        mock_llm.extract_structured = AsyncMock(return_value=raw_result)
        mock_llm._last_call_cost = None

        mock_extraction_populator = AsyncMock()
        mock_extraction_populator.load_registry = AsyncMock()
        mock_extraction_populator.process_extraction = AsyncMock(return_value={})
        mock_extraction_populator.save_chronology_entry = AsyncMock()

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=mock_llm,
        ), patch(
            "services.extraction_service.ExtractionPopulator",
            return_value=mock_extraction_populator,
        ):
            await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=7)

        # After injection, facts should have cycle=7
        assert raw_result["facts"][0]["cycle"] == 7


class TestProcessRawBatch:
    """Tests for _process_raw_batch() fallback processor."""

    @pytest.mark.asyncio
    async def test_processes_facts(self):
        from services.extraction_service import _process_raw_batch

        mock_populator = AsyncMock()
        mock_populator.create_fact = AsyncMock(return_value=True)
        mock_conn = AsyncMock()

        data = {
            "facts": [
                {
                    "description": "A discovered B in the lower deck",
                    "fact_type": "event",
                    "importance": 3,
                    "participants": [],
                    "cycle": 5,
                    "semantic_key": "valentin:discover:passage",
                }
            ],
        }

        stats = await _process_raw_batch(mock_populator, mock_conn, data, cycle=5)
        assert stats["facts_created"] == 1
        mock_populator.create_fact.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_fact_error(self):
        from services.extraction_service import _process_raw_batch

        mock_populator = AsyncMock()
        mock_populator.create_fact = AsyncMock(side_effect=RuntimeError("DB error"))
        mock_conn = AsyncMock()

        data = {
            "facts": [
                {
                    "description": "A discovered B in the passage",
                    "fact_type": "event",
                    "importance": 3,
                    "participants": [],
                    "cycle": 5,
                    "semantic_key": "valentin:discover:passage",
                }
            ],
        }

        stats = await _process_raw_batch(mock_populator, mock_conn, data, cycle=5)
        assert stats["facts_created"] == 0
        assert len(stats["errors"]) == 1
        assert "fact:" in stats["errors"][0]

    @pytest.mark.asyncio
    async def test_processes_entities(self):
        from services.extraction_service import _process_raw_batch

        mock_populator = AsyncMock()
        mock_populator._process_entity_creation = AsyncMock()
        mock_conn = AsyncMock()

        data = {
            "entities_created": [
                {
                    "entity_type": "character",
                    "name": "Dr. Voss",
                    "data": {"role": "scientist"},
                }
            ],
        }

        stats = await _process_raw_batch(mock_populator, mock_conn, data, cycle=3)
        assert stats["entities_created"] == 1

    @pytest.mark.asyncio
    async def test_processes_objects(self):
        from services.extraction_service import _process_raw_batch

        mock_populator = AsyncMock()
        mock_populator._process_object_creation = AsyncMock()
        mock_conn = AsyncMock()

        data = {
            "objects_created": [
                {
                    "name": "Access Card",
                    "from_hint": "keycard found",
                    "transportable": True,
                }
            ],
        }

        stats = await _process_raw_batch(mock_populator, mock_conn, data, cycle=3)
        assert stats["objects_created"] == 1

    @pytest.mark.asyncio
    async def test_processes_relations(self):
        from services.extraction_service import _process_raw_batch

        mock_populator = AsyncMock()
        mock_populator.create_relation = AsyncMock(return_value=True)
        mock_conn = AsyncMock()

        data = {
            "relations_created": [
                {
                    "relation": {
                        "source_ref": "Valentin",
                        "target_ref": "Ossek",
                        "relation_type": "knows",
                    },
                    "cycle": 3,
                }
            ],
        }

        stats = await _process_raw_batch(mock_populator, mock_conn, data, cycle=3)
        assert stats["relations_created"] == 1

    @pytest.mark.asyncio
    async def test_processes_ambient_updates(self):
        from services.extraction_service import _process_raw_batch

        mock_populator = AsyncMock()
        mock_populator.update_entity = AsyncMock()
        mock_conn = AsyncMock()

        data = {
            "ambient_updates": [
                {
                    "entity_ref": "Le Quart de Cycle",
                    "entity_type": "location",
                    "ambient": "A busy atmosphere fills the cafe.",
                }
            ],
        }

        stats = await _process_raw_batch(mock_populator, mock_conn, data, cycle=3)
        mock_populator.update_entity.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_data(self):
        from services.extraction_service import _process_raw_batch

        mock_populator = AsyncMock()
        mock_conn = AsyncMock()

        stats = await _process_raw_batch(mock_populator, mock_conn, {}, cycle=1)
        assert stats["facts_created"] == 0
        assert stats["entities_created"] == 0
        assert stats["objects_created"] == 0
        assert stats["relations_created"] == 0
        assert stats["errors"] == []

    @pytest.mark.asyncio
    async def test_injects_cycle_into_facts(self):
        """Facts without cycle get the cycle parameter injected."""
        from services.extraction_service import _process_raw_batch

        mock_populator = AsyncMock()
        mock_populator.create_fact = AsyncMock(return_value=True)
        mock_conn = AsyncMock()

        fact_data = {
            "description": "Something happened on the station",
            "fact_type": "event",
            "importance": 2,
            "participants": [],
            "semantic_key": "something:happen:station",
        }
        data = {"facts": [fact_data]}

        await _process_raw_batch(mock_populator, mock_conn, data, cycle=7)
        # The fact_data should have been mutated to include cycle
        assert fact_data["cycle"] == 7


class TestFormalizeInventoryHints:
    """Tests for _formalize_inventory_hints()."""

    @pytest.mark.asyncio
    async def test_formalizes_acquire_hints(self):
        from services.extraction_service import _formalize_inventory_hints

        mock_populator = AsyncMock()
        mock_populator._process_object_creation = AsyncMock()
        mock_conn = AsyncMock()

        hints = [
            {"action": "acquire", "item_name": "Keycard", "item_description": "A shiny card"},
            {"action": "acquire", "item_name": "Medkit", "quantity": 2},
        ]

        created = await _formalize_inventory_hints(mock_populator, mock_conn, hints, cycle=3)
        assert created == 2
        assert mock_populator._process_object_creation.await_count == 2

    @pytest.mark.asyncio
    async def test_ignores_non_acquire_hints(self):
        from services.extraction_service import _formalize_inventory_hints

        mock_populator = AsyncMock()
        mock_conn = AsyncMock()

        hints = [
            {"action": "lose", "item_name": "Credits"},
            {"action": "use", "item_name": "Potion"},
        ]

        created = await _formalize_inventory_hints(mock_populator, mock_conn, hints, cycle=3)
        assert created == 0

    @pytest.mark.asyncio
    async def test_ignores_hints_without_name(self):
        from services.extraction_service import _formalize_inventory_hints

        mock_populator = AsyncMock()
        mock_conn = AsyncMock()

        hints = [
            {"action": "acquire", "item_name": ""},
            {"action": "acquire"},  # Missing item_name entirely
        ]

        created = await _formalize_inventory_hints(mock_populator, mock_conn, hints, cycle=3)
        assert created == 0

    @pytest.mark.asyncio
    async def test_handles_creation_error(self):
        from services.extraction_service import _formalize_inventory_hints

        mock_populator = AsyncMock()
        mock_populator._process_object_creation = AsyncMock(
            side_effect=RuntimeError("DB constraint")
        )
        mock_conn = AsyncMock()

        hints = [{"action": "acquire", "item_name": "BrokenItem"}]

        created = await _formalize_inventory_hints(mock_populator, mock_conn, hints, cycle=3)
        assert created == 0  # Error swallowed, logged

    @pytest.mark.asyncio
    async def test_empty_hints(self):
        from services.extraction_service import _formalize_inventory_hints

        mock_populator = AsyncMock()
        mock_conn = AsyncMock()

        created = await _formalize_inventory_hints(mock_populator, mock_conn, [], cycle=3)
        assert created == 0


class TestExtractionCostAndTimestamp:
    """Tests for extraction cost storage and last_extraction_time update."""

    @pytest.mark.asyncio
    async def test_extraction_cost_stored_on_last_message(self):
        """Extraction cost is stored on the last message's narrator_deltas."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()
        msg_id = uuid4()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 0}
        )
        mock_reader.get_unextracted_messages = AsyncMock(
            return_value=[
                {"id": msg_id, "content": "Text", "narrator_deltas": None}
            ]
        )
        mock_reader.get_entities = AsyncMock(return_value=[])
        mock_reader.get_active_arcs = AsyncMock(return_value=[])
        mock_reader.get_stub_locations = AsyncMock(return_value=[])

        raw_result = _make_extraction_result()
        mock_llm = MagicMock()
        mock_llm.extract_structured = AsyncMock(return_value=raw_result)
        mock_llm._last_call_cost = {"cost_usd": 0.007, "input_tokens": 1200}

        mock_extraction_populator = AsyncMock()
        mock_extraction_populator.load_registry = AsyncMock()
        mock_extraction_populator.process_extraction = AsyncMock(return_value={})
        mock_extraction_populator.save_chronology_entry = AsyncMock()

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=mock_llm,
        ), patch(
            "services.extraction_service.ExtractionPopulator",
            return_value=mock_extraction_populator,
        ):
            await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=2)

        # Check that conn.execute was called to store extraction cost
        execute_calls = mock_conn.execute.call_args_list
        cost_update_found = False
        for call in execute_calls:
            args = call[0]
            if len(args) >= 1 and "extraction_cost" in str(args[0]):
                cost_update_found = True
                break
        assert cost_update_found, "Expected extraction cost to be stored on last message"

    @pytest.mark.asyncio
    async def test_last_extraction_time_updated(self):
        """last_extraction_time is updated from the last message's time field."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 0}
        )
        mock_reader.get_unextracted_messages = AsyncMock(
            return_value=[
                {
                    "id": uuid4(),
                    "content": "Text",
                    "narrator_deltas": {"inventory_hints": []},
                    "time": "14h30",
                },
            ]
        )
        mock_reader.get_entities = AsyncMock(return_value=[])
        mock_reader.get_active_arcs = AsyncMock(return_value=[])
        mock_reader.get_stub_locations = AsyncMock(return_value=[])

        raw_result = _make_extraction_result()
        mock_llm = MagicMock()
        mock_llm.extract_structured = AsyncMock(return_value=raw_result)
        mock_llm._last_call_cost = None

        mock_extraction_populator = AsyncMock()
        mock_extraction_populator.load_registry = AsyncMock()
        mock_extraction_populator.process_extraction = AsyncMock(return_value={})
        mock_extraction_populator.save_chronology_entry = AsyncMock()

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=mock_llm,
        ), patch(
            "services.extraction_service.ExtractionPopulator",
            return_value=mock_extraction_populator,
        ):
            await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=2)

        # Check that last_extraction_time was set
        execute_calls = mock_conn.execute.call_args_list
        time_update_found = False
        for call in execute_calls:
            args = call[0]
            if len(args) >= 1 and "last_extraction_time" in str(args[0]):
                time_update_found = True
                break
        assert time_update_found, "Expected last_extraction_time to be updated"


class TestExtractionChronology:
    """Tests for chronology entry creation during extraction."""

    @pytest.mark.asyncio
    async def test_chronology_entry_saved_when_summary_present(self):
        """save_chronology_entry is called when segment_summary is non-empty."""
        from services.extraction_service import run_batch_extraction

        pool, mock_conn = _mock_pool()

        mock_reader = AsyncMock()
        mock_reader.get_game = AsyncMock(
            return_value={"extracted_up_to_cycle": 0}
        )
        mock_reader.get_unextracted_messages = AsyncMock(
            return_value=[
                {"id": uuid4(), "content": "Narrative", "narrator_deltas": None}
            ]
        )
        mock_reader.get_entities = AsyncMock(return_value=[])
        mock_reader.get_active_arcs = AsyncMock(return_value=[])
        mock_reader.get_stub_locations = AsyncMock(return_value=[])

        raw_result = _make_extraction_result()
        raw_result["segment_summary"] = "Valentin found the hidden room."
        mock_llm = MagicMock()
        mock_llm.extract_structured = AsyncMock(return_value=raw_result)
        mock_llm._last_call_cost = None

        mock_extraction_populator = AsyncMock()
        mock_extraction_populator.load_registry = AsyncMock()
        mock_extraction_populator.process_extraction = AsyncMock(return_value={})
        mock_extraction_populator.save_chronology_entry = AsyncMock()

        with patch(
            "services.extraction_service.KnowledgeGraphReader",
            return_value=mock_reader,
        ), patch(
            "services.extraction_service.KnowledgeGraphPopulator",
            return_value=AsyncMock(),
        ), patch(
            "services.extraction_service.get_llm_service",
            return_value=mock_llm,
        ), patch(
            "services.extraction_service.ExtractionPopulator",
            return_value=mock_extraction_populator,
        ):
            await run_batch_extraction(pool, SAMPLE_GAME_ID, trigger_cycle=4)

        mock_extraction_populator.save_chronology_entry.assert_awaited_once_with(
            mock_conn,
            4,
            summary="Valentin found the hidden room.",
        )
