"""
LDVELH - References resolved at the edge of a knowledge-graph write.

Extracted and generated items name entities with words (a handle `E<n>`, a label, an
alias, PROTAGONIST); the populator writes by id. These helpers turn a reference into an
id through IdentityService, never by guessing:
- `required`: the item cannot be written without it (a fact participant, a relation end):
  RefUnresolved propagates, `write_item` rolls the item back and counts `ref_dropped`.
- `optional`: the item stands without it (a fact's place, an event participant): an
  unresolved reference is counted the same way, in its own savepoint, and the item is
  written without it.
`entity_type` None means an untyped reference (any type may hold it, exactly one must).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from .item_writes import write_item

if TYPE_CHECKING:
    from asyncpg import Connection

    from services.identity.service import IdentityService
    from services.identity.types import ResolvedRef


async def resolve(
    identity: IdentityService, conn: Connection, ref: str, entity_type: str | None
) -> ResolvedRef:
    """The entity `ref` names; RefUnresolved when none or several do."""
    if entity_type is None:
        return await identity.require_any_ref(conn, ref)
    return await identity.require_ref(conn, ref, entity_type)


async def required(
    identity: IdentityService,
    conn: Connection,
    ref: str,
    entity_type: str | None = None,
) -> UUID:
    """Id of the entity `ref` names; RefUnresolved when none or several do."""
    return (await resolve(identity, conn, ref, entity_type)).entity_id


async def optional(
    identity: IdentityService,
    conn: Connection,
    errors: list[str | dict],
    label: str,
    ref: str | None,
    entity_type: str | None = None,
) -> UUID | None:
    """Id of the entity `ref` names; None when there is no reference, or when it is
    unresolved (then counted in `errors` as `ref_dropped` under `label`)."""
    if ref is None or not ref.strip():
        return None
    resolved = await write_item(
        conn, errors, label, lambda: resolve(identity, conn, ref, entity_type)
    )
    return resolved.entity_id if resolved is not None else None


async def optional_ids(
    identity: IdentityService,
    conn: Connection,
    errors: list[str | dict],
    label: str,
    refs: list[str] | None,
    entity_type: str | None = None,
) -> list[UUID]:
    """`optional` for each reference: the ids resolved, in order, without repeats."""
    ids: list[UUID] = []
    for ref in refs or ():
        entity_id = await optional(identity, conn, errors, label, ref, entity_type)
        if entity_id is not None and entity_id not in ids:
            ids.append(entity_id)
    return ids
