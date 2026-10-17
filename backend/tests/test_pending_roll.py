"""Pending Fate roll: resolved once, not dodgeable, restored on reload (#32)."""

from uuid import UUID

from pipeline import turn
from repos import turns
from tests.characterization import payloads
from tests.characterization.harness import spy_narration
from tests.plugins.pending_roll import PENDING_ACTION as ACTION

HIGH_CONCEPT = "Pilote déchu en quête de rédemption"
TROUBLE = "Je dois de l'argent à tout le monde"


async def _fate_points(harness, game_id):
    async with harness.pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id)


async def _messages(harness, game_id):
    async with harness.pool.acquire() as conn:
        return await conn.fetch(
            "SELECT role, content FROM messages WHERE game_id = $1 ORDER BY created_at, sequence",
            game_id)


def _errors(events):
    return [e for e in events if e["type"] == "error"]


async def test_resume_twice_applies_once(harness, pending):
    game_id, event = pending
    first = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                               invoked_aspects=[HIGH_CONCEPT])
    await harness.drain()
    assert "done" in harness.summarize(first)
    assert await _fate_points(harness, game_id) == 2

    second = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                                invoked_aspects=[HIGH_CONCEPT])
    await harness.drain()
    errors = _errors(second)
    assert [e.get("code") for e in errors] == ["roll_not_pending"], second
    assert errors[0]["error"] == "Ce jet n'est plus en attente."
    assert "done" not in harness.summarize(second)
    assert await _fate_points(harness, game_id) == 2


async def test_chat_while_roll_pending_resends_the_modal(harness, pending):
    game_id, event = pending
    before = len(await _messages(harness, game_id))
    events = await harness.chat(game_id, "Je fais autre chose.")
    await harness.drain()
    assert harness.summarize(events) == ["roll_pending"]
    again = events[0]
    assert again["roll_id"] == event["roll_id"]
    assert again["roll"] == event["roll"]
    assert again["fate_points"] == 3
    assert HIGH_CONCEPT in again["aspects"]
    assert "mechanical" not in harness.llm.purposes()
    assert len(await _messages(harness, game_id)) == before


async def test_resume_uses_the_stored_message(harness, pending, monkeypatch):
    game_id, event = pending
    narration_calls = spy_narration(monkeypatch)
    events = await harness.chat(game_id, "autre chose", roll_id=event["roll_id"],
                                invoked_aspects=[])
    await harness.drain()
    assert "done" in harness.summarize(events)
    sent = str(narration_calls[-1]["messages"])
    assert f"> {ACTION}" in sent and "> autre chose" not in sent
    user_messages = [m["content"] for m in await _messages(harness, game_id) if m["role"] == "user"]
    assert user_messages[-1] == ACTION
    assert "autre chose" not in user_messages


async def test_loaded_state_exposes_pending_roll(harness, pending):
    game_id, event = pending
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.status_code == 200, r.text
    stored = r.json()["state"]["pending_roll"]
    assert stored["roll_id"] == event["roll_id"]
    assert stored["roll"] == event["roll"]
    assert stored["fate_points"] == 3
    assert stored["aspects"] == event["aspects"]

    await harness.chat(game_id, ACTION, roll_id=event["roll_id"], invoked_aspects=[])
    await harness.drain()
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.json()["state"]["pending_roll"] is None


async def test_overspend_is_rejected_and_fp_unchanged(harness, pending):
    game_id, event = pending
    async with harness.pool.acquire() as conn:
        await conn.execute("UPDATE character_fate SET fate_points = 1 WHERE game_id = $1", game_id)
    events = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                                invoked_aspects=[HIGH_CONCEPT, TROUBLE])
    await harness.drain()
    errors = _errors(events)
    assert [e.get("code") for e in errors] == ["invalid_invocation"], events
    assert "done" not in harness.summarize(events)
    assert await _fate_points(harness, game_id) == 1
    # The roll is still waiting: the player can choose again.
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.json()["state"]["pending_roll"]["roll_id"] == event["roll_id"]


async def test_loaded_pending_roll_carries_the_stored_action(harness, pending):
    """The frontend shows the waiting action in the chat after a reload."""
    game_id, event = pending
    assert event["player_message"] == ACTION
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.json()["state"]["pending_roll"]["player_message"] == ACTION


async def test_resume_with_empty_message_saves_the_stored_action(harness, pending):
    """After a reload the frontend has no last message: it resumes with message=""."""
    game_id, event = pending
    events = await harness.chat(game_id, "", roll_id=event["roll_id"],
                                invoked_aspects=[HIGH_CONCEPT])
    await harness.drain()
    assert "done" in harness.summarize(events), events
    user_messages = [m["content"] for m in await _messages(harness, game_id) if m["role"] == "user"]
    assert user_messages[-1] == ACTION
    assert "" not in user_messages


