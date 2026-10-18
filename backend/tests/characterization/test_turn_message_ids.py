"""#55: the done event names the turn's saved messages, so the client can edit or regenerate it."""

from uuid import UUID


async def _last_two_messages(harness, game_id):
    async with harness.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT m.id, m.role FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE c.game_id = $1 ORDER BY m.sequence DESC LIMIT 2""",
            game_id)
    return {r["role"]: r["id"] for r in rows}


async def test_done_carries_the_ids_of_the_saved_turn(harness, world_game):
    events = await harness.chat(world_game, "Je regarde autour de moi.")
    await harness.drain()

    done = next(e for e in events if e["type"] == "done")
    meta = done["state"]["meta"]
    saved = await _last_two_messages(harness, world_game)
    assert UUID(meta["user_message_id"]) == saved["user"]
    assert UUID(meta["assistant_message_id"]) == saved["assistant"]


async def test_a_legacy_client_game_state_is_ignored(harness, world_game):
    # A frontend cached before #55 still sends gameState: it must not get a 422 during a deploy.
    events = await harness.chat(world_game, "Je regarde autour de moi.",
                                gameState={"game": {"current_cycle": 99}})
    await harness.drain()

    done = next(e for e in events if e["type"] == "done")
    # Ignored, not merged: the state comes from the database.
    assert done["state"]["game_state"]["game"]["current_cycle"] != 99
