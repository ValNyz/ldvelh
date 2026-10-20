"""
LDVELH - Fate Core protagonist aspects (aspects_fate table, #93)
Each aspect stores its kind: one high concept, one trouble, any number of others.
"""

from uuid import UUID

from schema.coerce import coerce_json_list

KINDS = ("high_concept", "trouble", "other")
# Player- and narrator-facing labels of the kinds
KIND_LABELS = {"high_concept": "Concept", "trouble": "Problème", "other": "Aspect"}


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def aspect_pairs(raw) -> list[tuple[str, str]]:
    """(kind, name) pairs from wizard data or a sheet's aspect list, blanks dropped.

    The wizard sends {"high_concept", "trouble", "other": [...]}: an empty slot simply has
    no aspect, nothing moves into it. A list holds {"name"|"text", "type"} dicts (get_stats)
    or plain names (older callers), typed as "other"; a kind already taken becomes "other".
    """
    if isinstance(raw, dict):
        pairs = [("high_concept", _text(raw.get("high_concept"))),
                 ("trouble", _text(raw.get("trouble")))]
        pairs += [("other", _text(o)) for o in (raw.get("other") or [])]
    else:
        pairs = []
        for item in coerce_json_list(raw):
            if isinstance(item, dict):
                kind = item.get("type") if item.get("type") in KINDS else "other"
                pairs.append((kind, _text(item.get("name")) or _text(item.get("text"))))
            else:
                pairs.append(("other", _text(item)))
    taken, result = set(), []
    for kind, name in pairs:
        if not name:
            continue
        if kind in taken and kind != "other":
            kind = "other"
        taken.add(kind)
        result.append((kind, name))
    return result


async def insert_aspects(conn, game_id: UUID, aspects: list[tuple[str, str]]) -> None:
    await conn.executemany(
        "INSERT INTO aspects_fate (game_id, position, name, kind) VALUES ($1, $2, $3, $4)",
        [(game_id, pos, name, kind) for pos, (kind, name) in enumerate(aspects)],
    )


async def load_aspects(conn, game_id: UUID) -> list[dict]:
    """Aspects in sheet order as {"type": kind, "name"} (the FateAspect shape)."""
    rows = await conn.fetch(
        "SELECT name, kind FROM aspects_fate WHERE game_id = $1 ORDER BY position", game_id)
    return [{"type": r["kind"], "name": r["name"]} for r in rows]


async def rename_aspect(conn, game_id: UUID, old_name: str, new_name: str) -> bool:
    """Rename in place: kind and position are kept. False when no aspect has that name."""
    status = await conn.execute(
        """
        UPDATE aspects_fate SET name = $3
        WHERE id = (SELECT id FROM aspects_fate WHERE game_id = $1 AND name = $2
                    ORDER BY position LIMIT 1)
        """,
        game_id, old_name, new_name,
    )
    return status.endswith(" 1")