async def test_invoked_aspects_are_stored_with_their_sheet_name(harness, pending):
    game_id, event = pending
    events = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                                invoked_aspects=["pilote dechu en quete de redemption"])
    await harness.drain()
    roll = next(e["roll"] for e in events if e["type"] == "roll_result")
    assert roll["details"]["invoked_aspects"] == [HIGH_CONCEPT]
    async with harness.pool.acquire() as conn:
        stored = await conn.fetchval(
            "SELECT roll_details FROM mechanic_rolls WHERE id = $1::uuid", event["roll_id"])
    assert stored["details"]["invoked_aspects"] == [HIGH_CONCEPT]


async def test_rollback_expires_the_pending_roll(harness, pending):
    """R12: the modal of a rolled-back action does not come back; the next turn rolls anew."""
    game_id, event = pending
    r = await harness.client.post(f"/api/games/{game_id}/rollback", json={"fromIndex": 2},
                                  headers=harness.headers)
    assert r.status_code == 200, r.text
    assert r.json()["state"]["pending_roll"] is None
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.json()["state"]["pending_roll"] is None
    async with harness.pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM mechanic_rolls WHERE id = $1::uuid", event["roll_id"])
    assert status == "expired"

    harness.llm._responses["mechanical"] = payloads.mechanical(requires_test=False)
    events = await harness.chat(game_id, "Je fais demi-tour.")
    await harness.drain()
    assert "done" in harness.summarize(events), harness.summarize(events)
    assert "roll_pending" not in harness.summarize(events)
    assert "mechanical" in harness.llm.purposes()


async def test_claim_refused_at_commit_writes_nothing(harness, pending, monkeypatch):
    """Defence in depth: a roll claimed by a concurrent turn fails this one, untouched."""
    game_id, event = pending
    before = len(await _messages(harness, game_id))

    async def already_claimed(*args, **kwargs):
        return False

    monkeypatch.setattr(turns, "claim_pending_roll", already_claimed)
    events = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                                invoked_aspects=[HIGH_CONCEPT])
    await harness.drain()
    assert [e.get("code") for e in _errors(events)] == ["roll_not_pending"], events
    assert "done" not in harness.summarize(events)
    assert await _fate_points(harness, game_id) == 3
    assert len(await _messages(harness, game_id)) == before


async def test_fate_points_spent_elsewhere_before_commit(harness, pending, monkeypatch):
    """The guarded debit refuses the turn when the balance dropped after arbitrate."""
    game_id, event = pending
    before = len(await _messages(harness, game_id))
    original = turn.commit_turn

    async def drain_fate_points_then_commit(*args, **kwargs):
        async with harness.pool.acquire() as conn:
            await conn.execute(
                "UPDATE character_fate SET fate_points = 0 WHERE game_id = $1", game_id)
        return await original(*args, **kwargs)

    monkeypatch.setattr(turn, "commit_turn", drain_fate_points_then_commit)
    events = await harness.chat(game_id, ACTION, roll_id=event["roll_id"],
                                invoked_aspects=[HIGH_CONCEPT])
    await harness.drain()
    assert [e.get("code") for e in _errors(events)] == ["invalid_invocation"], events
    assert "done" not in harness.summarize(events)
    assert await _fate_points(harness, game_id) == 0
    assert len(await _messages(harness, game_id)) == before
    async with harness.pool.acquire() as conn:
        assert (await turns.get_pending_roll(conn, game_id))["id"] == UUID(event["roll_id"])


async def test_concurrent_pending_roll_is_offered_again(harness, pending, monkeypatch):
    """A pending roll stored after load (unique index hit): the stored one is offered again."""
    from pipeline.steps import load

    game_id, event = pending

    async def stale_load(*args, **kwargs):
        return None  # load ran before the other pending roll was stored

    monkeypatch.setattr(load, "load_pending_roll", stale_load)
    events = await harness.chat(game_id, "Je fais autre chose.")
    await harness.drain()

    assert harness.summarize(events) == ["roll_pending"], events
    assert events[0]["roll_id"] == event["roll_id"]
    assert events[0]["roll"] == event["roll"]
    async with harness.pool.acquire() as conn:
        pending_rows = await conn.fetchval(
            "SELECT count(*) FROM mechanic_rolls WHERE game_id = $1 AND status = 'pending'",
            UUID(game_id))
    assert pending_rows == 1


async def test_other_unique_violation_is_not_taken_for_a_pending_roll(harness, pending, monkeypatch):
    """Only the one-pending-per-game index means "a roll already waits"; others stay errors."""
    import asyncpg

    from pipeline.steps import load

    game_id, _ = pending

    async def stale_load(*args, **kwargs):
        return None

    async def other_violation(*args, **kwargs):
        exc = asyncpg.UniqueViolationError("duplicate key")
        exc.constraint_name = "mechanic_rolls_some_other_key"
        raise exc

    monkeypatch.setattr(load, "load_pending_roll", stale_load)
    monkeypatch.setattr(turns, "store_pending_roll", other_violation)
    events = await harness.chat(game_id, "Je fais autre chose.")
    await harness.drain()

    assert [e.get("code") for e in _errors(events)] == ["internal"], events
    assert "roll_pending" not in harness.summarize(events)
