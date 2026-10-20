"""Conversations and messages: SQL only, on the caller's connection."""

from __future__ import annotations

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
