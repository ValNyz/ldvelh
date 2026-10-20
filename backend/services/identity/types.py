"""Value types and failures of the identity service (spec §4.4, §4.11).

A failure never carries story text in its message: a reference or a name is story text
(never logged above DEBUG), so `str()` of these exceptions names only types, tables, ids
and codes. `write_item` catches every IdentityFailure, records its `code` in stats.errors
and writes an identity_events row of that kind with its `payload()`, after rolling the
item back (so the row survives).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from services.identity.aliases import AliasSpec


@dataclass(frozen=True)
class NewEntitySpec:
    """An entity to create. `kind`: its label is a proper name (a character's true name,
    another entity's name) or a descriptor (what the protagonist sees). `known`: the
    protagonist knows the name; for a descriptor character it applies to the aliases only
    (a descriptor is always known) and known_by_protagonist is always false, since the
    character has no true name to know yet. `secret`: the entity is guarded by the Director (every
    alias made at its creation is secret). `fields`: other columns of its domain row."""

    entity_type: str
    label: str
    kind: Literal["proper_name", "descriptor"]
    known: bool = True
    secret: bool = False
    fields: dict = field(default_factory=dict)
    aliases: list[AliasSpec] = field(default_factory=list)


@dataclass(frozen=True)
class EntityRef:
    ref: str
    entity_type: str


@dataclass(frozen=True)
class FactRef:
    ref: str


@dataclass(frozen=True)
class RevealOutcome:
    """What a reveal did (spec §4.7). `applied`: a true name set; `known_only`: the
    protagonist now knows (or already knew) the name the entity has; `noop`: nothing to
    reveal, or no entity resolved; `conflict`: the narration's name replaced another one;
    `merged`: the name was another entity's, the two were merged into `merged_into` (the
    live entity, possibly `entity_id` itself); `merge_refused`: the same, but a guard
    refused the merge. `entity_id`: the entity the reference named (None: unresolved)."""

    kind: Literal[
        "applied", "known_only", "noop", "conflict", "merged", "merge_refused"
    ]
    entity_id: UUID | None
    merged_into: UUID | None = None


@dataclass(frozen=True)
class MergeOutcome:
    """A merge: its entity_merges id, or the code of the guard that refused it."""

    merge_id: UUID | None
    refused: str | None


@dataclass(frozen=True)
class ResolvedRef:
    """A resolved entity: its id, its E<n> handle and what the player may read for it."""

    entity_id: UUID
    handle: int
    label: str


class IdentityFailure(Exception):
    """An identity write refused or impossible; `write_item` counts it under `code`."""

    code = "identity_failure"

    def __init__(self, message: str, game_id: UUID | None):
        super().__init__(message)
        self.game_id = game_id

    def payload(self) -> dict:
        """The identity_events payload: types, counts, ids and codes, never story text."""
        return {}

    def debug_detail(self) -> str | None:
        """Story text for a DEBUG log, if any."""
        return None


class IdentityWriteMiss(IdentityFailure):
    """A write by id found no row (UPDATE 0): the entity is gone or of another type."""

    code = "write_miss"

    def __init__(self, table: str, entity_id: UUID, game_id: UUID | None = None):
        super().__init__(f"no {table} row {entity_id}", game_id)
        self.table = table
        self.entity_id = entity_id

    def payload(self) -> dict:
        return {"table": self.table, "entity_id": str(self.entity_id)}


class RefUnresolved(IdentityFailure):
    """A required reference names no entity of its type (`candidates` 0), or several
    (ambiguous: 2 or more). `ref` is story text: it is kept on the exception for DEBUG logs
    only, never in its message."""

    code = "ref_dropped"

    def __init__(
        self,
        ref: str,
        entity_type: str,
        game_id: UUID | None = None,
        *,
        candidates: int = 0,
    ):
        super().__init__(f"unresolved {entity_type} reference", game_id)
        self.ref = ref
        self.entity_type = entity_type
        self.candidates = candidates

    def payload(self) -> dict:
        return {"entity_type": self.entity_type, "candidates": self.candidates}

    def debug_detail(self) -> str | None:
        return repr(self.ref)


class AmbiguousLabel(IdentityFailure):
    """A creation refused: only aliases of several entities hold the label, so it may name
    any of them (« dans le doute, on ne crée pas »). `label` is story text, DEBUG only.

    Nothing records it when it is raised: `write_item` writes its durable identity_events
    row (kind `create_ambiguous`, after rolling the item back). A caller that runs
    create_entity outside write_item must record that event itself."""

    code = "create_ambiguous"

    def __init__(
        self,
        label: str,
        entity_type: str,
        game_id: UUID | None = None,
        *,
        candidates: int,
        source: str,
    ):
        super().__init__(f"ambiguous {entity_type} label", game_id)
        self.label = label
        self.entity_type = entity_type
        self.candidates = candidates
        self.source = source

    def payload(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "candidates": self.candidates,
            "source": self.source,
        }

    def debug_detail(self) -> str | None:
        return repr(self.label)
