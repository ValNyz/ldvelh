"""Game repository: DB reads that build domain objects."""

from uuid import UUID

from domain.game import DirectorSchedule, GameSnapshot
from kg.reader import KnowledgeGraphReader


async def get_snapshot(conn, game_id: UUID) -> GameSnapshot | None:
    """Return the game snapshot, or None if the game is missing or inactive.

    The reader is built without a pool: the methods used here only take `conn`.
    """
    reader = KnowledgeGraphReader(None, game_id)
    game = await reader.get_game(conn)
    if not game or not game["active"]:
        return None
    protagonist = await reader.get_protagonist(conn)
    plan = await conn.fetchrow(
        """SELECT cycle, ig_time FROM director_plans
           WHERE game_id = $1 ORDER BY created_at DESC LIMIT 1""",
        game_id,
    )
    return GameSnapshot(
        id=game_id,
        name=game["name"],
        world_created=await reader.is_world_created(conn),
        current_cycle=game["current_cycle"] or 0,
        current_date=game["current_date"],
        current_time=game["current_time"] or "08h00",
        current_location_id=game["current_location_id"],
        current_location_name=await reader.get_current_location_name(conn),
        engine=game["engine"] or "none",
        engine_locked=bool(game["engine_locked"]),
        genre_id=game["genre_id"],
        world_name=game["world_name"],
        protagonist_name=(protagonist or {}).get("name"),
        director=DirectorSchedule(
            last_cycle=plan["cycle"] if plan else None,
            last_time=plan["ig_time"] if plan else None,
            game_duration=game["game_duration"] or "medium",
        ),
    )
