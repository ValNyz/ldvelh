"""
LDVELH - LLM Service

Narration streaming (SSE) on top of LLMSession; all other LLM calls go
directly through llm.session.
"""

from collections.abc import Awaitable, Callable

import json
import logging
import re

from api.streaming import SSEWriter, build_display_text, extract_narrative_from_partial
from config import get_settings
from llm.session import LLMSession, Purpose
from llm.usage import call_cost, get_usage_ledger
from services.llm_providers import LLMUsage
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


# Singleton
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get the LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
