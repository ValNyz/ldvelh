"""The rollback replays the turn journal (#22); ROLLBACK_ENGINE=cycle keeps the old path."""

import ast
import inspect
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

from config import get_settings
from repos import turns
from services import rollback
from services.engine import fate_core
from services.game_service import GameService
from tests.characterization import payloads
from tests.helpers import last_user_message_id, narration_with, rollback_last_turn

BACKEND = Path(__file__).resolve().parents[1]
MIRA = payloads.NEW_CHARACTER_NAME
ARC = "La mère malade"
OBJECT = "Valise cabine"
BEFORE_JOURNAL = (
    "Impossible de revenir sur un tour joué avant la mise en place du journal "
    "des tours."
)


async def _world(harness, game_id) -> dict:
    """What the B-08 turn changes, plus the message and turn counts."""
    async with harness.pool.acquire() as conn:
        game = await conn.fetchrow(
            """SELECT current_cycle, "current_time", current_location_id, detail_requests,
                      last_director_time FROM games WHERE id = $1""",
            game_id,
        )
        return {
            **dict(game),
            "characters": sorted(
                r["name"]
                for r in await conn.fetch(
                    "SELECT name FROM characters WHERE game_id = $1", game_id
                )
            ),
            "registry": sorted(
                r["name"]
                for r in await conn.fetch(
                    "SELECT name FROM entity_registry WHERE game_id = $1", game_id
                )
            ),
            "credits": await conn.fetchval(
                "SELECT credits FROM protagonists WHERE game_id = $1", game_id
            ),
            "quantity": await conn.fetchval(
                """SELECT i.quantity FROM inventory i JOIN objects o ON o.id = i.object_id
                   WHERE i.game_id = $1 AND o.name = $2""",
                game_id,
                OBJECT,
            ),
            "arc_resolved": await conn.fetchval(
                "SELECT resolved FROM narrative_arcs WHERE game_id = $1 AND title = $2",
                game_id,
                ARC,
            ),
            "plans": await conn.fetchval(
                "SELECT count(*) FROM director_plans WHERE game_id = $1", game_id
            ),
            "messages": await conn.fetchval(
                "SELECT count(*) FROM messages WHERE game_id = $1", game_id
            ),
            "turns": await conn.fetchval(
                "SELECT count(*) FROM turns WHERE game_id = $1", game_id
            ),
        }


async def _turn(harness, game_id, narration: str, message: str) -> None:
    harness.llm._responses["narration"] = narration
    await harness.chat(game_id, message)
    await harness.drain()


async def _first_turn_creates_mira(harness, game_id) -> None:
    harness.llm._responses["resolver"] = payloads.RESOLVER_NEW_CHARACTER
    harness.llm._responses["extract:extract_characters"] = (
        payloads.EXTRACT_CHARACTERS_NEW
    )
    await _turn(
        harness, game_id, narration_with(info_requests=[OBJECT]), "Je regarde la foule."
    )
    harness.llm._responses["resolver"] = payloads.RESOLVER_EMPTY


async def _b08_turn(harness, game_id) -> None:
    """Rename, debit, info requests, inventory +2 and a Director resolving a world arc."""
    harness.llm._responses["extract:extract_inventory"] = {
        "inventory_changes": [
            {"action": "acquire", "object_ref": OBJECT, "quantity_delta": 2}
        ]
    }
    harness.llm._responses["director"] = json.dumps(
        {
            **json.loads(payloads.DIRECTOR),
            "arc_updates": [
                {"action": "resolve", "title": ARC, "resolution": "Elle guérit."}
            ],
        }
    )
    # 18h00: the medium Director interval (6 in-game hours) after the 11h42 init plan.
    await _turn(
        harness,
        game_id,
        narration_with(
            time={"new_time": "18h00", "ellipse": False, "ellipse_summary": None},
            entity_reveals=[
                {
                    "entity_type": "character",
                    "current_name": MIRA,
                    "real_name": "Mira Vance",
                }
            ],
            credit_delta={"amount": -30, "description": "Pot-de-vin"},
            info_requests=["Mira Vance"],
            extraction_triggers=["inventory"],
        ),
        "Je soudoie Mira.",
    )


