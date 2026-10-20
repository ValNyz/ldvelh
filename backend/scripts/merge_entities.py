"""Merge two duplicate entities of a game by hand (operator tool, #153).

Offline: it never runs against a database unless --database-url is given. It shows the two
entity cards and the edges that would move, asks for confirmation (unless --yes) and calls
IdentityService.merge outside any turn, in one transaction. The merge is audited in
entity_merges and is NOT undone by a turn rollback: take a backup first (CONTRIBUTING,
"Merging duplicates").

Usage (from backend/):
  python -m scripts.merge_entities --database-url postgres://... --game GAME_UUID \\
      --keep E12 --drop E31 --reason "same person" [--yes]

--keep and --drop take a handle (`E<n>`, as in the prompts and the tooltips) or an entity
uuid. The cards show names: the operator owns the data. Nothing but ids and codes is logged.
"""

import argparse
import asyncio
import re
import sys
from uuid import UUID

_HANDLE = re.compile(r"^[Ee]([0-9]{1,9})$")


async def _entity_id(conn, game_id: UUID, ref: str) -> UUID:
    """The entity a handle (`E<n>`) or a uuid names in this game; SystemExit otherwise."""
    from repos import entities

    match = _HANDLE.match(ref)
    try:
        entity_id = (
            await entities.entity_by_handle(conn, game_id, int(match.group(1)))
            if match
            else UUID(ref)
        )
    except ValueError:
        entity_id = None
    row = await entities.get_registry(conn, game_id, entity_id) if entity_id else None
    if row is None:
        raise SystemExit(f"no entity {ref!r} in game {game_id}")
    return row.id


async def _card(conn, game_id: UUID, entity_id: UUID, role: str) -> None:
    from repos import entities

    row = await entities.get_registry(conn, game_id, entity_id)
    domain = await entities.domain_row(conn, row.entity_type, entity_id) or {}
    shown = await entities.display_for_player(conn, entity_id)
    state = (
        "" if row.merged_into is None else f"  [already merged into {row.merged_into}]"
    )
    print(f"{role}: E{row.handle}  {row.entity_type}  {entity_id}{state}")
    print(f"  label: {row.name}")
    print(f"  shown to the player: {shown}")
    for column in ("true_name", "descriptor", "name"):
        if domain.get(column):
            print(f"  {column}: {domain[column]}")
    for alias in await entities.list_aliases(conn, game_id, entity_id):
        flags = ("known" if alias.known else "hidden") + (
            ", secret" if alias.secret else ""
        )
        print(f"  alias ({alias.kind}, {flags}): {alias.alias}")
    for label, count in (await entities.edge_counts(conn, entity_id)).items():
        print(f"  {label}: {count}")


async def _main(args: argparse.Namespace) -> int:
    import asyncpg

    from repos import entities
    from services.identity import merges
    from services.identity.service import IdentityService

    conn = await asyncpg.connect(args.database_url)
    try:
        keep = await _entity_id(conn, args.game, args.keep)
        drop = await _entity_id(conn, args.game, args.drop)
        service = await IdentityService.for_game(conn, args.game)
        print(
            "Take a backup of the database before a merge: it is not undone by a rollback."
        )
        await _card(conn, args.game, keep, "KEEP")
        await _card(conn, args.game, drop, "DROP")
        print("Edges of DROP above move to KEEP (duplicates are closed or merged).")
        refused = await merges.refusal(service, conn, keep, drop)
        if refused:
            print(f"The guards refuse this merge: {refused}")
        if not args.yes:
            answer = await asyncio.to_thread(input, "Merge DROP into KEEP? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("Cancelled: nothing was changed.")
                return 1
        async with conn.transaction():
            outcome = await service.merge(
                conn, keep, drop, reason=args.reason, turn_id=None
            )
        if outcome.refused:
            print(f"Refused ({outcome.refused}): nothing was merged.")
            return 1
        print(f"Merged. entity_merges id: {outcome.merge_id}")
        handle = await entities.handle_of(conn, keep)
        print(f"E{handle} now carries the edges and names of both entities.")
    finally:
        await conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--game", type=UUID, required=True)
    parser.add_argument(
        "--keep", required=True, help="E<n> or uuid of the entity to keep"
    )
    parser.add_argument("--drop", required=True, help="E<n> or uuid of the duplicate")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation")
    return parser


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
