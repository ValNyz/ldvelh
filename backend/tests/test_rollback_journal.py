"""The rollback replays the turn journal (#22); ROLLBACK_ENGINE=cycle keeps the old path."""

import ast
import inspect
import json
import textwrap
from pathlib import Path

from config import get_settings
from services import rollback
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


async def test_resumed_roll_rolls_back_with_its_halted_turn(harness, pending):
    """W3: the resuming turn moved the roll to itself and pointed it at its message. The
    undo puts it back on the halted turn while that turn still exists, then undoes the
    halted turn too: the roll is gone, nothing dangles, both turns are deleted."""
    game_id, event = pending
    async with harness.pool.acquire() as conn:
        halted = await conn.fetchval(
            "SELECT turn_id FROM mechanic_rolls WHERE id = $1::uuid", event["roll_id"]
        )
        fate_points = await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id
        )
    await harness.chat(
        game_id,
        "Je tente un saut impossible.",
        roll_id=event["roll_id"],
        invoked_aspects=["Pilote déchu en quête de rédemption"],
    )
    await harness.drain()
    async with harness.pool.acquire() as conn:
        claimed = await conn.fetchrow(
            "SELECT turn_id, message_id FROM mechanic_rolls WHERE id = $1::uuid",
            event["roll_id"],
        )
    assert claimed["turn_id"] != halted and claimed["message_id"] is not None

    await rollback_last_turn(harness, game_id)
    async with harness.pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM mechanic_rolls WHERE id = $1::uuid",
                event["roll_id"],
            )
            == 0
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM turns WHERE id = ANY($1::uuid[])",
                [halted, claimed["turn_id"]],
            )
            == 0
        )
        assert (
            await conn.fetchval(
                "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id
            )
            == fate_points
        )


async def test_rollback_after_a_resumed_roll_keeps_the_roll(harness, pending):
    """The roll resolved by a kept turn stays resolved on that turn and its message."""
    game_id, event = pending
    await harness.chat(
        game_id,
        "Je tente un saut impossible.",
        roll_id=event["roll_id"],
        invoked_aspects=["Pilote déchu en quête de rédemption"],
    )
    await harness.drain()
    async with harness.pool.acquire() as conn:
        resolved = dict(
            await conn.fetchrow(
                "SELECT status, turn_id, message_id FROM mechanic_rolls WHERE id = $1::uuid",
                event["roll_id"],
            )
        )
    harness.llm._responses["mechanical"] = payloads.mechanical(requires_test=False)
    await _turn(harness, game_id, payloads.NARRATION, "Je reprends mon souffle.")

    await rollback_last_turn(harness, game_id)
    async with harness.pool.acquire() as conn:
        after = await conn.fetchrow(
            "SELECT status, turn_id, message_id FROM mechanic_rolls WHERE id = $1::uuid",
            event["roll_id"],
        )
    assert dict(after) == resolved


def test_rollback_to_message_is_thin():
    source = inspect.getsource(GameService.rollback_to_message)
    node = ast.parse(textwrap.dedent(source)).body[0]
    assert node.end_lineno - node.lineno + 1 < 40
    service = (BACKEND / "services" / "game_service.py").read_text(encoding="utf-8")
    for legacy in ("rollback_to_cycle", "restore_turn_state", "credit_reversal"):
        assert legacy not in service
