"""
LDVELH - Entity Resolver (Context-Propagation)
Resolves narrative entity mentions to canonical DB names using two-message
coreference: the previous turn's annotated response + current response.

The previous assistant message carries span annotations (narrator_context)
that map text ranges to canonical entity names. The resolver reads those
to understand what entities exist, then maps mentions in the new response.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from schema.extraction import EntityResolution
from services.llm_service import get_llm_service

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)

# =============================================================================
# RESOLUTION MAP
# =============================================================================


@dataclass
class MentionMapping:
    """A single narrative mention mapped to a canonical entity."""

    mention: str  # Exact text from narrative (e.g. "le docteur")
    canonical: str  # Canonical DB name (e.g. "Dr. Elara Voss")
    entity_type: str  # character, location, organization, object, arc
    is_new: bool  # True if this is a new entity (not yet in DB)


@dataclass
class ResolutionMap:
    """Lookup table of narrative mentions -> canonical entity names."""

    mappings: list[MentionMapping] = field(default_factory=list)

    def get_canonical(self, mention: str) -> str | None:
        """Lookup canonical name for a narrative mention (case-insensitive)."""
        mention_lower = mention.lower()
        for m in self.mappings:
            if m.mention.lower() == mention_lower:
                return m.canonical
        return None

    def to_prompt_section(self, entity_type: str | None = None) -> str:
        """Render a lookup table for injection into extractor prompts."""
        filtered = self.mappings
        if entity_type:
            filtered = [m for m in filtered if m.entity_type == entity_type]
        if not filtered:
            return ""

        groups: dict[tuple[str, bool], list[MentionMapping]] = {}
        for m in filtered:
            key = (m.canonical, m.is_new)
            groups.setdefault(key, []).append(m)

        existing_lines = []
        new_lines = []
        for (canonical, is_new), mentions in groups.items():
            mention_strs = ", ".join(f'"{m.mention}"' for m in mentions)
            etype = mentions[0].entity_type
            line = f'- {mention_strs} \u2192 "{canonical}" [{etype}]'
            if is_new:
                new_lines.append(line)
            else:
                existing_lines.append(line)

        parts = []
        if existing_lines:
            parts.append(
                "EXISTING entities (use these exact canonical names):\n"
                + "\n".join(existing_lines)
            )
        if new_lines:
            parts.append(
                "NEW entities (use these suggested names):\n"
                + "\n".join(new_lines)
            )
        return "\n\n".join(parts)


# =============================================================================
# SPAN ANNOTATIONS
# =============================================================================


def build_span_annotations(
    text: str, resolution_map: ResolutionMap
) -> list[list]:
    """Find spans of resolved mentions in the narrator response text.

    Returns list of [char_start, char_end, canonical_name, entity_type].
    """
    annotations = []
    text_lower = text.lower()

    # Group by canonical to avoid duplicate spans
    seen_spans: set[tuple[int, int]] = set()

    for mapping in resolution_map.mappings:
        mention_lower = mapping.mention.lower()
        # Find all occurrences of this mention in the text
        start = 0
        while True:
            idx = text_lower.find(mention_lower, start)
            if idx == -1:
                break
            end = idx + len(mapping.mention)
            span = (idx, end)
            if span not in seen_spans:
                seen_spans.add(span)
                annotations.append([
                    idx, end, mapping.canonical, mapping.entity_type
                ])
            start = idx + 1

    # Sort by position
    annotations.sort(key=lambda a: a[0])
    return annotations


def _rebuild_annotated_text(text: str, annotations: list | None) -> str:
    """Rebuild a text with inline entity annotations for the resolver prompt.

    Transforms: "le docteur sourit" with annotation [3, 13, "Dr. Voss", "character"]
    Into: "le docteur [= Dr. Voss] sourit"
    """
    if not annotations:
        return text

    # Handle double-encoded strings from DB (legacy data)
    if isinstance(annotations, str):
        import json
        try:
            annotations = json.loads(annotations)
        except (json.JSONDecodeError, TypeError):
            return text

    # Sort by position descending to insert without shifting offsets
    sorted_anns = sorted(annotations, key=lambda a: a[0], reverse=True)
    result = text
    for ann in sorted_anns:
        if len(ann) < 3:
            continue
        start, end, canonical = ann[0], ann[1], ann[2]
        result = result[:end] + f" [= {canonical}]" + result[end:]

    return result


# =============================================================================
# PROMPT
# =============================================================================

RESOLVER_SYSTEM_PROMPT = """\
You are an entity resolution engine for a French-language interactive narrative RPG.

