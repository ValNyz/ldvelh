"""Merging two entities into one (spec §4.7): the policy guards, then the SQL merge.

The guards live here, in code: same type, neither the protagonist nor the companion, not
two mandatory entities, neither already merged. `merge_entities` (SQL) only checks
integrity, re-points every edge, moves the aliases, leaves a tombstone on the dropped
registry row, deletes its domain row, and writes the entity_merges audit row and the
'merge' event. Every write is journaled by the P5a triggers: undoing the turn
(`world_changes_undo`) restores both entities and their edges.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from domain.identity import MergeOutcome
from repos import entities

if TYPE_CHECKING:
    from services.identity.service import IdentityService

logger = logging.getLogger(__name__)

# Entities made by game creation: never merged (spec §4.10).
UNMERGEABLE_TYPES = frozenset({"protagonist", "companion"})
_MANDATORY = "is_mandatory"


async def refusal(
    service: IdentityService, conn, keep_id: UUID, drop_id: UUID
) -> str | None:
    """The code of the first guard that refuses merging `drop_id` into `keep_id`, None
    when the merge may go ahead."""
    if keep_id == drop_id:
        return "same_entity"
    keep = await entities.get_registry(conn, service.game_id, keep_id)
    drop = await entities.get_registry(conn, service.game_id, drop_id)
    if keep is None or drop is None:
        return "missing"
    if {keep.entity_type, drop.entity_type} & UNMERGEABLE_TYPES:
        return "reserved_type"
    if keep.entity_type != drop.entity_type:
        return "type_mismatch"
    if keep.merged_into is not None or drop.merged_into is not None:
        return "already_merged"
    keep_row = await entities.domain_row(conn, keep.entity_type, keep_id) or {}
    drop_row = await entities.domain_row(conn, drop.entity_type, drop_id) or {}
    if keep_row.get(_MANDATORY) and drop_row.get(_MANDATORY):
        return "both_mandatory"
    return None


async def merge(
    service: IdentityService,
    conn,
    keep_id: UUID,
    drop_id: UUID,
    *,
    reason: str | None,
    turn_id: UUID | None,
    evidence: str | None,
) -> MergeOutcome:
    """Merge `drop_id` into `keep_id` when the guards allow it (event 'merge', written by
    the SQL merge), else nothing is written but a 'merge_refused' event."""
    refused = await refusal(service, conn, keep_id, drop_id)
    if refused is not None:
        await service.record_event(
            conn,
            "merge_refused",
            turn_id,
            keep_id,
            {"dropped_id": str(drop_id), "refused": refused},
            once=True,
        )
        logger.info(
            f"[IDENTITY] merge refused game={service.game_id} keep={keep_id}"
            f" drop={drop_id} refused={refused}"
        )
        return MergeOutcome(None, refused)
    return MergeOutcome(
        await apply(service, conn, keep_id, drop_id, reason=reason, evidence=evidence),
        None,
    )


async def apply(
    service: IdentityService,
    conn,
    keep_id: UUID,
    drop_id: UUID,
    *,
    reason: str | None,
    evidence: str | None,
) -> UUID:
    """The SQL merge, for a caller that already ran `refusal` (no guard run twice);
    returns the entity_merges id."""
    merge_id = await entities.merge_entities(conn, keep_id, drop_id, reason, evidence)
    logger.info(
        f"[IDENTITY] merged game={service.game_id} keep={keep_id} drop={drop_id}"
        f" merge={merge_id}"
    )
    return merge_id
