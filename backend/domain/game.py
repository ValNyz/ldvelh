"""Typed, frozen game state used by the turn pipeline.

Read straight from the DB (repos.games.get_snapshot). The frontend DTO built by
services.state_normalizer drops fields the pipeline needs (#9), so the pipeline
never reads it.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
    director: DirectorSchedule = DirectorSchedule()
