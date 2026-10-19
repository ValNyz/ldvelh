"""Every narration request opens a turn; its writes are journaled under that turn's id
and a rollback deletes the turns of the messages it deletes (#105)."""

import json
from types import SimpleNamespace
from uuid import UUID

from repos import turns
from services.engine import fate_core
from tests.characterization import payloads
from tests.helpers import rollback_last_turn


async def _turns(conn, game_id) -> list[dict]:
    rows = await conn.fetch(
        "SELECT id, status, committed_at FROM turns WHERE game_id = $1 ORDER BY created_at",
        UUID(game_id) if isinstance(game_id, str) else game_id,
    )
    return [dict(r) for r in rows]


async def _changes(conn, turn_id) -> list[tuple]:
    rows = await conn.fetch(
        "SELECT table_name, op, old_row FROM world_changes WHERE turn_id = $1 ORDER BY id",
        turn_id,
    )
    return [
        (
            r["table_name"],
            r["op"],
            json.loads(r["old_row"]) if isinstance(r["old_row"], str) else r["old_row"],
        )
        for r in rows
    ]


async def test_a_turn_commits_under_its_turn_id(harness, world_game):
    game_id = UUID(world_game)
    async with harness.pool.acquire() as conn:
        changes_before = await conn.fetchval("SELECT count(*) FROM world_changes")
        turns_before = len(await _turns(conn, game_id))

    events = await harness.chat(world_game, "Je regarde autour.")
    await harness.drain()
    assert "done" in harness.summarize(events)

    async with harness.pool.acquire() as conn:
        all_turns = await _turns(conn, game_id)
        assert len(all_turns) == turns_before + 1
        turn = all_turns[-1]
        message_turns = await conn.fetch(
            "SELECT turn_id FROM messages WHERE game_id = $1 ORDER BY sequence DESC LIMIT 2",
            game_id,
        )
        changes_after = await conn.fetchval("SELECT count(*) FROM world_changes")
        journal = await _changes(conn, turn["id"])

    assert [r["turn_id"] for r in message_turns] == [turn["id"], turn["id"]]
    assert turn["status"] == "committed"
    assert turn["committed_at"] is not None
    assert ("games", "U") in [(t, op) for t, op, _ in journal]
    # Every journal row the turn created carries its id.
    assert changes_after - changes_before == len(journal)


async def test_a_halted_turn_stays_open_with_its_pending_roll_journaled(
    harness, fate_game, monkeypatch
):
    game_id = UUID(fate_game)
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4
    )
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    async with harness.pool.acquire() as conn:
        turns_before = len(await _turns(conn, game_id))

    events = await harness.chat(fate_game, "Je tente un saut impossible.")
    pending = next(e for e in events if e["type"] == "roll_pending")
    roll_id = UUID(pending["roll_id"])

    async with harness.pool.acquire() as conn:
        halted = (await _turns(conn, game_id))[turns_before:]
        roll_turn = await conn.fetchval(
            "SELECT turn_id FROM mechanic_rolls WHERE id = $1", roll_id
        )
        halted_journal = await _changes(conn, halted[0]["id"]) if halted else []
    assert [t["status"] for t in halted] == ["open"]
    assert roll_turn == halted[0]["id"]
    assert [(t, op) for t, op, _ in halted_journal] == [("mechanic_rolls", "I")]

    aspect = pending["aspects"][0]
    aspect_name = aspect["name"] if isinstance(aspect, dict) else aspect
    resumed = await harness.chat(
        fate_game, "autre chose", roll_id=str(roll_id), invoked_aspects=[aspect_name]
    )
    await harness.drain()
    assert "done" in harness.summarize(resumed)

    async with harness.pool.acquire() as conn:
        after = (await _turns(conn, game_id))[turns_before:]
        resume_journal = await _changes(conn, after[1]["id"])
        roll_turn = await conn.fetchval(
            "SELECT turn_id FROM mechanic_rolls WHERE id = $1", roll_id
        )
    assert [t["status"] for t in after] == ["open", "committed"]
    # The resumed roll belongs to the turn that resolves it.
    assert roll_turn == after[1]["id"]
    roll_updates = [
        old for t, op, old in resume_journal if (t, op) == ("mechanic_rolls", "U")
    ]
    assert len(roll_updates) == 1
    assert "status" in roll_updates[0]


async def test_failed_turn_leaves_an_open_turn_and_no_message(harness, world_game):
    game_id = UUID(world_game)
    async with harness.pool.acquire() as conn:
        turns_before = len(await _turns(conn, game_id))
        messages_before = await conn.fetchval(
            "SELECT count(*) FROM messages WHERE game_id = $1", game_id
        )
    harness.llm.fail_on["narration"] = RuntimeError("provider down")

    events = await harness.chat(world_game, "Ça va casser.")
    await harness.drain()
    harness.llm.fail_on.clear()

    assert [e["code"] for e in events if e["type"] == "error"] == ["provider_error"]
    async with harness.pool.acquire() as conn:
        failed = (await _turns(conn, game_id))[turns_before:]
        messages_after = await conn.fetchval(
            "SELECT count(*) FROM messages WHERE game_id = $1", game_id
        )
        journal = await _changes(conn, failed[0]["id"]) if failed else []
    assert [t["status"] for t in failed] == ["open"]
    assert messages_after == messages_before
    assert journal == []


async def test_rollback_deletes_the_turns_of_the_deleted_messages(harness, world_game):
    game_id = UUID(world_game)
    # Arrival (world_game) + this turn: two committed turns.
    await harness.chat(world_game, "Je regarde autour.")
    await harness.drain()
    async with harness.pool.acquire() as conn:
        played = await _turns(conn, game_id)
        journal_before = await conn.fetchval(
            "SELECT count(*) FROM world_changes WHERE turn_id = $1", played[1]["id"]
        )
        # An abandoned turn (client gone before the commit) is purged too.
        await turns.open_turn(conn, game_id)
    assert [t["status"] for t in played] == ["committed", "committed"]
    assert journal_before > 0

    await rollback_last_turn(harness, game_id)

    async with harness.pool.acquire() as conn:
        left = await _turns(conn, game_id)
        orphan_journal = await conn.fetchval(
            "SELECT count(*) FROM world_changes WHERE turn_id = $1", played[1]["id"]
        )
    assert [(t["id"], t["status"]) for t in left] == [(played[0]["id"], "committed")]
    assert orphan_journal == 0
