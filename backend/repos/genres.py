"""Genres a user may pick: the presets and the user's own."""

from __future__ import annotations

from uuid import UUID

# A genre the user may see: a preset or one of theirs ($1 the user).
_VISIBLE = "(is_preset = true OR user_id = $1)"


async def visible_genres(conn, user_id: UUID) -> list[dict]:
    """The genres the user may pick, presets first, then by label."""
    rows = await conn.fetch(
        f"""SELECT id, slug, label, is_preset, world_type
              FROM genres
             WHERE {_VISIBLE}
             ORDER BY is_preset DESC, label ASC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def visible_genre(conn, user_id: UUID, genre_id: UUID) -> dict | None:
    """Every column of a genre the user may see (None: unknown or not theirs)."""
    row = await conn.fetchrow(
        f"SELECT * FROM genres WHERE id = $2 AND {_VISIBLE}", user_id, genre_id
    )
    return dict(row) if row else None
