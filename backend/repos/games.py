"""Game repository: DB reads that build domain objects."""

from uuid import UUID

from domain.game import DirectorSchedule, GameSnapshot
from kg.reader import KnowledgeGraphReader
from schema import DEFAULT_GAME_TIME


async def get_director_schedule(conn, game_id: UUID) -> DirectorSchedule:
    """Latest director plan (cycle, ig_time) plus the game's duration setting.

    Re-read at trigger time: the previous turn's Director runs outside the game
    lock and may commit a plan after a turn-start snapshot was taken.
    """
    plan = await conn.fetchrow(
        """SELECT cycle, ig_time FROM director_plans
           WHERE game_id = $1 ORDER BY created_at DESC LIMIT 1""",
        game_id,
    )
    duration = await conn.fetchval("SELECT game_duration FROM games WHERE id = $1", game_id)
    return DirectorSchedule(
        last_cycle=plan["cycle"] if plan else None,
        last_time=plan["ig_time"] if plan else None,
        game_duration=duration or "medium",
    )


async def get_snapshot(conn, game_id: UUID) -> GameSnapshot | None:
    """Return the game snapshot, or None if the game is missing or inactive.

    The reader is built without a pool: the methods used here only take `conn`.
    """
    reader = KnowledgeGraphReader(None, game_id)
    game = await reader.get_game(conn)
    if not game or not game["active"]:
        return None
    protagonist = await reader.get_protagonist(conn)
    return GameSnapshot(
        id=game_id,
        name=game["name"],
        world_created=await reader.is_world_created(conn),
        current_cycle=game["current_cycle"] or 0,
        current_date=game["current_date"],
        current_time=game["current_time"] or DEFAULT_GAME_TIME,
        current_location_id=game["current_location_id"],
        current_location_name=await reader.get_current_location_name(conn),
        engine=game["engine"],
        engine_locked=bool(game["engine_locked"]),
        genre_id=game["genre_id"],
        world_name=game["world_name"],
        protagonist_name=(protagonist or {}).get("name"),
        director=await get_director_schedule(conn, game_id),
    )


async def get_genre(conn, genre_id: UUID | None) -> dict | None:
    """Return the genre config by id, or None (no id or unknown genre)."""
    if not genre_id:
        return None
    row = await conn.fetchrow(
        """SELECT id, slug, label, tone_style, friction_flavor,
                  atmosphere_guidelines, world_type, location_types,
                  npc_archetypes, arrival_prompt, world_gen_example,
                  forbidden_ai_names
           FROM genres WHERE id = $1""",
        genre_id,
    )
    return dict(row) if row else None


async def get_genre_by_slug(conn, slug: str) -> dict | None:
    """Return the genre row for a slug, or None."""
    row = await conn.fetchrow("SELECT * FROM genres WHERE slug = $1 LIMIT 1", slug)
    return dict(row) if row else None


async def set_game_genre(conn, game_id: UUID, genre_id: UUID) -> None:
    await conn.execute("UPDATE games SET genre_id = $1 WHERE id = $2", genre_id, game_id)


async def set_game_duration(conn, game_id: UUID, duration: str) -> None:
    await conn.execute("UPDATE games SET game_duration = $2 WHERE id = $1", game_id, duration)


async def set_engine(conn, game_id: UUID, engine_type: str, world_config: dict | None) -> None:
    """Set the engine type and world config on the game."""
    await conn.execute(
        """UPDATE games SET engine = $1, world_config = $2, updated_at = NOW()
           WHERE id = $3""",
        engine_type, world_config, game_id,
    )
