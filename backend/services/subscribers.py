"""Default post-turn subscribers (#95): the scheduled Director, then the new-cycle work.

`register_defaults()` runs once at app import (main.py) and before each test (conftest).
"""

from uuid import UUID

import asyncpg

from kg.populator import KnowledgeGraphPopulator
from kg.reader import KnowledgeGraphReader
from services import director_service, hooks
from services.engine import get_engine


async def engine_new_cycle(conn: asyncpg.Connection, game_id: UUID, cycle: int) -> None:
    """The game engine's new-day work (BaseEngine.on_new_cycle)."""
    engine_type = await KnowledgeGraphReader(None, game_id).get_engine_type(conn)
    await get_engine(engine_type).on_new_cycle(conn, game_id, cycle)


async def archive_seeds(conn: asyncpg.Connection, game_id: UUID, cycle: int) -> None:
    """Archive the narrative seeds left active for too many cycles."""
    await KnowledgeGraphPopulator(None, game_id).archive_stale_seeds(conn, cycle)


def register_defaults() -> None:
    hooks.on_turn_committed(director_service.on_turn_committed)
    hooks.on_new_cycle(engine_new_cycle)
    hooks.on_new_cycle(archive_seeds)
