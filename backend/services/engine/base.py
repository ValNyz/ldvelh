"""
LDVELH - Base Engine ABC
All engine-specific logic goes through this abstraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from schema.engine import EngineType, MechanicalDecision, RollResult


class BaseEngine(ABC):
    """Abstract base class for game engines.

    Strategy pattern: get_engine(engine_type) returns the correct implementation.
    All engine-specific logic is dispatched through this interface.
    """

    engine_type: EngineType

    # =========================================================================
    # DB operations (async — require a connection)
    # =========================================================================

    @abstractmethod
    async def get_stats(self, conn, game_id: UUID) -> dict:
        """Load full engine character stats from DB."""
        ...

    @abstractmethod
    async def get_vitals_display(self, conn, game_id: UUID) -> dict:
        """Load engine vitals formatted for frontend display."""
        ...

    @abstractmethod
    async def create_character(self, conn, game_id: UUID, data: dict) -> None:
        """Create engine character tables from wizard data."""
        ...

    @abstractmethod
    async def get_npc_stats(self, conn, character_id: UUID) -> dict:
        """Load engine stats for an NPC."""
        ...

    @abstractmethod
    async def create_npc_stats(self, conn, character_id: UUID, data: dict) -> None:
        """Create engine stats for an NPC."""
        ...

    @abstractmethod
    async def apply_roll_result(
        self, conn, game_id: UUID, roll: RollResult, cycle: int
    ) -> dict:
        """Apply mechanical consequences (stress, wounds, etc.) after a roll."""
        ...

    @abstractmethod
    async def snapshot_state(self, conn, game_id: UUID) -> dict:
        """Capture current engine state for message snapshot (rollback support)."""
        ...

    @abstractmethod
    async def restore_snapshot(self, conn, game_id: UUID, snapshot: dict) -> None:
        """Restore engine state from a message snapshot."""
        ...

    # =========================================================================
    # Pure logic (sync — no DB needed)
    # =========================================================================

    @abstractmethod
    def needs_mechanical_step(self) -> bool:
        """Whether this engine requires a mechanical LLM call before narration."""
        ...

    @abstractmethod
    def roll_dice(self, decision: MechanicalDecision) -> RollResult:
        """Execute a dice roll based on the mechanical decision."""
        ...

    @abstractmethod
    def build_narrator_addon(self, roll_result: RollResult | None) -> str:
        """Build extra text to inject into the narrator system prompt."""
        ...

    @abstractmethod
    def get_gauge_policy(self) -> str:
        """How vitals are managed: 'none' | 'engine'."""
        ...

    def get_system_prompt_addon(self) -> str:
        """Return engine-specific text to append to the narrator system prompt.
        Override in subclasses. Default: empty."""
        return ""

    def build_context_stats(self, engine_stats: dict) -> list[str]:
        """Build engine-specific stats lines for the narrator context prompt.
        Returns a list of lines (no trailing newline). Override in subclasses."""
        return []

    # =========================================================================
    # Progression (override in subclasses that support progression)
    # =========================================================================

    def get_progression_system_prompt(self) -> str:
        """System prompt for progression extraction LLM call.
        Return empty string to skip progression entirely (e.g. NoneEngine)."""
        return ""

    def build_progression_user_prompt(
        self, stats: dict, rolls: list[dict], narrative_summary: str
    ) -> str:
        """User prompt for progression extraction. Includes current stats and context."""
        return ""

    def get_progression_tool_schema(self) -> dict:
        """Tool schema for structured progression extraction."""
        return {}

    async def apply_progression(
        self, conn, game_id: UUID, extraction: dict
    ) -> dict:
        """Apply extracted progression changes to DB. Returns summary of changes."""
        return {}

    # =========================================================================
    # Inventory object extensions (override in subclasses)
    # =========================================================================

    def get_object_prompt_addon(self) -> str:
        """Extra instructions for inventory extraction about engine-specific object fields.
        Return empty string if engine has no object extensions."""
        return ""

    async def create_object_extension(
        self, conn, object_id: UUID, engine_data: dict
    ) -> None:
        """Create engine-specific extension row for an object (object_d6, etc.)."""
        pass

    def build_mechanical_result_section(
        self, decision: "MechanicalDecision", roll: RollResult
    ) -> list[str]:
        """Build the mechanical result section for the narrator context prompt.
        Override in subclasses for engine-specific formatting."""
        lines = [
            "### RÉSULTAT MÉCANIQUE",
            f"**Compétence testée**: {decision.skill} (+{decision.skill_value})",
            f"**Difficulté**: {decision.difficulty}" + (
                f" ({decision.difficulty_label})" if decision.difficulty_label else ""
            ),
            f"**Dés**: {roll.dice} → total: {roll.total}",
            f"**Résultat avec compétence**: {roll.skill_total}",
        ]
        if roll.opposition_total is not None:
            lines.append(f"**Opposition**: {roll.opposition_total}")
        lines.append(f"**Issue**: **{roll.outcome.upper()}**")
        if roll.shifts is not None:
            lines.append(f"**Marge**: {roll.shifts}")
        if roll.complication:
            lines.append("**⚠ COMPLICATION** : le dé sauvage a provoqué un incident")
        lines.append(f"**Raison du test**: {decision.reason}")
        lines.append("")
        lines.append("⚠ Ce résultat est **DÉFINITIF**. Ta narration DOIT le respecter.")
        lines.append("")
        return lines