async def test_regenerate_restores_inserts_and_updates(harness, world_game):
    await _first_turn_creates_mira(harness, world_game)
    before = await _world(harness, world_game)
    assert MIRA in before["characters"] and before["detail_requests"] == [OBJECT]

    await _b08_turn(harness, world_game)
    during = await _world(harness, world_game)
    assert "Mira Vance" in during["characters"] and MIRA not in during["characters"]
    assert during["credits"] == before["credits"] - 30
    assert during["detail_requests"] == ["Mira Vance"]
    assert during["quantity"] == before["quantity"] + 2
    assert during["arc_resolved"] is True and before["arc_resolved"] is False
    assert during["last_director_time"] == "18h00" != before["last_director_time"]

    user_msg = await last_user_message_id(harness, world_game)
    r = await harness.client.post(
        f"/api/games/{world_game}/rollback",
        json={"messageId": str(user_msg)},
        headers=harness.headers,
    )
    assert r.status_code == 200, r.text
    result = r.json()["rollback_result"]
    assert set(result) == {"undone_changes", "deleted_turns"}
    assert result["undone_changes"] > 0 and result["deleted_turns"] == 1
    assert await _world(harness, world_game) == before


async def test_rollback_refuses_a_message_without_turn(harness, world_game):
    await _first_turn_creates_mira(harness, world_game)
    async with harness.pool.acquire() as conn:
        await conn.execute(
            """UPDATE messages SET turn_id = NULL WHERE turn_id = (
                   SELECT turn_id FROM messages WHERE game_id = $1
                   ORDER BY sequence DESC LIMIT 1)""",
            world_game,
        )
    before = await _world(harness, world_game)
    user_msg = await last_user_message_id(harness, world_game)
    r = await harness.client.post(
        f"/api/games/{world_game}/rollback",
        json={"messageId": str(user_msg)},
        headers=harness.headers,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == BEFORE_JOURNAL
    assert await _world(harness, world_game) == before


async def test_rollback_is_atomic(harness, world_game, monkeypatch):
    await _first_turn_creates_mira(harness, world_game)
    await _b08_turn(harness, world_game)
    before = await _world(harness, world_game)

    async def boom(conn, turn_ids):
        raise RuntimeError("undo failed")

    monkeypatch.setattr(rollback, "_undo_changes", boom)
    user_msg = await last_user_message_id(harness, world_game)
    try:
        r = await harness.client.post(
            f"/api/games/{world_game}/rollback",
            json={"messageId": str(user_msg)},
            headers=harness.headers,
        )
        status = r.status_code
    except RuntimeError:  # the ASGI test client may re-raise the server error
        status = 500
    assert status == 500
    assert await _world(harness, world_game) == before


async def test_cycle_engine_keeps_the_old_behaviour(harness, world_game, monkeypatch):
    monkeypatch.setattr(get_settings(), "rollback_engine", "cycle")
    await _first_turn_creates_mira(harness, world_game)
    async with harness.pool.acquire() as conn:
        turns_before = await conn.fetchval(
            "SELECT count(*) FROM turns WHERE game_id = $1", world_game
        )
    harness.llm._responses["resolver"] = payloads.RESOLVER_EMPTY
    await _turn(harness, world_game, payloads.NARRATION, "Deuxième tour.")

    user_msg = await last_user_message_id(harness, world_game)
    r = await harness.client.post(
        f"/api/games/{world_game}/rollback",
        json={"messageId": str(user_msg)},
        headers=harness.headers,
    )
    assert r.status_code == 200, r.text
    assert {
        "deleted_facts",
        "deleted_events",
        "deleted_arcs",
        "reverted_relations",
    } <= set(r.json()["rollback_result"])
    async with harness.pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM turns WHERE game_id = $1", world_game
            )
            == turns_before
        )


