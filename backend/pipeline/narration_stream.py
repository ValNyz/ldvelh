"""Narrator stream: deltas go to the sink, the result is returned (no callback, #44).

A provider failure raises ProviderCallFailed and sends nothing: the caller reports
it once (#45).
"""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from config import get_settings
from llm.session import LLMSession, Purpose, UsageRecordingFailed
from pipeline.narrative_scanner import NarrativeScanner, extract_narrative_from_partial
from pipeline.ports import EventSink
from utils import parse_json_response

logger = logging.getLogger(__name__)

PROGRESS_STEP = 500  # world generation: send the raw JSON every 500 new characters


class ProviderCallFailed(Exception):
    """The LLM provider failed mid-stream; the original error is the __cause__."""

    def __init__(self, provider: str):
        super().__init__(f"{provider} stream failed")
        self.provider = provider


@dataclass(frozen=True)
class NarrationStream:
    parsed: dict | None
    display_text: str | None
    raw: str
    cost: dict | None


async def _guarded(stream: AsyncIterator[str], provider: str) -> AsyncIterator[str]:
    """Re-raise provider errors as ProviderCallFailed.

    The consumer's own errors and our ledger failures pass through (they map to `internal`).
    """
    try:
        async for item in stream:
            yield item
    except UsageRecordingFailed:
        raise
    except Exception as e:
        raise ProviderCallFailed(provider) from e


async def stream_narration(session: LLMSession, sink: EventSink, *, system_prompt: str,
                           messages: list[dict], world_gen: bool,
                           temperature: float | None = None) -> NarrationStream:
    """Stream a narration (chunks) or a world generation (progress) and return its result."""
    settings = get_settings()
    max_tokens = settings.max_tokens_init if world_gen else settings.max_tokens_narration
    temp = settings.temperature if temperature is None else temperature
    purpose = Purpose.WORLD_GEN if world_gen else Purpose.NARRATION

    full_json = ""
    scanner = NarrativeScanner()
    last_progress_length = 0

    stream = session.stream(purpose, system_prompt, messages, temp, max_tokens)
    async for item in _guarded(stream, session.provider_name):
        full_json += item
        if world_gen:
            if len(full_json) - last_progress_length > PROGRESS_STEP:
                await sink.send_progress(full_json)
                last_progress_length = len(full_json)
        else:
            delta = scanner.feed(item)
            if delta:
                await sink.send_chunk(delta)

    if world_gen and len(full_json) > last_progress_length:
        await sink.send_progress(full_json)

    parsed = parse_json_response(full_json)
    if parsed:
        if settings.log_prompts:
            logger.debug(
                f"[LLM] JSON generated:\n{json.dumps(parsed, indent=2, ensure_ascii=False)}")
    else:
        # The raw output is story text: only its length at ERROR, an excerpt at DEBUG.
        logger.error(f"[LLM] JSON parse FAILED. Raw output: {len(full_json)} chars")
        if settings.log_prompts:
            logger.debug(f"[LLM] Unparsable output excerpt: "
                         f"head={full_json[:500]!r} tail={full_json[-500:]!r}")

    display_text = None
    if not world_gen:
        if parsed:
            display_text = build_display_text(parsed)
        else:
            display_text = extract_narrative_from_partial(full_json) or "Generation error."

    return NarrationStream(parsed=parsed, display_text=display_text, raw=full_json,
                           cost=stream.cost)


# =============================================================================
# DISPLAY BUILDER
# =============================================================================


def build_display_text(parsed: dict) -> str:
    """
    Construit le texte d'affichage depuis une réponse parsée.
    """
    text = parsed.get("narrative_text") or ""
    return text.strip()
