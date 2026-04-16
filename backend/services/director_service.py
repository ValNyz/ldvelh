"""
LDVELH - Director Service
Background narrative planner that produces session-level guidance for the narrator.
Runs periodically based on in-game time elapsed.
"""

import json
import logging
from uuid import UUID

import asyncpg

from kg.reader import KnowledgeGraphReader
from prompts.director_prompt import (
    DIRECTOR_INTERVAL,
    DIRECTOR_SYSTEM_PROMPT,
    build_director_user_prompt,
    get_director_tool_schema,
)
from schema.director import DirectorOutput
from services.llm_service import LLMService

logger = logging.getLogger(__name__)


def _parse_ig_hours(t: str) -> float:
    """Parse 'HHhMM' to fractional hours."""
    if not t or "h" not in t:
        return 0.0
    try:
        parts = t.split("h")
        return int(parts[0]) + int(parts[1] or "0") / 60
    except (ValueError, IndexError):
        return 0.0


def should_run_director(
    current_time: str,
    last_director_time: str | None,
    game_duration: str = "medium",
) -> bool:
    """Check if enough in-game time has elapsed since last Director run."""
    interval = DIRECTOR_INTERVAL.get(game_duration, 6)

    if last_director_time is None:
        return True

    current_h = _parse_ig_hours(current_time)
    last_h = _parse_ig_hours(last_director_time)

    # Handle day wrap (e.g., last=22h, current=03h → elapsed=5h)
    elapsed = current_h - last_h
    if elapsed < 0:
        elapsed += 24

    return elapsed >= interval


async def run_director(
    pool: asyncpg.Pool,
    game_id: UUID,
    current_cycle: int,
    current_time: str,
    provider_name: str = "anthropic",
    api_key: str | None = None,
) -> dict | None:
    """Run the Director LLM and store its plan.

    Fire-and-forget — called via asyncio.create_task from routes.py.
    Returns the stored plan dict or None on failure.
    """
    logger.info(f"[DIRECTOR] Starting for game {game_id} at cycle {current_cycle} {current_time}")

    try:
        reader = KnowledgeGraphReader(pool, game_id)

        async with pool.acquire() as conn:
            # Load game state
            game = await reader.get_game(conn)
            if not game:
                logger.warning(f"[DIRECTOR] Game {game_id} not found")
                return None

            game_duration = game.get("game_duration") or "medium"

            # Build world summary
            world_summary = f"**{game.get('world_name', 'Monde')}**"
            if game.get("world_description"):
                world_summary += f"\n{game['world_description']}"
            if game.get("world_atmosphere"):
                world_summary += f"\nAtmosphère: {game['world_atmosphere']}"

            # Build protagonist summary
            proto = await reader.get_protagonist(conn)
            proto_summary = "Pas de protagoniste"
            if proto:
                proto_summary = f"**{proto['name']}** — {proto.get('occupation', 'sans emploi')}"
                if proto.get("description"):
                    proto_summary += f"\n{proto['description']}"
                if proto.get("backstory"):
                    proto_summary += f"\nPassé: {proto['backstory']}"

            # Build NPC summaries
            npcs = await reader.get_all_characters(conn)
            npc_lines = []
            for npc in npcs[:10]:
                line = f"- **{npc['name']}** ({npc.get('occupation', '?')})"
                if npc.get("traits"):
                    traits = npc["traits"] if isinstance(npc["traits"], list) else [npc["traits"]]
                    line += f" — {', '.join(traits[:3])}"
                if npc.get("ambient"):
                    line += f" [Ambiance: {npc['ambient']}]"
                npc_lines.append(line)
            npc_summaries = "\n".join(npc_lines)

            # Load active arcs
            arcs = await reader.get_active_arcs(conn)
            arc_lines = []
            for arc in arcs:
                line = f"- **{arc['title']}** ({arc.get('domain', '?')}, intensité {arc.get('intensity', 3)})"
                if arc.get("description"):
                    line += f": {arc['description'][:200]}"
                arc_lines.append(line)
            active_arcs = "\n".join(arc_lines)

            # Load recent facts
            facts = await reader.get_facts(conn, min_importance=3, limit=10)
            facts_text = "\n".join(f"- {f['description']}" for f in facts) if facts else ""

            # Load chronology
            chronology = await reader.get_chronology(conn, limit=3)  # defaults to desc order
            chrono_lines = []
            for entry in chronology:
                chrono_lines.append(f"Cycle {entry['cycle']}: {entry['summary']}")
            chrono_text = "\n".join(chrono_lines)

            # Load active seeds
            seeds = await reader.get_active_seeds(conn, limit=10)
            seeds_text = "\n".join(f"- {s['text']}" for s in seeds) if seeds else ""

            # Load previous Director plans (last 3)
            prev_plans = await conn.fetch(
                """SELECT cycle, ig_time, tension_level, narrator_guidance, long_term_vision
                   FROM director_plans
                   WHERE game_id = $1
                   ORDER BY created_at DESC LIMIT 3""",
                game_id,
            )
            prev_text = ""
            if prev_plans:
                plan_lines = []
                for p in reversed(prev_plans):  # oldest first
                    plan_lines.append(
                        f"**Cycle {p['cycle']} {p['ig_time'] or ''}** (tension {p['tension_level']})\n"
                        f"{p['narrator_guidance'][:300]}"
                    )
                prev_text = "\n\n".join(plan_lines)

        # Build prompt
        user_prompt = build_director_user_prompt(
            world_summary=world_summary,
            protagonist_summary=proto_summary,
            npc_summaries=npc_summaries,
            active_arcs=active_arcs,
            recent_facts=facts_text,
            recent_chronology=chrono_text,
            active_seeds=seeds_text,
            previous_plans=prev_text,
            game_duration=game_duration,
            current_cycle=current_cycle,
            current_time=current_time,
        )

        # Call LLM
        llm_service = LLMService()
        raw_result = await llm_service.extract_structured(
            system_prompt=DIRECTOR_SYSTEM_PROMPT,
            user_message=user_prompt,
            tool_name="director_plan",
            tool_description="Narrative direction plan for the next few in-game hours",
            schema=get_director_tool_schema(),
            provider_name=provider_name,
            api_key=api_key,
        )

        if not raw_result:
            logger.warning("[DIRECTOR] LLM returned empty result")
            return None

        # Validate
        plan = DirectorOutput.model_validate(raw_result)

        # Store in DB
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO director_plans
                   (game_id, cycle, ig_time, tension_level, narrator_guidance, planned_events, long_term_vision)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                game_id,
                current_cycle,
                current_time,
                plan.tension_level,
                plan.narrator_guidance,
                json.dumps([e.model_dump() for e in plan.planned_events]),
                plan.long_term_vision,
            )

            # Update last_director_time on game
            await conn.execute(
                "UPDATE games SET last_director_time = $2 WHERE id = $1",
                game_id, current_time,
            )

        logger.info(
            f"[DIRECTOR] Plan stored for game {game_id}: "
            f"tension={plan.tension_level}, events={len(plan.planned_events)}"
        )
        return plan.model_dump()

    except Exception as e:
        logger.error(f"[DIRECTOR] Failed for game {game_id}: {e}", exc_info=True)
        return None
