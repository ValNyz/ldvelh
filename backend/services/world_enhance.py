"""
LDVELH - World Enhance
One LLM call that fills the creation wizard from the player's quick description.

The LLM output is never trusted as is: every field is validated against the
wizard's allowed values, and anything missing or invalid falls back to what the
form already holds, so the result can always be loaded back into the wizard.
"""

import logging
import re

from config import get_settings
from llm.session import LLMSession, Purpose
from prompts.world_enhance_prompt import SYSTEM_PROMPTS, build_user_message
from services.engine.engine_data import (
    D6_ATTRIBUTES,
    D6_MAX_SKILL_DICE_AT_CREATION,
    D6_STARTING_ATTRIBUTE_DICE,
    D6_STARTING_SKILL_DICE,
    FATE_DEFAULT_PYRAMID,
    get_d6_skills,
    get_fate_skills,
)

logger = logging.getLogger(__name__)

ENGINES = ("none", "narrative", "fate_core", "d6")
DIFFICULTIES = ("easy", "moderate", "hard", "brutal")
DURATIONS = ("short", "medium", "long")
GENDERS = ("", "male", "female", "non-binary", "other")
ENTITY_KINDS = ("npcs", "locations", "organizations")
SCOPES = ("world", "character")

MAX_ENTITIES = 6
MAX_TRAITS = 5
D6_MIN_PIPS, D6_MAX_PIPS = 3, 15  # 1D..5D, 1D = 3 pips
D6_SKILL_MAX_PIPS = D6_MAX_SKILL_DICE_AT_CREATION * 3
# Fate pyramid as an ordered list of levels: [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]
FATE_PYRAMID_LEVELS = [lvl for lvl in sorted(FATE_DEFAULT_PYRAMID, reverse=True)
                       for _ in range(FATE_DEFAULT_PYRAMID[lvl])]


class WorldEnhanceFailed(Exception):
    """The LLM call failed or returned no usable JSON."""


class NothingToEnhance(ValueError):
    """The scope's source text (lore or character description) is empty."""


def _text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _choice(value, allowed: tuple, fallback):
    return value if value in allowed else fallback


def _entities(proposed, current) -> list[dict]:
    """Current entities first (the player's), then new names from the LLM."""
    out, seen = [], set()
    for source in (current, proposed):
        for item in source if isinstance(source, list) else []:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"), 80)
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            out.append({"name": name, "description": _text(item.get("description"), 300)})
    return out[:MAX_ENTITIES]


def _traits(proposed, current) -> list[dict] | None:
    traits = []
    for item in proposed if isinstance(proposed, list) else []:
        if isinstance(item, dict) and _text(item.get("name"), 60):
            traits.append({"name": _text(item["name"], 60),
                           "description": _text(item.get("description"), 200)})
    return traits[:MAX_TRAITS] or current


def _aspects(proposed, current) -> dict | None:
    if not isinstance(proposed, dict):
        return current
    cur = _dict(current)
    proposed_other = proposed.get("other")
    cur_other = cur.get("other")
    other = []
    for i in range(3):
        mine = proposed_other[i] if isinstance(proposed_other, list) and i < len(proposed_other) else None
        theirs = cur_other[i] if isinstance(cur_other, list) and i < len(cur_other) else None
        other.append(_text(mine, 120) or _text(theirs, 120))
    return {
        "high_concept": _text(proposed.get("high_concept"), 120) or _text(cur.get("high_concept"), 120),
        "trouble": _text(proposed.get("trouble"), 120) or _text(cur.get("trouble"), 120),
        "other": other,
    }


