"""
LDVELH - LLM Service

Orchestrates LLM calls via provider abstraction.
Handles streaming logic, JSON parsing, SSE events, cost tracking.
"""

from collections.abc import Awaitable, Callable

import json
import logging
import re

from api.streaming import SSEWriter, build_display_text, extract_narrative_from_partial
from config import get_settings
from llm.session import LLMSession, Purpose
from llm.usage import call_cost, get_usage_ledger
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
# COST HELPERS
# =============================================================================


def compute_cost_from_stored(usage_data: dict) -> float:
    """Compute USD cost from a stored usage dict (read from DB).

    Expected keys: input_tokens, output_tokens, cache_creation_input_tokens,
    cache_read_input_tokens, model, provider.
    """
    usage = LLMUsage(
        input_tokens=usage_data.get("input_tokens", 0),
        output_tokens=usage_data.get("output_tokens", 0),
        cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
    )
    return round(
        call_cost(usage, usage_data.get("provider", "anthropic"), usage_data.get("model", "")), 6
    )


# =============================================================================
# LLM SERVICE
# =============================================================================


class LLMService:
    """Orchestrates LLM calls via provider abstraction."""

    def __init__(self):
        self.settings = get_settings()
        self.cost_tracker = get_usage_ledger()

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
        session: LLMSession,
        system_prompt: str,
        messages: list[dict],
        sse_writer: SSEWriter,
        is_init_mode: bool = False,
        temperature: float | None = None,
        on_complete: Callable[[dict | None, str | None, str, dict | None], Awaitable[None]]
        | None = None,
        on_narrative_ready: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Stream a narrative (or world-gen) response; on_complete gets this call's cost."""
        settings = self.settings
        max_tokens = (
            settings.max_tokens_init if is_init_mode else settings.max_tokens_narration
        )
        temp = settings.temperature if temperature is None else temperature
        purpose = Purpose.WORLD_GEN if is_init_mode else Purpose.NARRATION

        full_json = ""
        last_sent_length = 0
        last_progress_length = 0
        narrative_callback_fired = False

        try:
            stream = session.stream(purpose, system_prompt, messages, temp, max_tokens)
            async for item in stream:
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
                await on_complete(parsed, display_text, full_json, stream.cost)

        except Exception as e:
            logger.error(f"[LLM] API error ({session.provider_name}): {e}")
            await sse_writer.send_error(
                f"LLM API error ({session.provider_name}): {e}", recoverable=True
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
        purpose: str = "extraction",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict | None:
        """JSON-in-text call (extraction by default; also used by the mechanical step)."""
        return await self._extract(
            system_prompt, user_message, purpose, provider_name,
            max_tokens or self.settings.max_tokens_extraction,
            api_key=api_key, model=model, temperature=temperature,
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
                "extraction", provider.provider_name, mdl, tool_result.usage
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
                "extraction", provider.provider_name, mdl, result.usage
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
        temperature: float | None = None,
    ) -> dict | None:
        """Shared extraction logic."""
        provider = self._get_provider(provider_name, api_key=api_key, model=model)
        try:
            result = await provider.complete(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                temperature=(
                    temperature if temperature is not None
                    else self.settings.temperature_extraction
                ),
                max_tokens=max_tokens,
            )
            model = provider.model_name(purpose)
            self._last_call_cost = self.cost_tracker.record(
                purpose, provider.provider_name, model, result.usage
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
                "summary", provider.provider_name, model, result.usage
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
