"""
LDVELH - Entity Resolver (Phase 1)
Resolves narrative entity mentions to canonical DB names before parallel extraction.
Single Haiku call on the recent scene + known entity catalog.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from config import get_settings
from kg.reader import KnowledgeGraphReader
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
        """Render a lookup table for injection into extractor prompts.

        Groups mentions by canonical name for readability.
        If entity_type is given, filter to that type only.
        """
        filtered = self.mappings
        if entity_type:
            filtered = [m for m in filtered if m.entity_type == entity_type]
        if not filtered:
            return ""

        # Group by (canonical, is_new)
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
# ENTITY CATALOG
# =============================================================================


async def _build_entity_catalog(
    pool: Pool, game_id: UUID
) -> dict[str, list[dict]]:
    """Load compact entity catalog from DB for the resolver prompt."""
    reader = KnowledgeGraphReader(pool, game_id)
    catalog: dict[str, list[dict]] = {}

    async with pool.acquire() as conn:
        # Characters
        characters = await reader.get_all_characters(conn)
        catalog["character"] = [
            {
                "name": c["name"],
                "occupation": c.get("occupation"),
                "unknown_name": c.get("unknown_name"),
                "species": c.get("species"),
            }
            for c in characters[:50]
        ]

        # Locations
        locations = await reader.get_locations(conn)
        catalog["location"] = [
            {
                "name": loc["name"],
                "location_type": loc.get("location_type"),
                "sector": loc.get("sector"),
            }
            for loc in locations[:50]
        ]

        # Organizations
        organizations = await reader.get_organizations(conn)
        catalog["organization"] = [
            {
                "name": org["name"],
                "org_type": org.get("org_type"),
                "domain": org.get("domain"),
            }
            for org in organizations[:50]
        ]

        # Objects
        objects = await reader.get_objects(conn)
        catalog["object"] = [
            {"name": obj["name"], "category": obj.get("category")}
            for obj in objects[:50]
        ]

        # Arcs
        arcs = await reader.get_active_arcs(conn)
        catalog["arc"] = [
            {"title": arc["title"], "domain": arc.get("domain")}
            for arc in arcs[:50]
        ]

    return catalog


def _format_catalog_section(catalog: dict[str, list[dict]]) -> str:
    """Format the entity catalog as a compact prompt section."""
    lines = []

    if catalog.get("character"):
        entries = []
        for c in catalog["character"]:
            parts = [c["name"]]
            if c.get("occupation"):
                parts.append(f"occupation: {c['occupation']}")
            if c.get("unknown_name"):
                parts.append(f"also known as: {c['unknown_name']}")
            if c.get("species") and c["species"] != "human":
                parts.append(f"species: {c['species']}")
            entries.append(f"  - {', '.join(parts)}")
        lines.append("Characters:\n" + "\n".join(entries))

    if catalog.get("location"):
        entries = []
        for loc in catalog["location"]:
            parts = [loc["name"]]
            if loc.get("location_type"):
                parts.append(f"type: {loc['location_type']}")
            if loc.get("sector"):
                parts.append(f"sector: {loc['sector']}")
            entries.append(f"  - {', '.join(parts)}")
        lines.append("Locations:\n" + "\n".join(entries))

    if catalog.get("organization"):
        entries = []
        for org in catalog["organization"]:
            parts = [org["name"]]
            if org.get("org_type"):
                parts.append(f"type: {org['org_type']}")
            if org.get("domain"):
                parts.append(f"domain: {org['domain']}")
            entries.append(f"  - {', '.join(parts)}")
        lines.append("Organizations:\n" + "\n".join(entries))

    if catalog.get("object"):
        entries = []
        for obj in catalog["object"]:
            parts = [obj["name"]]
            if obj.get("category"):
                parts.append(f"category: {obj['category']}")
            entries.append(f"  - {', '.join(parts)}")
        lines.append("Objects:\n" + "\n".join(entries))

    if catalog.get("arc"):
        entries = []
        for arc in catalog["arc"]:
            parts = [arc["title"]]
            if arc.get("domain"):
                parts.append(f"domain: {arc['domain']}")
            entries.append(f"  - {', '.join(parts)}")
        lines.append("Narrative arcs:\n" + "\n".join(entries))

    return "\n\n".join(lines)


# =============================================================================
# PROMPT
# =============================================================================

RESOLVER_SYSTEM_PROMPT = """\
You are an entity resolution engine for a French-language interactive narrative RPG.

