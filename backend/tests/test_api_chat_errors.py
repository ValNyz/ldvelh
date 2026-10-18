"""/api/chat errors raised before any pipeline step, as the player sees them on the stream."""

from uuid import UUID

from services.game_service import GameService


async def test_game_deleted_after_the_ownership_check_sends_game_not_found(harness, monkeypatch):
    """The game vanishes between the ownership check and the snapshot: one French error."""
    game_id = await harness.create_game("none")
    original = GameService.verify_ownership

    async def verify_then_delete(self, gid, user_id):
        await original(self, gid, user_id)
        await self.delete_game(gid)

    monkeypatch.setattr(GameService, "verify_ownership", verify_then_delete)
    events = await harness.chat(game_id, "Je regarde autour de moi.")
    await harness.drain()

    assert harness.summarize(events) == ["error"]
    error = events[0]
    assert (error["code"], error["error"], error["recoverable"]) == (
        "game_not_found", "Partie introuvable.", False)
    assert error["ref"]
    assert harness.llm.calls == []
    async with harness.pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM games WHERE id = $1", UUID(game_id)) == 0


async def test_wizard_name_with_reserved_characters_is_refused_before_the_stream(harness):
    """#28: '<'/'>' and the reserved PROTAGONIST reference are refused at the API boundary."""
    game_id = await harness.create_game("none")
    for name in ("<x>", "Kira>", " protagonist "):
        r = await harness.client.post("/api/chat", headers=harness.headers, json={
            "message": "__INIT__", "gameId": game_id, "engine": "none",
            "character_data": {"name": name}})
        assert r.status_code == 400, (name, r.text)
        assert r.json()["detail"].startswith("Nom du protagoniste invalide"), r.text
    assert harness.llm.calls == []
