"""
LDVELH - Mechanical Prompt
System prompt for the mechanical LLM step (decides if a test is needed and parameters).
Uses Haiku for cost efficiency.
"""

from services.engine.engine_data import (
    FATE_DIFFICULTY_LADDER,
    D6_DIFFICULTY_SCALE,
)


# =============================================================================
# SHARED MECHANICAL RULES
# =============================================================================

_SHARED_RULES = """## YOUR ROLE

You are the game mechanics arbiter for an RPG. Given the player's action and the current game state,
you decide whether a mechanical skill test is needed and, if so, which skill and difficulty.

## RULES

1. **Routine actions DO NOT require tests**: walking, talking, buying common items, looking around.
2. **Tests are for uncertain outcomes**: combat, persuasion under pressure, difficult physical feats,
   resisting danger, using specialized knowledge.
3. **Match the difficulty to the fiction**: a trained character attempting something within their
   expertise should face lower difficulty than an untrained one.
4. **Opposition**: If an NPC actively resists (combat, argument, chase), use an opposed test
   with the NPC's relevant skill.

## OUTPUT FORMAT

Return a JSON object:
```json
{
  "requires_test": true,
  "skill": "Skill Name",
  "skill_value": 3,
  "difficulty": 4,
  "difficulty_label": "Excellent",
  "opposition": null,
  "reason": "Brief explanation of why this test is needed"
}
```

If no test is needed:
```json
{
  "requires_test": false,
  "reason": "Brief explanation of why no test is needed"
}
```
"""


# =============================================================================
# FATE CORE MECHANICAL PROMPT
# =============================================================================

def _fate_ladder_text() -> str:
    """Format the Fate difficulty ladder for the prompt."""
    lines = []
    for value, label in sorted(FATE_DIFFICULTY_LADDER.items()):
        lines.append(f"  +{value}: {label}")
    return "\n".join(lines)


FATE_MECHANICAL_PROMPT = f"""{_SHARED_RULES}

## FATE CORE SPECIFICS

### Difficulty Ladder
{_fate_ladder_text()}

### Skill Values
- `skill_value` is the character's skill level (0=Mediocre to 8=Legendary)
- `difficulty` is the target number on the ladder
- For opposed tests, set `opposition` with the NPC's skill name and value

### Difficulty Guidelines
- Routine tasks: no test needed
- Easy tasks: Mediocre (+0) to Average (+1)
- Standard challenges: Fair (+2) to Good (+3)
- Hard challenges: Great (+4) to Superb (+5)
- Near-impossible: Fantastic (+6) to Legendary (+8)

### Opposition Format
When an NPC actively opposes, set:
```json
"opposition": {{"npc_name": "Guard", "skill": "Combat", "skill_value": 3}}
```
"""


# =============================================================================
# D6 SYSTEM MECHANICAL PROMPT
# =============================================================================

def _d6_difficulty_text() -> str:
    """Format D6 difficulty numbers for the prompt."""
    lines = []
    for label, value in sorted(D6_DIFFICULTY_SCALE.items(), key=lambda x: x[1]):
        lines.append(f"  {value}: {label}")
    return "\n".join(lines)


D6_MECHANICAL_PROMPT = f"""{_SHARED_RULES}

## D6 SYSTEM SPECIFICS

### Difficulty Numbers
{_d6_difficulty_text()}

### Skill Values
- `skill_value` is the character's dice code as an integer (number of dice, e.g. 3 for "3D")
- `difficulty` is the target number to beat
- For opposed tests, set `opposition` with the NPC's skill dice code

### Difficulty Guidelines
- Very easy: 5
- Easy: 10
- Moderate: 15
- Difficult: 20
- Very difficult: 25
- Heroic: 30

### Opposition Format
When an NPC actively opposes, set:
```json
"opposition": {{"npc_name": "Guard", "skill": "Blasters", "skill_value": "4D+1"}}
```
"""


# =============================================================================
# CONTEXT BUILDER
# =============================================================================


def build_mechanical_context(
    player_message: str,
    engine_stats: dict,
    world_difficulty: str,
    context_summary: str,
) -> str:
    """Build the user message for the mechanical LLM call."""
    lines = [
        "## GAME STATE",
        f"World difficulty: {world_difficulty}",
        "",
        "## CHARACTER STATS",
    ]

    # Skills
    skills = engine_stats.get("skills", [])
    if isinstance(skills, list):
        for s in skills:
            if isinstance(s, dict):
                name = s.get("name", "?")
                level = s.get("level") or s.get("dice_value", "?")
                label = s.get("label", "")
                lines.append(f"- {name}: {level}" + (f" ({label})" if label else ""))
    elif isinstance(skills, dict):
        # NPC-style flat dict: {"Combat": 3}
        for name, value in skills.items():
            lines.append(f"- {name}: {value}")

    # Vitals
    if engine_stats.get("fate_points") is not None:
        lines.append(f"Fate Points: {engine_stats['fate_points']}")
    if engine_stats.get("force_points") is not None:
        lines.append(f"Force Points: {engine_stats['force_points']}")

    lines.extend([
        "",
        "## SCENE CONTEXT",
        context_summary,
        "",
        "## PLAYER ACTION",
        f"> {player_message}",
        "",
        "Analyze the player's action and determine if a mechanical test is needed.",
    ])

    return "\n".join(lines)


def get_mechanical_system_prompt(engine_type: str) -> str:
    """Get the appropriate mechanical system prompt for the engine type."""
    if engine_type == "fate_core":
        return FATE_MECHANICAL_PROMPT
    elif engine_type == "d6":
        return D6_MECHANICAL_PROMPT
    else:
        raise ValueError(f"Engine {engine_type} does not use mechanical tests")