async def _roll_state(harness, game_id, roll_id) -> dict:
    """The pending roll's row (None once removed), the fate points, the game's turns."""
    async with harness.pool.acquire() as conn:
        roll = await conn.fetchrow(
            "SELECT status, turn_id, message_id FROM mechanic_rolls WHERE id = $1::uuid",
            roll_id,
        )
        return {
            "roll": dict(roll) if roll else None,
            "fate_points": await conn.fetchval(
                "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id
            ),
            "turns": {
                r["id"]
                for r in await conn.fetch(
                    "SELECT id FROM turns WHERE game_id = $1", game_id
                )
            },
        }


async def _resume(harness, game_id, event) -> None:
    await harness.chat(
        game_id,
        "Je tente un saut impossible.",
        roll_id=event["roll_id"],
        invoked_aspects=["Pilote déchu en quête de rédemption"],
    )
    await harness.drain()


async def _play_on(harness, game_id) -> None:
    harness.llm._responses["mechanical"] = payloads.mechanical(requires_test=False)
    await _turn(harness, game_id, payloads.NARRATION, "Je reprends mon souffle.")


def _without_adoption(monkeypatch):
    """Resumes committed as before the adoption (P5a games): returns the restore callable."""
    original = turns.adopt_halted_turn

    async def no_adoption(*args, **kwargs):
        return False

    monkeypatch.setattr(turns, "adopt_halted_turn", no_adoption)
    return lambda: monkeypatch.setattr(turns, "adopt_halted_turn", original)


async def test_resume_adopts_the_halted_turn(harness, pending):
    game_id, event = pending
    before = await _roll_state(harness, game_id, event["roll_id"])
    halted = before["roll"]["turn_id"]
    await _resume(harness, game_id, event)
    during = await _roll_state(harness, game_id, event["roll_id"])
    resuming = during["roll"]["turn_id"]
    assert halted not in during["turns"] and resuming in during["turns"]
    async with harness.pool.acquire() as conn:
        insert_turn = await conn.fetchval(
            """SELECT turn_id FROM world_changes
               WHERE row_id = $1::uuid AND table_name = 'mechanic_rolls' AND op = 'I'""",
            event["roll_id"],
        )
    assert insert_turn == resuming


async def test_resumed_roll_rolls_back_with_its_halted_turn(harness, pending):
    """W3: the resuming turn moved the roll to itself and pointed it at its message. Its
    undo removes the roll whole (the halted turn's insert is part of it): nothing
    dangles, the fate point comes back, both turns are gone."""
    game_id, event = pending
    before = await _roll_state(harness, game_id, event["roll_id"])
    await _resume(harness, game_id, event)
    assert (await _roll_state(harness, game_id, event["roll_id"]))["roll"]["message_id"]

    await rollback_last_turn(harness, game_id)
    after = await _roll_state(harness, game_id, event["roll_id"])
    assert after["roll"] is None
    assert after["fate_points"] == before["fate_points"]
    assert after["turns"] == before["turns"] - {before["roll"]["turn_id"]}


async def test_rollback_after_a_resumed_roll_keeps_the_roll(harness, pending):
    """The roll resolved by a kept turn stays resolved on that turn and its message."""
    game_id, event = pending
    await _resume(harness, game_id, event)
    resolved = await _roll_state(harness, game_id, event["roll_id"])
    await _play_on(harness, game_id)

    await rollback_last_turn(harness, game_id)
    assert await _roll_state(harness, game_id, event["roll_id"]) == resolved


