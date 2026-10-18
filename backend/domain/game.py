"""Typed, frozen game state used by the turn pipeline.

Read straight from the DB (repos.games.get_snapshot). The frontend DTO built by
services.state_normalizer drops fields the pipeline needs (#9), so the pipeline
never reads it.
"""

import logging
from uuid import UUID

from pydantic import BaseModel, ConfigDict


logger = logging.getLogger(__name__)

# The wizard offers the arbiter's own scale (schema.engine.MechanicalDecision).
ARBITER_DIFFICULTIES = ("easy", "moderate", "hard", "brutal")
DEFAULT_DIFFICULTY = "moderate"


def difficulty_from_world_config(world_config: dict | None, game_id: UUID) -> str:
    """The arbiter's difficulty for a game's stored wizard world_config (#137).

    Games without stored parameters (created before #88) and unknown values get the
    default; an unknown value is logged with the game id only.
    """
    value = (world_config or {}).get("difficulty")
    if value is None:
        return DEFAULT_DIFFICULTY
    if value not in ARBITER_DIFFICULTIES:
        logger.warning(f"Unknown stored difficulty for game {game_id}: using "
                       f"{DEFAULT_DIFFICULTY}")
        return DEFAULT_DIFFICULTY
    return value


class DirectorSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    last_cycle: int | None = None
    last_time: str | None = None
    game_duration: str = "medium"


class GameSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str | None = None
    world_created: bool
    current_cycle: int
    current_date: str | None = None
    current_time: str
    current_location_id: UUID | None = None
    current_location_name: str | None = None
    engine: str = "none"
    engine_locked: bool = False
    genre_id: UUID | None = None
    world_name: str | None = None
    protagonist_name: str | None = None
    difficulty: str = DEFAULT_DIFFICULTY  # arbiter scale, from the wizard (#137)
    director: DirectorSchedule = DirectorSchedule()
