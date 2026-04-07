"""
LDVELH - None Engine
No mechanical system. Pure narrative, LLM decides everything.
"""

from uuid import UUID

from schema.engine import EngineType, MechanicalDecision, RollResult
from .base import BaseEngine


class NoneEngine(BaseEngine):
    engine_type = EngineType.NONE

    async def get_stats(self, conn, game_id: UUID) -> dict:
        return {}

    async def get_vitals_display(self, conn, game_id: UUID) -> dict:
        return {}

    async def create_character(self, conn, game_id: UUID, data: dict) -> None:
        pass

    async def get_npc_stats(self, conn, character_id: UUID) -> dict:
        return {}

    async def create_npc_stats(self, conn, character_id: UUID, data: dict) -> None:
        pass

    async def apply_roll_result(
        self, conn, game_id: UUID, roll: RollResult, cycle: int
    ) -> dict:
        return {}

    async def snapshot_state(self, conn, game_id: UUID) -> dict:
        return {}

    async def restore_snapshot(self, conn, game_id: UUID, snapshot: dict) -> None:
        pass

    def needs_mechanical_step(self) -> bool:
        return False

    def roll_dice(self, decision: MechanicalDecision) -> RollResult:
        raise NotImplementedError("NoneEngine does not roll dice")

    def build_narrator_addon(self, roll_result: RollResult | None) -> str:
        return ""

    def get_gauge_policy(self) -> str:
        return "none"
