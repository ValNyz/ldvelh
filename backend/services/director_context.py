"""
LDVELH - Director context
Reads the world state the Director plans from (collect step of the Director run, #96).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from kg.reader import KnowledgeGraphReader
from prompts.director_prompt import build_director_user_prompt

if TYPE_CHECKING:
    from asyncpg import Connection


@dataclass(frozen=True)
class DirectorContext:
    """Everything the Director prompt is built from."""

    world_summary: str
    protagonist_summary: str
    npc_summaries: str
    active_arcs: str
    recent_facts: str
    recent_chronology: str
    active_seeds: str
    previous_plans: str
    game_duration: str
    current_cycle: int
    current_time: str

    def user_prompt(self) -> str:
        return build_director_user_prompt(**asdict(self))


def _world_summary(game: dict) -> str:
    text = f"**{game.get('world_name', 'Monde')}**"
    if game.get("world_description"):
        text += f"\n{game['world_description']}"
    if game.get("world_atmosphere"):
        text += f"\nAtmosphère: {game['world_atmosphere']}"
    return text


def _protagonist_summary(proto: dict | None) -> str:
    if not proto:
        return "Pas de protagoniste"
    text = f"**{proto['name']}** — {proto.get('occupation', 'sans emploi')}"
    if proto.get("description"):
        text += f"\n{proto['description']}"
    if proto.get("backstory"):
        text += f"\nPassé: {proto['backstory']}"
    return text


def _npc_summaries(npcs: list[dict]) -> str:
    lines = []
    for npc in npcs[:10]:
        line = f"- **{npc['name']}** ({npc.get('occupation', '?')})"
        if npc.get("traits"):
            traits = npc["traits"] if isinstance(npc["traits"], list) else [npc["traits"]]
            line += f" — {', '.join(traits[:3])}"
        if npc.get("ambient"):
            line += f" [Ambiance: {npc['ambient']}]"
        lines.append(line)
    return "\n".join(lines)


def _active_arcs(arcs: list[dict]) -> str:
    lines = []
    for arc in arcs:
        line = f"- **{arc['title']}** ({arc.get('domain', '?')}, intensité {arc.get('intensity', 3)})"
        if arc.get("description"):
            line += f": {arc['description'][:200]}"
        lines.append(line)
    return "\n".join(lines)


def _previous_plans(plans) -> str:
    return "\n\n".join(
        f"**Cycle {p['cycle']} {p['ig_time'] or ''}** (tension {p['tension_level']})\n"
        f"{p['narrator_guidance'][:300]}"
        for p in reversed(plans)  # oldest first
    )


async def _last_plans(conn: Connection, game_id: UUID):
    return await conn.fetch(
        """SELECT cycle, ig_time, tension_level, narrator_guidance, long_term_vision
           FROM director_plans
           WHERE game_id = $1
           ORDER BY created_at DESC LIMIT 3""",
        game_id,
    )


async def collect_director_context(
    conn: Connection, game_id: UUID, current_cycle: int, current_time: str,
) -> DirectorContext | None:
    """Read the Director's inputs; None if the game does not exist."""
    reader = KnowledgeGraphReader(None, game_id)  # reads on `conn` only: no pool needed
    game = await reader.get_game(conn)
    if not game:
        return None
    proto = await reader.get_protagonist(conn)
    npcs = await reader.get_all_characters(conn)
    arcs = await reader.get_active_arcs(conn)
    facts = await reader.get_facts(conn, min_importance=3, limit=10)
    chronology = await reader.get_chronology(conn, limit=3)  # defaults to desc order
    seeds = await reader.get_active_seeds(conn, limit=10)
    return DirectorContext(
        world_summary=_world_summary(game),
        protagonist_summary=_protagonist_summary(proto),
        npc_summaries=_npc_summaries(npcs),
        active_arcs=_active_arcs(arcs),
        recent_facts="\n".join(f"- {f['description']}" for f in facts) if facts else "",
        recent_chronology="\n".join(f"Cycle {e['cycle']}: {e['summary']}" for e in chronology),
        active_seeds="\n".join(f"- {s['text']}" for s in seeds) if seeds else "",
        previous_plans=_previous_plans(await _last_plans(conn, game_id)),
        game_duration=game.get("game_duration") or "medium",
        current_cycle=current_cycle,
        current_time=current_time,
    )