async def test_resume_can_be_rolled_back_after_a_later_rollback(harness, pending):
    """C1: rolling back the turn after a resume used to purge the halted turn (open), and
    the resume's own rollback then restored a dangling turn_id (500)."""
    game_id, event = pending
    before = await _roll_state(harness, game_id, event["roll_id"])
    await _resume(harness, game_id, event)
    await _play_on(harness, game_id)

    await rollback_last_turn(harness, game_id)
    await rollback_last_turn(harness, game_id)
    after = await _roll_state(harness, game_id, event["roll_id"])
    assert after["roll"] is None
    assert after["fate_points"] == before["fate_points"]
    assert after["turns"] == before["turns"] - {before["roll"]["turn_id"]}


async def test_legacy_resume_with_its_halted_turn_still_open(
    harness, pending, monkeypatch
):
    """A P5a resume whose halted turn is still open: the rollback adopts it first."""
    game_id, event = pending
    before = await _roll_state(harness, game_id, event["roll_id"])
    restore = _without_adoption(monkeypatch)
    await _resume(harness, game_id, event)
    restore()
    assert (
        before["roll"]["turn_id"]
        in (await _roll_state(harness, game_id, event["roll_id"]))["turns"]
    )

    await rollback_last_turn(harness, game_id)
    after = await _roll_state(harness, game_id, event["roll_id"])
    assert after["roll"] is None
    assert after["fate_points"] == before["fate_points"]
    assert after["turns"] == before["turns"] - {before["roll"]["turn_id"]}


async def test_legacy_resume_after_its_halted_turn_was_purged(
    harness, pending, monkeypatch
):
    """A P5a resume whose halted turn an earlier rollback purged, with the roll's insert:
    the dangling old turn_id is cleared and the roll removed after the undo."""
    game_id, event = pending
    before = await _roll_state(harness, game_id, event["roll_id"])
    restore = _without_adoption(monkeypatch)
    await _resume(harness, game_id, event)
    await _play_on(harness, game_id)
    restore()
    await rollback_last_turn(
        harness, game_id
    )  # purges the open halted turn (P5a state)
    assert (
        before["roll"]["turn_id"]
        not in (await _roll_state(harness, game_id, event["roll_id"]))["turns"]
    )

    await rollback_last_turn(harness, game_id)
    after = await _roll_state(harness, game_id, event["roll_id"])
    assert after["roll"] is None
    assert after["fate_points"] == before["fate_points"]
    assert after["turns"] == before["turns"] - {before["roll"]["turn_id"]}


async def test_rollback_of_a_resume_while_a_new_roll_is_pending(
    harness, pending, monkeypatch
):
    """I1: the undo puts the resumed roll back to pending while the next action's roll is
    pending (one pending roll per game, not deferrable): the latter is expired first."""
    game_id, event = pending
    before = await _roll_state(harness, game_id, event["roll_id"])
    await _resume(harness, game_id, event)
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4
    )
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    events = await harness.chat(game_id, "Je saute encore.")
    second = next(e for e in events if e["type"] == "roll_pending")

    await rollback_last_turn(harness, game_id)
    async with harness.pool.acquire() as conn:
        rolls = {
            str(r["id"]): r["status"]
            for r in await conn.fetch(
                "SELECT id, status FROM mechanic_rolls WHERE game_id = $1", game_id
            )
        }
    assert rolls == {second["roll_id"]: "expired"}  # the resumed roll is gone
    after = await _roll_state(harness, game_id, event["roll_id"])
    assert after["fate_points"] == before["fate_points"]
    assert after["turns"] == before["turns"] - {before["roll"]["turn_id"]}


def test_rollback_to_message_is_thin():
    source = inspect.getsource(GameService.rollback_to_message)
    node = ast.parse(textwrap.dedent(source)).body[0]
    assert node.end_lineno - node.lineno + 1 < 40
    service = (BACKEND / "services" / "game_service.py").read_text(encoding="utf-8")
    for legacy in ("rollback_to_cycle", "restore_turn_state", "credit_reversal"):
        assert legacy not in service