def _pips(value) -> int | None:
    """3 -> 9 pips; "3D+1" -> 10 pips; anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) * 3
    if isinstance(value, str):
        m = re.fullmatch(r"\s*(\d+)\s*D(?:\s*\+\s*(\d))?\s*", value, re.IGNORECASE)
        if m:
            return int(m.group(1)) * 3 + int(m.group(2) or 0)
    return None


def _format_dice(pips: int) -> str:
    dice, rem = divmod(pips, 3)
    return f"{dice}D+{rem}" if rem else f"{dice}D"


def _fit_budget(pips: dict[str, int], low: int, high: int, budget: int) -> dict[str, int]:
    """Bring the total to the budget within [low, high]: whole dice first, then
    single pips, taking from the highest and giving to the lowest."""
    for step in (3, 1):
        while sum(pips.values()) - budget >= step:
            name = max((n for n in pips if pips[n] - step >= low), key=lambda n: pips[n], default=None)
            if name is None:
                break
            pips[name] -= step
        while budget - sum(pips.values()) >= step:
            name = min((n for n in pips if pips[n] + step <= high), key=lambda n: pips[n], default=None)
            if name is None:
                break
            pips[name] += step
    return pips


def normalize_d6_attributes(proposed) -> dict | None:
    """Every attribute between 1D and 5D, the total exactly the starting budget."""
    if not isinstance(proposed, dict):
        return None
    pips = {}
    for attr in D6_ATTRIBUTES:
        p = _pips(proposed.get(attr))
        pips[attr] = min(max(p if p is not None else 6, D6_MIN_PIPS), D6_MAX_PIPS)
    pips = _fit_budget(pips, D6_MIN_PIPS, D6_MAX_PIPS, D6_STARTING_ATTRIBUTE_DICE * 3)
    return {attr: _format_dice(p) for attr, p in pips.items()}


def _canonical(names) -> dict[str, str]:
    return {n.casefold(): n for n in names}


def normalize_d6_skills(proposed, genre: str | None) -> dict | None:
    """Dice added to skills of the genre's list: each 1 pip to 2D, 7D in total
    (less when too few skills to spend it: the player spends the rest).

    Returns {skill: "1D+1"} (dice added on top of the attribute), or None when
    nothing usable was proposed.
    """
    if not isinstance(proposed, dict):
        return None
    allowed = _canonical(s for skills in get_d6_skills(genre).values() for s in skills)
    budget = D6_STARTING_SKILL_DICE * 3
    pips: dict[str, int] = {}
    for name, value in proposed.items():
        canonical = allowed.get(str(name).strip().casefold())
        p = _pips(value)
        if canonical and canonical not in pips and p and p > 0 and len(pips) < budget:
            pips[canonical] = min(p, D6_SKILL_MAX_PIPS)
    if not pips:
        return None
    pips = _fit_budget(pips, 1, D6_SKILL_MAX_PIPS, budget)
    return {name: _format_dice(p) for name, p in pips.items()}


def normalize_fate_skills(proposed, genre: str | None, current) -> dict | None:
    """The default pyramid (1 at +4, 2 at +3, 3 at +2, 4 at +1) from the proposed
    ranking, with skills of the genre's list only. Empty slots are completed from
    the current sheet, then from the list. None when nothing usable was proposed."""
    if not isinstance(proposed, dict):
        return None
    allowed = _canonical(get_fate_skills(genre))

    def level(value) -> float | None:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return float(value) if ok else None

    ranked: list[tuple[float, int, str]] = []  # (-level, order, skill)
    for i, (name, value) in enumerate(proposed.items()):
        canonical = allowed.get(str(name).strip().casefold())
        lvl = level(value)
        if canonical and lvl is not None and canonical not in (r[2] for r in ranked):
            ranked.append((-lvl, i, canonical))
    if not ranked:
        return None
    chosen = [name for _, _, name in sorted(ranked)]

    current_levels = {name: lvl for name, value in _dict(current).items()
                      if name in allowed.values() and (lvl := level(value)) is not None}
    current_ranked = sorted(current_levels, key=lambda name: -current_levels[name])
    for name in current_ranked + sorted(allowed.values()):
        if len(chosen) >= len(FATE_PYRAMID_LEVELS):
            break
        if name not in chosen:
            chosen.append(name)
    return dict(zip(chosen, FATE_PYRAMID_LEVELS))


def normalize_world(raw: dict, genre_slugs: list[str], current: dict) -> dict:
    """World step from the LLM JSON; anything invalid keeps the current form's value."""
    cur_world = _dict(current.get("world_config"))
    cur_entities = _dict(current.get("manual_entities"))
    world = _dict(raw.get("world_config"))
    cur_genre = cur_world.get("genre") if cur_world.get("genre") in genre_slugs else None
    hardcore = world.get("hardcore")
    world_config = {
        **cur_world,
        "genre": _choice(world.get("genre"), tuple(genre_slugs),
                         cur_genre or (genre_slugs[0] if genre_slugs else None)),
        "difficulty": _choice(world.get("difficulty"), DIFFICULTIES,
                              _choice(cur_world.get("difficulty"), DIFFICULTIES, "moderate")),
        "duration": _choice(world.get("duration"), DURATIONS,
                            _choice(cur_world.get("duration"), DURATIONS, "medium")),
        "hardcore": hardcore if isinstance(hardcore, bool) else bool(cur_world.get("hardcore")),
        "lore": _text(world.get("lore"), 3000) or _text(cur_world.get("lore"), 3000),
    }
    entities = _dict(raw.get("manual_entities"))
    manual_entities = {
        kind: _entities(entities.get(kind), cur_entities.get(kind)) for kind in ENTITY_KINDS
    }
    return {"world_config": world_config, "manual_entities": manual_entities}


