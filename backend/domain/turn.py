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
class AppliedCredit:
    """What the ledger did with the narrator's credit delta."""

    amount: int
    description: str
    applied: bool
    new_balance: int | None
    error: str | None


@dataclass(frozen=True)
class AppliedDeltas:
    """Narrator deltas applied on the spot (credit transaction, Fate compel)."""

    credit: AppliedCredit | None
    compel: dict | None  # {"result", "aspect", "fp_change", "new_fp"}


@dataclass(frozen=True)
class InvocationOffer:
    """What the player may spend to improve a roll: invocable aspects and fate points."""

    aspects: list[str]
    fate_points: int


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


@dataclass(frozen=True)
class TurnCommitted:
    """A narration turn saved: what the post-turn background job works from."""

    game_id: UUID
    previous_cycle: int  # cycle at turn start
    cycle: int  # cycle after the narration
    time: str
    user_message_id: UUID
    assistant_message_id: UUID
    turn_id: UUID

    @property
    def new_cycle(self) -> bool:
        """The turn started a new in-game day."""
        return self.cycle > self.previous_cycle
