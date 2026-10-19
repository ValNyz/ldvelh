"""What a turn receives (TurnRequest) and what every step shares (TurnContext)."""

from dataclasses import dataclass, field
from uuid import UUID

import asyncpg

from domain.game import GameSnapshot
from llm.session import LLMSession
from pipeline.ports import EventSink
from services.engine.base import BaseEngine
from services.game_service import GameService


@dataclass(frozen=True)
class InitParams:
    """Wizard parameters of the world generation turn."""

    engine: str | None
    world_config: dict | None
    character_data: dict | None
    manual_entities: dict | None
    # The request carries the wizard parameters (any of the three parts, even null): they
    # replace the stored set. False for a bare retry, which reuses the stored set (#88).
    carries_wizard: bool = False


@dataclass(frozen=True)
class TurnRequest:
    game_id: UUID
    user_id: UUID
    message: str
    roll_id: UUID | None = None
    invoked_aspects: tuple[str, ...] = ()
    init: InitParams | None = None


@dataclass
class TurnContext:
    request: TurnRequest
    snapshot: GameSnapshot
    session: LLMSession
    sink: EventSink
    pool: asyncpg.Pool
    engine: BaseEngine
    ref: str
    # The turn this request opened (load step): its writes are journaled under it (#105).
    turn_id: UUID | None = None
    # Built once per turn from the pool: game state and narrator history reads.
    games: GameService = field(init=False)

    def __post_init__(self) -> None:
        self.games = GameService(self.pool)
