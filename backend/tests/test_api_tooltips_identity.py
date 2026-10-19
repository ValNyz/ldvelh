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
    assert annotations["messages"][0]["annotations"][0]["label"] == DESCRIPTOR
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


async def _store_spans(test_pool, game_id: UUID, spans: list) -> None:
    async with test_pool.acquire() as conn:
        conversation = await conn.fetchval(
            "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, 1) RETURNING id",
            game_id,
        )
        await conn.execute(
            """INSERT INTO messages (game_id, conversation_id, role, content, sequence,
                                     narrator_context)
               VALUES ($1, $2, 'assistant', 'Elle lève les yeux vers Ossek.', 1, $3::jsonb)""",
            game_id,
            conversation,
            spans,
        )


async def test_an_unresolved_character_span_never_carries_its_stored_label(
    client, test_user, test_pool
):
    """Two homonyms share the true name the resolver stored: the span no longer resolves
    (ambiguous), and the stored label, a hidden true name, must not reach the player."""
    from packs.loader import load_lang

    game_id = await _world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        for suffix in ("Quai 9", "Bar"):
            await conn.execute(
                "INSERT INTO characters (game_id, true_name, label_suffix) VALUES ($1, $2, $3)",
                game_id,
                SECRET_NAME,
                suffix,
            )
    await _store_spans(test_pool, game_id, [[0, 4, SECRET_NAME, "character"]])

    annotations = (
        await client.get(
            "/api/tooltips/annotations",
            params={"gameId": str(game_id)},
            headers=auth_headers(test_user["token"]),
        )
    ).json()

    [span] = annotations["messages"][0]["annotations"]
    assert span["label"] == load_lang("fr").unknown_character_label
    assert span["entity_id"] is None
    assert span["surface"] == "Elle"
    assert (
        SECRET_NAME.casefold()
        not in json.dumps(annotations, ensure_ascii=False).casefold()
    )


async def test_a_known_npc_still_shows_its_true_name(client, test_user, test_pool):
    game_id = await _world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        ossek = await conn.fetchval(
            "UPDATE characters SET known_by_protagonist = true"
            " WHERE game_id = $1 AND true_name = 'Ossek' RETURNING id",
            game_id,
        )
        handle = await conn.fetchval(
            "SELECT handle FROM entity_registry WHERE id = $1", ossek
        )
    await _store_spans(test_pool, game_id, [[24, 29, "Ossek", "character"]])

    annotations = (
        await client.get(
            "/api/tooltips/annotations",
            params={"gameId": str(game_id)},
            headers=auth_headers(test_user["token"]),
        )
    ).json()
    by_id = await _tooltip(client, test_user, game_id, str(ossek))

    [span] = annotations["messages"][0]["annotations"]
    assert (span["label"], span["entity_id"], span["handle"], span["surface"]) == (
        "Ossek",
        str(ossek),
        handle,
        "Ossek",
    )
    assert by_id["found"] is True and by_id["tooltip"]["name"] == "Ossek"
    assert any(info.startswith("Métier") for info in by_id["tooltip"]["infos"])


async def test_unknown_npc_tooltip_drops_free_text_that_may_name_it(
    client, test_user, test_pool
):
    """Occupation and ambient are free text (extraction, Director): for an NPC the PC has
    not identified they may hold its true name, so the tooltip leaves them out."""
    game_id = await _world(client, test_user, test_pool)
    await _hide_under_a_descriptor(test_pool, game_id)
    async with test_pool.acquire() as conn:
        await conn.execute(
            "UPDATE characters SET ambient = $2, occupation = $3"
            " WHERE game_id = $1 AND true_name = $4",
            game_id,
            f"{SECRET_NAME} fixe la porte",
            f"assistante de {SECRET_NAME}",
            SECRET_NAME,
        )

    payload = await _tooltip(client, test_user, game_id, DESCRIPTOR)

    assert payload["found"] is True
    assert (
        SECRET_NAME.casefold() not in json.dumps(payload, ensure_ascii=False).casefold()
    )
    assert all(not info.startswith("Métier") for info in payload["tooltip"]["infos"])


def test_an_unresolved_character_span_falls_back_to_the_unknown_label():
    """Even when SQL gives no label, the stored label of a character is not sent."""
    from api.tooltips import _annotation

    content = "Elle lève les yeux."
    span = _annotation(content, [0, 4, SECRET_NAME, "character"], {}, "?")
    place = _annotation(content, [5, 9, "Quai 9", "location"], {}, "?")
    assert (span.label, span.surface) == ("?", "Elle")
    assert place.label == "Quai 9"
