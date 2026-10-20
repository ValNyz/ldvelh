"""Value types and failures of the identity service (spec §4.4, §4.11).

A failure never carries story text in its message: a reference or a name is story text
(never logged above DEBUG), so `str()` of these exceptions names only types, tables, ids
and codes, and `write_item` records their `code` in stats.errors.
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
    protagonist knows the name; `secret`: the entity is guarded by the Director (every
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
class ResolvedRef:
    """A resolved entity: its id, its E<n> handle and what the player may read for it."""

    entity_id: UUID
    handle: int
    label: str


class IdentityWriteMiss(Exception):
    """A write by id found no row (UPDATE 0): the entity is gone or of another type."""

    code = "write_miss"

    def __init__(self, table: str, entity_id: UUID, game_id: UUID | None = None):
        super().__init__(f"no {table} row {entity_id}")
        self.table = table
        self.entity_id = entity_id
        self.game_id = game_id


class RefUnresolved(Exception):
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
        super().__init__(f"unresolved {entity_type} reference")
        self.ref = ref
        self.entity_type = entity_type
        self.game_id = game_id
        self.candidates = candidates
