"""What a turn receives (TurnRequest) and what every step shares (TurnContext)."""

from dataclasses import dataclass
from uuid import UUID

import asyncpg

from domain.game import GameSnapshot
from llm.session import LLMSession
from pipeline.ports import EventSink
from services.engine.base import BaseEngine


@dataclass(frozen=True)
class InitParams:
    """Wizard parameters of the world generation turn."""

    engine: str | None
    world_config: dict | None
    character_data: dict | None
    manual_entities: dict | None


@dataclass(frozen=True)
class TurnRequest:
    game_id: UUID
    user_id: UUID | None
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
