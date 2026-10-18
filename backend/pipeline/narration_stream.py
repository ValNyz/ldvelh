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
    last_sent_length = 0
    last_progress_length = 0

    stream = session.stream(purpose, system_prompt, messages, temp, max_tokens)
    async for item in _guarded(stream, session.provider_name):
        full_json += item
        if world_gen:
            if len(full_json) - last_progress_length > PROGRESS_STEP:
                await sink.send_progress(full_json)
                last_progress_length = len(full_json)
        else:
            displayable = extract_narrative_from_partial(full_json)
            if displayable and len(displayable) > last_sent_length:
                await sink.send_chunk(displayable[last_sent_length:])
                last_sent_length = len(displayable)

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


_SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
                   '"': '"', "\\": "\\", "/": "/"}
_HEX = frozenset("0123456789abcdefABCDEF")
REPLACEMENT_CHAR = "\ufffd"


def _read_hex4(s: str, i: int) -> int | None | bool:
    """Four hex digits at s[i:i+4]: the value, None if still incomplete, False if invalid."""
    digits = s[i:i + 4]
    if not set(digits) <= _HEX:
        return False
    return int(digits, 16) if len(digits) == 4 else None


def _decode_surrogate_pair(s: str, i: int, high: int) -> tuple[str, int] | None:
    """High surrogate read at s[i-6:i]: join it with the following `\\uXXXX` low surrogate.

    Returns None while the pair may still complete; a lone surrogate becomes U+FFFD
    (a lone surrogate cannot be encoded to UTF-8, json.loads would keep it).
    """
    rest = s[i:i + 6]
    if len(rest) < 6:
        if rest == "\\u"[:len(rest)] or (rest.startswith("\\u") and set(rest[2:]) <= _HEX):
            return None
        return REPLACEMENT_CHAR, i
    if rest.startswith("\\u") and (low := _read_hex4(s, i + 2)) and 0xDC00 <= low <= 0xDFFF:
        return chr(0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00)), i + 6
    return REPLACEMENT_CHAR, i


def _decode_unicode_escape(s: str, i: int) -> tuple[str, int] | None:
    """Decode `\\uXXXX` starting at s[i] (the backslash); None if more input is needed."""
    value = _read_hex4(s, i + 2)
    if value is None:
        return None
    if value is False:
        return REPLACEMENT_CHAR, i + 2  # invalid hex: the following characters stay literal
    end = i + 6
    if 0xD800 <= value <= 0xDBFF:
        return _decode_surrogate_pair(s, end, value)
    if 0xDC00 <= value <= 0xDFFF:
        return REPLACEMENT_CHAR, end
    return chr(value), end


def decode_json_escape(s: str, i: int) -> tuple[str, int] | None:
    """Decode the JSON escape whose backslash is at s[i].

    Returns (text, index after the escape), or None when the escape is cut off
    and the caller must wait for more input.
    """
    if i + 1 >= len(s):
        return None
    kind = s[i + 1]
    if kind == "u":
        return _decode_unicode_escape(s, i)
    return _SIMPLE_ESCAPES.get(kind, kind), i + 2


def extract_narrative_from_partial(partial_json: str) -> str | None:
    """
    Extrait le texte narratif d'un JSON partiel en cours de streaming.
    Gère les cas où le JSON n'est pas encore complet.
    """
    # Cherche "narrative_text": "
    marker = '"narrative_text":'
    start = partial_json.find(marker)

    if start == -1:
        return None

    # Trouve le début de la string
    quote_start = partial_json.find('"', start + len(marker))
    if quote_start == -1:
        return None

    # Extrait jusqu'à la fin ou jusqu'au prochain guillemet non-échappé
    content = []
    i = quote_start + 1
    while i < len(partial_json):
        char = partial_json[i]

        if char == "\\":
            decoded = decode_json_escape(partial_json, i)
            if decoded is None:
                # Incomplete escape: wait for the next chunk
                break
            text, i = decoded
            content.append(text)
        elif char == '"':
            # Fin de la string
            break
        else:
            content.append(char)
            i += 1

    result = "".join(content).strip()
    return result if result else None


def build_display_text(parsed: dict) -> str:
    """
    Construit le texte d'affichage depuis une réponse parsée.
    """
    text = parsed.get("narrative_text") or ""
    return text.strip()
