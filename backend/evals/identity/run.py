"""What a resolver run returns for one scene, as the scorer reads it (#151)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DecisionKind = Literal["MATCH", "ALIAS", "NEW", "UNSURE", "SKIP"]


@dataclass(frozen=True)
class Decision:
    """One resolver decision on a span of the narration (`start` + `surface`).

    `entity_id` is the linked id for MATCH/ALIAS. On a NEW it carries the id the system
    gave the created entity (None if unknown): later turns of a sequence MATCH it,
    `coref.system_clusters` groups by it, and the scorer reads it to check the SAME
    repeats of an entity born in the turn (they must link to that id).
    """

    surface: str
    start: int
    decision: DecisionKind
    entity_id: str | None
    alias_kind: str | None
    new_type: str | None
    deterministic: bool = False
    escalated: bool = False

    @property
    def end(self) -> int:
        return self.start + len(self.surface)


@dataclass(frozen=True)
class RunResult:
    scene_id: str
    decisions: list[Decision]
    # mention start (gold or system) -> candidate ids, best first
    candidates: dict[int, list[str]]
    usage: dict
