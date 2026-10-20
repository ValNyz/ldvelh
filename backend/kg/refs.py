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
`entity_type` None means an untyped reference (any type may hold it, exactly one must),
always resolved live first (`IdentityService.require_any_live_ref`): the live homonym of a
removed entity is found by its name, a name only removed entities hold may name one.
`live`: the reference is a write target (a place, a seat, an inventory object): an entity
removed from the world does not count, it is unresolved (`ref_dropped`, its event counting
the removed entities named) like an unknown one.
`live_first`: the reference names the entity a write changes (an update, a removal, an
ambient update): a live entity first, so the live homonym of a removed entity is reached
by its name; a name no live entity holds may still name one removed entity (removing it
again is a no-op, not an error).

An optional reference resolved inside an item's savepoint has its `ref_dropped` event
written inside that item: if the item itself then fails, the event goes with it while the
`errors` entry stays (the event belongs to the item; the world generation and the turn
commit resolve their optional references before any item they feed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from .item_writes import write_item

if TYPE_CHECKING:
    from asyncpg import Connection

    from services.identity.service import IdentityService
    from domain.identity import ResolvedRef


async def resolve(
    identity: IdentityService,
    conn: Connection,
    ref: str,
    entity_type: str | None,
    *,
    live: bool = False,
    live_first: bool = False,
) -> ResolvedRef:
    """The entity `ref` names; RefUnresolved when none or several do. Untyped: live
    first, a removed entity as a fallback only. With `live` (a
    typed write target), only entities not removed from the world count: a removed one
    is unresolved, and a live homonym of a removed entity is still found. With
    `live_first`, the same, but a name only one removed entity holds resolves to it."""
    if entity_type is None:
        return await identity.require_any_live_ref(conn, ref)
    if not (live or live_first):
        return await identity.require_ref(conn, ref, entity_type)
    return await identity.require_live_ref(
        conn, ref, entity_type, or_removed=live_first
    )


async def required(
    identity: IdentityService,
    conn: Connection,
    ref: str,
    entity_type: str | None = None,
    *,
    live: bool = False,
    live_first: bool = False,
) -> UUID:
    """Id of the entity `ref` names; RefUnresolved when none or several do."""
    resolved = await resolve(
        identity, conn, ref, entity_type, live=live, live_first=live_first
    )
    return resolved.entity_id


async def optional(
    identity: IdentityService,
    conn: Connection,
    errors: list[str | dict],
    label: str,
    ref: str | None,
    entity_type: str | None = None,
    *,
    live: bool = False,
) -> UUID | None:
    """Id of the entity `ref` names; None when there is no reference, or when it is
    unresolved (then counted in `errors` as `ref_dropped` under `label`)."""
    if ref is None or not ref.strip():
        return None
    resolved = await write_item(
        conn,
        errors,
        label,
        lambda: resolve(identity, conn, ref, entity_type, live=live),
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
