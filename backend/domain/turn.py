"""What a narration turn works with and produces (pure data)."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class NarrationState:
    """Game state after the narration was applied: cycle, time, place, NPCs, date."""

    cycle: int
    time: str
    location: str | None
    npcs_present: list[str]
    date: str | None


@dataclass(frozen=True)
class AppliedDeltas:
    """Narrator deltas applied on the spot (credit transaction, Fate compel)."""

    credit: dict | None  # {"amount", "description", "applied", "new_balance", "error"}
    compel: dict | None


@dataclass(frozen=True)
class PendingRoll:
    """A failed Fate roll waiting for the player's aspect invocation (#32)."""

    id: UUID
    roll: dict  # the original RollResult, as stored
    player_message: str  # the action the resumed turn narrates
    aspects: list[str]
    fate_points: int

    def offer(self) -> dict:
        """What the player sees: the roll_pending event and the loaded game state."""
        return {"roll_id": str(self.id), "roll": self.roll, "aspects": list(self.aspects),
                "fate_points": self.fate_points, "player_message": self.player_message}
