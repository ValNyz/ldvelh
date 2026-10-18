"""Typed, frozen game state used by the turn pipeline.

Read straight from the DB (repos.games.get_snapshot). The frontend DTO built by
services.state_normalizer drops fields the pipeline needs (#9), so the pipeline
never reads it.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


# The one difficulty scale: the wizard offers it (schema.engine.WorldConfig.difficulty,
# frontend engineConfig.DIFFICULTIES) and the arbiter reads it as "World difficulty"
# (prompts/mechanical_prompt.build_mechanical_context).
ARBITER_DIFFICULTIES = ("easy", "moderate", "hard", "brutal")
DEFAULT_DIFFICULTY = "moderate"


def difficulty_from_world_config(world_config: object) -> tuple[str, bool]:
    """The arbiter's difficulty for a game's stored wizard world_config (#137), and
    whether a stored value was unknown (the caller logs it).

    Games without stored parameters (created before #88) get the default silently; an
    unknown value, or a world_config that is not an object, gets it flagged.
    """
    if world_config is None:
        return DEFAULT_DIFFICULTY, False
    if not isinstance(world_config, dict):
        return DEFAULT_DIFFICULTY, True
    value = world_config.get("difficulty")
    if value is None:
        return DEFAULT_DIFFICULTY, False
    if value not in ARBITER_DIFFICULTIES:
        return DEFAULT_DIFFICULTY, True
    return value, False


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