Your task: identify all entity mentions in the RECENT SCENE and map them to known \
entities from the database, or flag them as genuinely new.

## Rules

1. **Match types**: exact name, partial name, role/title reference, descriptive \
reference, possessive reference.
   - "le docteur" -> match "Dr. Elara Voss" if she has occupation "médecin"
   - "Voss" -> match "Dr. Elara Voss" (partial name)
   - "le bar principal" -> match "Le Nebula Lounge" if it's the main bar
   - "l'enquête sur les disparitions" -> match arc "Mystères des couloirs E7" \
if thematically related

2. **Coreference**: group multiple mentions of the same entity together \
in the same `mentions` list.
   - If message 1 says "Dr. Voss" and message 3 says "la docteur", both go \
under the same entry.

3. **EXISTING vs NEW**:
   - EXISTING: the entity is in the known entities list. Use the exact canonical name.
   - NEW: genuinely new entity not in the known list. Suggest a clean French name.

4. **Skip**: pronouns (il, elle, ils), generic crowd ("les passants", "des gens"), \
and the protagonist (player character) should NOT appear in the output.

5. **Entity types**: character, location, organization, object, arc.

6. **Output exact narrative text** in the `mentions` list — copy the exact words \
from the scene text, do not paraphrase.

7. **Use the hints** (occupation, type, sector, category, domain) from the known \
entities list to disambiguate. A "docteur" near a medical context likely refers \
to the character with occupation "médecin".

8. **Arc title drift**: narrative may refer to arcs with different wording. Match \
if the thematic content clearly overlaps.

Output valid JSON matching this schema:
{
  "existing": [
    {"mentions": ["text1", "text2"], "canonical": "Exact DB Name", "entity_type": "character"}
  ],
  "new": [
    {"mentions": ["text1"], "suggested_name": "Clean Name", "entity_type": "character"}
  ]
}
"""


def _build_resolver_user_prompt(
    catalog: dict[str, list[dict]],
    recent_messages: list[dict],
) -> str:
    """Build the user prompt for the resolver LLM call."""
    parts = []

    # Known entities
    catalog_text = _format_catalog_section(catalog)
    if catalog_text:
        parts.append(f"## KNOWN ENTITIES (from database)\n\n{catalog_text}")
    else:
        parts.append("## KNOWN ENTITIES\n\nNo entities in database yet.")

    # Recent scene
    scene_lines = []
    for msg in recent_messages:
        role = msg.get("role", "assistant")
        content = msg.get("content", "")
        if content:
            scene_lines.append(f"[{role}] {content}")
    parts.append("## RECENT SCENE\n\n" + "\n\n".join(scene_lines))

    return "\n\n".join(parts)


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
    recent_messages: list[dict],
    provider_name: str = "anthropic",
    api_key: str | None = None,
) -> tuple[ResolutionMap | None, dict | None]:
    """Phase 1: resolve entity mentions in the recent scene to canonical names.

    Returns (ResolutionMap, cost_dict) or (None, None) on failure.
    """
    settings = get_settings()

    # Build entity catalog from DB
    catalog = await _build_entity_catalog(pool, game_id)

    # Check if there are any known entities to resolve against
    total_entities = sum(len(v) for v in catalog.values())
    if total_entities == 0:
        logger.info("[RESOLVER] No known entities — skipping resolution")
        return None, None

    # Build prompt
    user_prompt = _build_resolver_user_prompt(catalog, recent_messages)

    # Call LLM (Haiku — cheap and fast)
    llm = get_llm_service()
    raw = await llm.extract_text(
        system_prompt=RESOLVER_SYSTEM_PROMPT,
        user_message=user_prompt,
        provider_name=provider_name,
        api_key=api_key,
        model=settings.resolution_model,
    )
    cost = getattr(llm, "_last_call_cost", None)

    if not raw:
        logger.warning("[RESOLVER] LLM returned empty response")
        return None, cost

    # Parse into ResolutionMap
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
