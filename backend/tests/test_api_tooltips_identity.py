"""Tooltips and world panel on the identity model (#152): references resolve through the
typed find_entity, and what the player reads is display_for_player, never the true name of
an NPC the PC has not identified."""

import json
from uuid import UUID

import pytest
from helpers import auth_headers

from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

pytestmark = pytest.mark.integration

SECRET_NAME = "Zyrla Quenn"  # appears in no story text of the example world
DESCRIPTOR = "La femme aux cernes"


async def _world(client, test_user, test_pool) -> UUID:
    from schema import WorldGeneration
    from services.game_service import GameService

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])
    world_gen = WorldGeneration.model_validate(json.loads(WORLD_GENERATION_EXAMPLE))
    await GameService(test_pool).process_init(game_id, world_gen)
    return game_id


async def _hide_under_a_descriptor(test_pool, game_id: UUID) -> None:
    """Justine becomes an unidentified NPC whose true name is SECRET_NAME."""
    async with test_pool.acquire() as conn:
        await conn.execute(
            "UPDATE characters SET true_name = $2, descriptor = $3,"
            " known_by_protagonist = false"
            " WHERE game_id = $1 AND true_name = 'Justine Lépicier'",
            game_id,
            SECRET_NAME,
            DESCRIPTOR,
        )


async def _tooltip(client, test_user, game_id: UUID, name: str) -> dict:
    resp = await client.get(
        "/api/tooltips/entity",
        params={"gameId": str(game_id), "name": name, "entityType": "character"},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    return resp.json()


async def test_entity_tooltip_resolves_a_descriptor_with_article(
    client, test_user, test_pool
):
    game_id = await _world(client, test_user, test_pool)
    await _hide_under_a_descriptor(test_pool, game_id)

    without_article = await _tooltip(client, test_user, game_id, "femme aux cernes")
    other_case = await _tooltip(client, test_user, game_id, "la FEMME aux cernes")

    for payload in (without_article, other_case):
        assert payload["found"] is True
        assert payload["tooltip"]["name"] == DESCRIPTOR
        assert payload["tooltip"]["type"] == "character"


async def test_unknown_npc_tooltip_and_world_panel_never_carry_the_true_name(
    client, test_user, test_pool
):
    game_id = await _world(client, test_user, test_pool)
    await _hide_under_a_descriptor(test_pool, game_id)
    async with test_pool.acquire() as conn:
        conversation = await conn.fetchval(
            "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, 1) RETURNING id",
            game_id,
        )
        # A resolver annotation written with the internal label (the true name).
        await conn.execute(
            """INSERT INTO messages (game_id, conversation_id, role, content, sequence,
                                     narrator_context)
               VALUES ($1, $2, 'assistant', 'Elle lève les yeux.', 1, $3::jsonb)""",
            game_id,
            conversation,
            [[0, 4, SECRET_NAME, "character"]],
        )
    headers = auth_headers(test_user["token"])

    by_true_name = await _tooltip(client, test_user, game_id, SECRET_NAME)
    annotations = (
        await client.get(
            "/api/tooltips/annotations",
            params={"gameId": str(game_id)},
            headers=headers,
        )
    ).json()
    world = (await client.get(f"/api/games/{game_id}/world", headers=headers)).json()

    assert by_true_name["found"] is True
    assert annotations["messages"][0]["annotations"][0]["name"] == DESCRIPTOR
    leaks = [
        label
        for label, payload in (
            ("tooltip", by_true_name),
            ("annotations", annotations),
            ("world", world),
        )
        if SECRET_NAME.casefold() in json.dumps(payload, ensure_ascii=False).casefold()
    ]
    assert leaks == []
