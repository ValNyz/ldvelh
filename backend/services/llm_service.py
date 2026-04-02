"""
LDVELH - LLM Service

Orchestrates LLM calls via provider abstraction.
Handles streaming logic, JSON parsing, SSE events, cost tracking.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import json
import logging
import re

from api.streaming import SSEWriter, build_display_text, extract_narrative_from_partial
from config import get_settings
from services.llm_providers import (
    LLMProvider,
    LLMUsage,
    StructuredOutputMode,
    ToolResult,
    get_provider,
)
from utils import parse_json_response

logger = logging.getLogger(__name__)


# =============================================================================
# COST TRACKING
# =============================================================================


@dataclass
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    calls: int = 0


def _compute_cost(usage: ModelUsage, provider: LLMProvider, model: str) -> float:
    """Compute USD cost using provider-specific pricing."""
    pricing = provider.get_pricing(model)
    return (
        usage.input_tokens * pricing.input
        + usage.output_tokens * pricing.output
        + usage.cache_creation_input_tokens * pricing.cache_write
        + usage.cache_read_input_tokens * pricing.cache_read
    ) / 1_000_000


def compute_cost_from_stored(usage_data: dict) -> float:
    """Compute USD cost from a stored usage dict (read from DB).

    Expected keys: input_tokens, output_tokens, cache_creation_input_tokens,
    cache_read_input_tokens, model, provider.
    """
    model = usage_data.get("model", "")
    provider_name = usage_data.get("provider", "anthropic")
    provider = get_provider(provider_name)
    mu = ModelUsage(
        input_tokens=usage_data.get("input_tokens", 0),
        output_tokens=usage_data.get("output_tokens", 0),
        cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
    )
    return round(_compute_cost(mu, provider, model), 6)


class CostTracker:
    """Accumulates token usage and computes cost, tracked per purpose."""

    def __init__(self):
        self._usage: dict[str, ModelUsage] = {}  # key = "purpose:model"

    def record(
        self, model: str, usage: LLMUsage, purpose: str, provider: LLMProvider
    ) -> dict:
        """Record usage from a provider call.

        Returns a cost snapshot for this individual call.
        """
        key = f"{purpose}:{model}"
        if key not in self._usage:
            self._usage[key] = ModelUsage()
        u = self._usage[key]

        u.input_tokens += usage.input_tokens
        u.output_tokens += usage.output_tokens
        u.cache_creation_input_tokens += usage.cache_creation_input_tokens
        u.cache_read_input_tokens += usage.cache_read_input_tokens
        u.calls += 1

        # Build per-call snapshot
        call_usage = ModelUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            calls=1,
        )
        call_cost = _compute_cost(call_usage, provider, model)
        logger.debug(
            f"[COST] {purpose}/{model}: +{usage.input_tokens}in +{usage.output_tokens}out "
            f"(cache_read={usage.cache_read_input_tokens}) = ${call_cost:.6f}"
        )
        return {
            "cost_usd": round(call_cost, 6),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "model": model,
            "provider": provider.provider_name,
        }

    def get_summary(self, default_provider: LLMProvider | None = None) -> dict:
        """Return a summary of usage and cost grouped by purpose."""
        purposes: dict[str, dict] = {}
        total_cost = 0.0

        for key, usage in self._usage.items():
            purpose, model = key.split(":", 1)

            # Determine provider from model name for pricing
            if model.startswith("mistral"):
                provider = get_provider("mistral")
            elif model.startswith("claude"):
                provider = get_provider("anthropic")
            elif default_provider:
                provider = default_provider
            else:
                provider = get_provider("anthropic")

            cost = _compute_cost(usage, provider, model)
            total_cost += cost

            if purpose not in purposes:
                purposes[purpose] = {"models": {}, "cost_usd": 0.0, "calls": 0}
            purposes[purpose]["models"][model] = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens,
                "calls": usage.calls,
                "cost_usd": round(cost, 6),
            }
            purposes[purpose]["cost_usd"] = round(
                purposes[purpose]["cost_usd"] + cost, 6
            )
            purposes[purpose]["calls"] += usage.calls

        return {
            "purposes": purposes,
            "total_cost_usd": round(total_cost, 6),
        }


# =============================================================================
# LLM SERVICE
# =============================================================================


class LLMService:
    """Orchestrates LLM calls via provider abstraction."""

    def __init__(self):
        self.settings = get_settings()
        self.cost_tracker = CostTracker()

    def _get_provider(
        self,
        provider_name: str = "anthropic",
        api_key: str | None = None,
        model: str | None = None,
    ) -> LLMProvider:
        return get_provider(provider_name, api_key=api_key, model=model)

    # =========================================================================
    # STREAMING NARRATION
    # =========================================================================

    async def stream_narration(
        self,
        system_prompt: str,
        messages: list[dict],
        sse_writer: SSEWriter,
        is_init_mode: bool = False,
        temperature: float | None = None,
        on_complete: Callable[[dict | None, str | None, str], Awaitable[None]]
        | None = None,
        on_narrative_ready: Callable[[str], Awaitable[None]] | None = None,
        provider_name: str = "anthropic",
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        """
        Stream a narrative response from the LLM.

        Args:
            system_prompt: System prompt
            messages: Messages array (multi-turn conversation + context prompt)
            sse_writer: SSE writer for streaming
            temperature: Temperature float to pass to the LLM
            is_init_mode: True for World Builder mode
            on_complete: Callback on completion with (parsed, display_text, raw_json)
            on_narrative_ready: Callback when narrative_text is complete
            provider_name: LLM provider to use ('anthropic' or 'mistral')
        """
        provider = self._get_provider(provider_name, api_key=api_key, model=model)
        settings = self.settings
        max_tokens = (
            settings.max_tokens_init if is_init_mode else settings.max_tokens_narration
        )
        temp = settings.temperature if temperature is None else temperature

        full_json = ""
        last_sent_length = 0
        last_progress_length = 0
        narrative_callback_fired = False

        try:
            stream_usage: LLMUsage | None = None
            async for item in provider.stream(
                system_prompt=system_prompt,
                messages=messages,
                temperature=temp,
                max_tokens=max_tokens,
            ):
                if isinstance(item, LLMUsage):
                    stream_usage = item
                    continue

                # item is a text delta
                full_json += item

                if is_init_mode:
                    if len(full_json) - last_progress_length > 500:
                        await sse_writer.send_progress(full_json)
                        last_progress_length = len(full_json)
                else:
                    displayable = extract_narrative_from_partial(full_json)
                    if displayable and len(displayable) > last_sent_length:
                        delta = displayable[last_sent_length:]
                        await sse_writer.send_chunk(delta)
                        last_sent_length = len(displayable)

                        if (
                            not narrative_callback_fired
                            and on_narrative_ready
                            and self._is_narrative_complete(full_json)
                        ):
                            narrative_callback_fired = True
                            await on_narrative_ready(displayable)

            # Record cost
            purpose = "world_gen" if is_init_mode else "narration"
            model = provider.model_name(purpose)
            if stream_usage:
                self._last_call_cost = self.cost_tracker.record(
                    model, stream_usage, purpose=purpose, provider=provider
                )

            if is_init_mode and len(full_json) > last_progress_length:
                await sse_writer.send_progress(full_json)

            parsed = parse_json_response(full_json)
            if parsed:
                logger.info(
                    f"[LLM] JSON generated:\n{json.dumps(parsed, indent=2, ensure_ascii=False)}"
                )
            else:
                logger.error(
                    f"[LLM] JSON parse FAILED. Raw output ({len(full_json)} chars):\n{full_json}"
                )

            display_text = None
            if not is_init_mode and parsed:
                display_text = build_display_text(parsed)
            elif not is_init_mode:
                display_text = (
                    extract_narrative_from_partial(full_json) or "Generation error."
                )

            if on_complete:
                await on_complete(parsed, display_text, full_json)

        except Exception as e:
            logger.error(f"[LLM] API error ({provider_name}): {e}")
            await sse_writer.send_error(
                f"LLM API error ({provider_name}): {e}", recoverable=True
            )
            raise

    @staticmethod
    def _is_narrative_complete(partial_json: str) -> bool:
        """Detect if the narrative_text field is complete in the partial JSON."""
        pattern = r'"narrative_text"\s*:\s*"(?:[^"\\]|\\.)*"\s*[,}]'
        return bool(re.search(pattern, partial_json))

    # =========================================================================
    # EXTRACTION
    # =========================================================================

    async def extract_text(
        self,
        system_prompt: str,
        user_message: str,
        provider_name: str = "anthropic",
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict | None:
        """Heavy extraction call."""
        return await self._extract(
            system_prompt, user_message, "extraction", provider_name,
            self.settings.max_tokens_extraction, api_key=api_key, model=model,
        )

    async def extract_structured(
        self,
        system_prompt: str,
        user_message: str,
        tool_name: str,
        tool_description: str,
        schema: dict,
        provider_name: str = "anthropic",
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict | None:
        """Dispatch extraction based on provider's structured_output_mode.

        - TOOL_USE: Anthropic native tool_use
        - JSON_SCHEMA: OpenAI Structured Outputs (schema-enforced)
        - TEXT: Raw JSON in text, schema in prompt only
        """
        provider = self._get_provider(provider_name, api_key=api_key, model=model)
        mode = provider.structured_output_mode

        if mode == StructuredOutputMode.TOOL_USE:
            return await self._extract_tool_use(
                provider, system_prompt, user_message,
                tool_name, tool_description, schema,
                provider_name=provider_name, api_key=api_key, model=model,
            )
        elif mode == StructuredOutputMode.JSON_SCHEMA:
            return await self._extract_json_schema(
                provider, system_prompt, user_message,
                tool_name, schema,
                provider_name=provider_name, api_key=api_key, model=model,
            )
        else:
            return await self.extract_text(
                system_prompt, user_message, provider_name,
                api_key=api_key, model=model,
            )

    # Backward-compatible alias
    async def extract_with_tools(self, **kwargs) -> dict | None:
        return await self.extract_structured(**kwargs)

    async def _extract_tool_use(
        self,
        provider: LLMProvider,
        system_prompt: str,
        user_message: str,
        tool_name: str,
        tool_description: str,
        schema: dict,
        provider_name: str = "anthropic",
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict | None:
        """Extraction via Anthropic tool_use. Falls back to text on failure."""
        try:
            tool_result: ToolResult = await provider.complete_with_tools(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                tools=[{
                    "name": tool_name,
                    "description": tool_description,
                    "input_schema": schema,
                }],
                tool_choice={"type": "tool", "name": tool_name},
                temperature=self.settings.temperature_extraction,
                max_tokens=self.settings.max_tokens_extraction,
            )
            mdl = provider.model_name("extraction")
            self._last_call_cost = self.cost_tracker.record(
                mdl, tool_result.usage, purpose="extraction", provider=provider
            )
            logger.info(f"[LLM] tool_use extraction via {provider_name}")
            return tool_result.tool_input

        except NotImplementedError:
            logger.info(
                f"[LLM] {provider_name} does not support tool_use, falling back to text"
            )
            return await self.extract_text(
                system_prompt, user_message, provider_name,
                api_key=api_key, model=model,
            )
        except Exception as e:
            logger.warning(f"[LLM] tool_use extraction failed: {e}, falling back to text")
            return await self.extract_text(
                system_prompt, user_message, provider_name,
                api_key=api_key, model=model,
            )

    async def _extract_json_schema(
        self,
        provider: LLMProvider,
        system_prompt: str,
        user_message: str,
        schema_name: str,
        schema: dict,
        provider_name: str = "anthropic",
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict | None:
        """Extraction via OpenAI Structured Outputs (json_schema). Falls back to text."""
        try:
            result = await provider.complete_with_schema(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                schema_name=schema_name,
                schema=schema,
                temperature=self.settings.temperature_extraction,
                max_tokens=self.settings.max_tokens_extraction,
            )
            mdl = provider.model_name("extraction")
            self._last_call_cost = self.cost_tracker.record(
                mdl, result.usage, purpose="extraction", provider=provider
            )
            logger.info(f"[LLM] json_schema extraction via {provider_name}")
            return json.loads(result.content)

        except NotImplementedError:
            logger.info(
                f"[LLM] {provider_name} does not support json_schema, falling back to text"
            )
            return await self.extract_text(
                system_prompt, user_message, provider_name,
                api_key=api_key, model=model,
            )
        except Exception as e:
            logger.warning(f"[LLM] json_schema extraction failed: {e}, falling back to text")
            return await self.extract_text(
                system_prompt, user_message, provider_name,
                api_key=api_key, model=model,
            )

    async def _extract(
        self,
        system_prompt: str,
        user_message: str,
        purpose: str,
        provider_name: str,
        max_tokens: int,
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict | None:
        """Shared extraction logic."""
        provider = self._get_provider(provider_name, api_key=api_key, model=model)
        try:
            result = await provider.complete(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                temperature=self.settings.temperature_extraction,
                max_tokens=max_tokens,
            )
            model = provider.model_name(purpose)
            self._last_call_cost = self.cost_tracker.record(
                model, result.usage, purpose=purpose, provider=provider
            )
            return parse_json_response(result.content)

        except Exception as e:
            logger.error(f"[LLM] Extraction error ({provider_name}): {e}")
            return None

    # =========================================================================
    # SUMMARY
    # =========================================================================

    async def summarize_message(
        self,
        narrative_text: str,
        max_length: int = 150,
        provider_name: str = "anthropic",
    ) -> str:
        """Generate a short summary of a narrative message."""
        provider = self._get_provider(provider_name)
        try:
            result = await provider.complete(
                system_prompt="You are a concise summarizer for a narrative RPG.",
                messages=[
                    {
                        "role": "user",
                        "content": f"""Résume ce texte narratif en une phrase de {max_length} caractères maximum.
Garde l'essentiel: qui, quoi, où.

Texte:
{narrative_text[:2000]}

Résumé (une phrase):""",
                    }
                ],
                temperature=0.3,
                max_tokens=self.settings.max_tokens_summary,
            )
            model = provider.model_name("summary")
            self.cost_tracker.record(
                model, result.usage, purpose="summary", provider=provider
            )
            return result.content.strip()[:max_length]

        except Exception as e:
            logger.error(f"[LLM] Summary error ({provider_name}): {e}")
            return narrative_text[:max_length].rsplit(" ", 1)[0] + "..."



# Singleton
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get the LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