def normalize_character(raw: dict, engine: str, current: dict) -> dict:
    """Character step from the LLM JSON; anything invalid keeps the current value."""
    cur_char = _dict(current.get("character_data"))
    genre = _dict(current.get("world_config")).get("genre")
    char = _dict(raw.get("character"))
    character_data = dict(cur_char)
    for key, limit in (("name", 80), ("occupation", 120), ("description", 2000)):
        character_data[key] = _text(char.get(key), limit) or _text(cur_char.get(key), limit)
    character_data["gender"] = _choice(char.get("gender"), GENDERS,
                                       _choice(cur_char.get("gender"), GENDERS, ""))

    mech = _dict(raw.get("engine"))
    if engine == "narrative":
        traits = _traits(mech.get("traits"), cur_char.get("traits"))
        if traits:
            character_data["traits"] = traits
    elif engine == "fate_core":
        aspects = _aspects(mech.get("aspects"), cur_char.get("aspects"))
        if aspects:
            character_data["aspects"] = aspects
        skills = normalize_fate_skills(mech.get("skills"), genre, cur_char.get("skills"))
        if skills:
            character_data["skills"] = skills
    elif engine == "d6":
        attributes = normalize_d6_attributes(mech.get("attributes")) or cur_char.get("attributes")
        if attributes:
            character_data["attributes"] = attributes
        skills = normalize_d6_skills(mech.get("skills"), genre)
        if skills:
            character_data["skills"] = skills
    return {"character_data": character_data}


def source_text(scope: str, current: dict) -> str:
    """The player's short text the scope enriches: the lore or the character description."""
    if scope == "world":
        return _text(_dict(current.get("world_config")).get("lore"), 3000)
    return _text(_dict(current.get("character_data")).get("description"), 2000)


async def enhance(
    session: LLMSession,
    scope: str,
    engine: str,
    genres: list[dict],
    current: dict,
) -> tuple[dict, dict | None]:
    """Run the LLM call for one scope; returns (the scope's wizard fields, cost).

    Raises NothingToEnhance when the source text is empty, WorldEnhanceFailed when
    the call gives no usable JSON.
    """
    text = source_text(scope, current)
    if not text:
        raise NothingToEnhance(scope)
    settings = get_settings()
    call = await session.complete_json(
        Purpose.WORLD_GEN,
        system_prompt=SYSTEM_PROMPTS[scope],
        user_message=build_user_message(scope, text, engine, genres, current),
        temperature=settings.temperature,
        max_tokens=settings.max_tokens_world_enhance,
    )
    if not isinstance(call.value, dict):
        logger.warning(f"[WORLD_ENHANCE] {scope}: no usable JSON (cost={call.cost})")
        raise WorldEnhanceFailed()
    if scope == "world":
        return normalize_world(call.value, [g["slug"] for g in genres], current), call.cost
    return normalize_character(call.value, engine, current), call.cost