Your task: identify all entity mentions in MESSAGE 2 (the new narrator response) \
and map them to canonical entity names.

MESSAGE 1 contains the PREVIOUS narrator response with inline annotations like \
[= Canonical Name] that show you the resolved entity names. Use these as your \
reference for coreference resolution.

## Rules

1. **Match mentions in MESSAGE 2** to canonical names seen in MESSAGE 1 annotations.
2. **Coreference**: "le docteur", "Voss", "la médecin" may all refer to "Dr. Elara Voss".
3. **EXISTING**: entity appeared in MESSAGE 1 annotations. Use the exact canonical name.
4. **NEW**: genuinely new entity not in MESSAGE 1. Suggest a clean French name.
5. **Skip**: pronouns, generic crowd, the protagonist.
6. **Entity types**: character, location, organization, object, arc.
7. **Output exact narrative text** from MESSAGE 2 in the `mentions` list.

Output valid JSON:
{
  "existing": [
    {"mentions": ["text1", "text2"], "canonical": "Exact Name", "entity_type": "type"}
  ],
  "new": [
    {"mentions": ["text1"], "suggested_name": "Clean Name", "entity_type": "type"}
  ]
}
"""


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def _parse_resolution(raw: dict) -> ResolutionMap:
    """Parse LLM output into a ResolutionMap."""
    resolution = EntityResolution.model_validate(raw)
    mappings: list[MentionMapping] = []

    for entry in resolution.existing:
        for mention in entry.mentions:
            mappings.append(MentionMapping(
                mention=mention,
                canonical=entry.canonical,
                entity_type=entry.entity_type,
                is_new=False,
            ))

    for entry in resolution.new:
        for mention in entry.mentions:
            mappings.append(MentionMapping(
                mention=mention,
                canonical=entry.suggested_name,
                entity_type=entry.entity_type,
                is_new=True,
            ))

    return ResolutionMap(mappings=mappings)


async def resolve_entities(
    pool: Pool,
    game_id: UUID,
    previous_response: str,
    previous_annotations: list[list] | None,
    current_response: str,
    provider_name: str = "anthropic",
    api_key: str | None = None,
) -> tuple[ResolutionMap | None, dict | None]:
    """Resolve entity mentions in the current narrator response.

    Uses two-message coreference:
      msg 1: previous response with inline entity annotations
      msg 2: current response (needs resolution)

    Returns (ResolutionMap, cost_dict) or (None, None) on failure.
    """
    # Build annotated previous response (msg 1)
    annotated_prev = _rebuild_annotated_text(
        previous_response, previous_annotations or []
    )

    # Call LLM with 2 messages — use the provider's default model
    llm = get_llm_service()
    raw = await llm.extract_text(
        system_prompt=RESOLVER_SYSTEM_PROMPT,
        user_message=f"MESSAGE 1 (previous, annotated):\n{annotated_prev}\n\n"
                     f"MESSAGE 2 (current, to resolve):\n{current_response}",
        provider_name=provider_name,
        api_key=api_key,
    )
    cost = getattr(llm, "_last_call_cost", None)

    if not raw:
        logger.warning("[RESOLVER] LLM returned empty response")
        return None, cost

    try:
        resolution_map = _parse_resolution(raw)
        logger.info(
            f"[RESOLVER] Resolved {len(resolution_map.mappings)} mentions "
            f"({sum(1 for m in resolution_map.mappings if not m.is_new)} existing, "
            f"{sum(1 for m in resolution_map.mappings if m.is_new)} new)"
        )
        return resolution_map, cost
    except Exception as e:
        logger.warning(f"[RESOLVER] Failed to parse resolution: {e}")
        return None, cost
