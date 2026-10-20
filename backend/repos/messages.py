"""Conversations and messages: SQL only, on the caller's connection."""

from __future__ import annotations

import json
from uuid import UUID


async def insert_conversation(conn, game_id: UUID, start_cycle: int) -> UUID:
    return await conn.fetchval(
        "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, $2) RETURNING id",
        game_id,
        start_cycle,
    )


async def insert_message(
    conn, game_id: UUID, conversation_id: UUID, role: str, content: str, sequence: int
) -> UUID:
    return await conn.fetchval(
        """INSERT INTO messages (game_id, conversation_id, role, content, sequence)
           VALUES ($1, $2, $3, $4, $5) RETURNING id""",
        game_id,
        conversation_id,
        role,
        content,
        sequence,
    )


async def recent_assistant_messages(
    conn, game_id: UUID, message_id: UUID, limit: int
) -> list[UUID]:
    """The `limit` latest narrator messages of the game before `message_id` (latest
    first; the game's latest ones when `message_id` is not stored)."""
    rows = await conn.fetch(
        """SELECT id FROM messages
            WHERE game_id = $1 AND role = 'assistant' AND id <> $2
              AND sequence < coalesce((SELECT sequence FROM messages WHERE id = $2),
                                      2147483647)
            ORDER BY sequence DESC, created_at DESC
            LIMIT $3""",
        game_id,
        message_id,
        limit,
    )
    return [r["id"] for r in rows]


async def scene_location(conn, game_id: UUID, message_id: UUID) -> UUID | None:
    """The place of a message: its own, else the game's current location."""
    return await conn.fetchval(
        """SELECT coalesce((SELECT location_id FROM messages WHERE id = $2),
                           (SELECT current_location_id FROM games WHERE id = $1))""",
        game_id,
        message_id,
    )


async def set_narrator_context(conn, message_id: UUID, annotations: list) -> None:
    """The legacy span annotations of a message, [start, end, label, type] each (written
    next to entity_mentions until the column goes, spec §4.9)."""
    await conn.execute(
        "UPDATE messages SET narrator_context = $1 WHERE id = $2",
        annotations,
        message_id,
    )


async def narrator_deltas(conn, message_id: UUID) -> dict:
    """The narrator deltas stored with a message ({} when none)."""
    row = await conn.fetchval(
        "SELECT narrator_deltas FROM messages WHERE id = $1", message_id
    )
    return json.loads(row) if isinstance(row, str) else (row or {})


async def set_narrator_deltas(conn, message_id: UUID, deltas: dict) -> None:
    await conn.execute(
        "UPDATE messages SET narrator_deltas = $1 WHERE id = $2", deltas, message_id
    )
