"""What a committed narration turn produced (pure data)."""

from dataclasses import dataclass


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
