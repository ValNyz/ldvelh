"""Tooltips and world panel on the identity model (#152, #155, spec §4.9): annotations are
the stored mentions, served by entity id with what the player may read
(display_for_player, never a secret name); a tooltip is read by id, and an NPC the PC has
not identified shows only what anyone can observe."""

import json
from uuid import UUID

import pytest
from helpers import auth_headers, last_user_message_id, narration_with

from domain.identity import MentionRow
from tests.characterization import payloads
from tests.prompt_examples import WORLD_GENERATION_EXAMPLE

pytestmark = pytest.mark.integration

SECRET_NAME = "Zyrla Quenn"  # appears in no story text of the example world
DESCRIPTOR = "La femme aux cernes"
SECRET_PLACE = "Crypte Vauquelin"


async def _world(client, test_user, test_pool) -> UUID:
    from schema import WorldGeneration
    from services.game_service import GameService

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    game_id = UUID(resp.json()["gameId"])
    world_gen = WorldGeneration.model_validate(json.loads(WORLD_GENERATION_EXAMPLE))
    await GameService(test_pool).process_init(game_id, world_gen)
    return game_id


async def _hide_under_a_descriptor(test_pool, game_id: UUID) -> UUID:
    """Justine becomes an unidentified NPC whose true name is SECRET_NAME."""
    async with test_pool.acquire() as conn:
        return await conn.fetchval(
            "UPDATE characters SET true_name = $2, descriptor = $3,"
            " known_by_protagonist = false"
            " WHERE game_id = $1 AND true_name = 'Justine Lépicier' RETURNING id",
            game_id,
            SECRET_NAME,
            DESCRIPTOR,
        )


async def _id(test_pool, game_id: UUID, where: str, *args) -> UUID:
    async with test_pool.acquire() as conn:
        return await conn.fetchval(
            f"SELECT id FROM entity_registry WHERE game_id = $1 AND {where}",
            game_id,
            *args,
        )


async def _mentions(test_pool, game_id: UUID, content: str, spans: list) -> UUID:
    """A narrator message holding `content`, with a stored mention per (start, end,
    entity id) of `spans`."""
    from repos import entities

    async with test_pool.acquire() as conn:
        conversation = await conn.fetchval(
            "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, 1) RETURNING id",
            game_id,
        )
        message = await conn.fetchval(
            """INSERT INTO messages (game_id, conversation_id, role, content, sequence)
               VALUES ($1, $2, 'assistant', $3, 1) RETURNING id""",
            game_id,
            conversation,
            content,
        )
        rows = [MentionRow(s, e, content[s:e], i, "match") for s, e, i in spans]
        await entities.insert_mentions(conn, game_id, message, None, rows)
    return message


async def _annotations(client, test_user, game_id: UUID) -> dict:
    resp = await client.get(
        "/api/tooltips/annotations",
        params={"gameId": str(game_id)},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    return resp.json()


async def _tooltip(client, test_user, game_id: UUID, entity_id) -> dict:
    resp = await client.get(
        "/api/tooltips/entity",
        params={"gameId": str(game_id), "id": str(entity_id)},
        headers=auth_headers(test_user["token"]),
    )
    assert resp.status_code == 200
    return resp.json()


def _holds(payload, text: str) -> bool:
    return text.casefold() in json.dumps(payload, ensure_ascii=False).casefold()


async def test_annotations_come_from_entity_mentions_with_ids_and_display_labels(
    client, test_user, test_pool
):
    game_id = await _world(client, test_user, test_pool)
    justine = await _hide_under_a_descriptor(test_pool, game_id)
    companion = await _id(test_pool, game_id, "entity_type = 'companion'")
    content = "Elle lève les yeux vers Célimène."
    message = await _mentions(
        test_pool, game_id, content, [(0, 4, justine), (24, 32, companion)]
    )

    annotations = await _annotations(client, test_user, game_id)

    assert annotations == {
        "messages": [
            {
                "message_id": str(message),
                "sequence": 1,
                "annotations": [
                    {"start": 0, "end": 4, "entity_id": str(justine),
                     "entity_type": "character", "label": DESCRIPTOR},
                    {"start": 24, "end": 32, "entity_id": str(companion),
                     "entity_type": "companion", "label": "Célimène"},
                ],
            }
        ]
    }  # fmt: skip
    assert not _holds(annotations, SECRET_NAME)


async def test_entity_tooltip_by_id_for_an_unknown_npc_hides_occupation_description_and_relation(
    client, test_user, test_pool
):
    game_id = await _world(client, test_user, test_pool)
    justine = await _hide_under_a_descriptor(test_pool, game_id)
    async with test_pool.acquire() as conn:
        await conn.execute(
            "UPDATE characters SET occupation = 'technicienne', mood = 'lasse',"
            " ambient = 'fixe la porte', description = 'Une ancienne pilote.'"
            " WHERE id = $1",
            justine,
        )
        target = await conn.fetchval(
            "SELECT id FROM characters WHERE game_id = $1 AND id <> $2 LIMIT 1",
            game_id,
            justine,
        )
        await conn.execute(
            """INSERT INTO relations (game_id, type, source_id, target_id, start_cycle)
               VALUES ($1, 'knows', $2, $3, 1)""",
            game_id,
            justine,
            target,
        )

    payload = await _tooltip(client, test_user, game_id, justine)

    assert payload["found"] is True
    tooltip = payload["tooltip"]
    assert (tooltip["name"], tooltip["type"], tooltip["relation"]) == (
        DESCRIPTOR,
        "character",
        None,
    )
    assert "Humeur: lasse" in tooltip["infos"] and "fixe la porte" in tooltip["infos"]
    assert not any(
        "technicienne" in info or "pilote" in info for info in tooltip["infos"]
    )


async def test_unknown_npc_tooltip_drops_an_ambient_that_names_it(
    client, test_user, test_pool
):
    """The ambient is free text (extraction, Director): when it holds the NPC's true
    name, the tooltip of an unidentified NPC leaves it out."""
    game_id = await _world(client, test_user, test_pool)
    justine = await _hide_under_a_descriptor(test_pool, game_id)
    async with test_pool.acquire() as conn:
        await conn.execute(
            "UPDATE characters SET ambient = $2, mood = 'lasse' WHERE id = $1",
            justine,
            f"{SECRET_NAME} fixe la porte",
        )

    payload = await _tooltip(client, test_user, game_id, justine)

    assert payload["found"] is True and payload["tooltip"]["infos"] == ["Humeur: lasse"]


async def test_a_known_npc_still_shows_its_true_name_occupation_and_relation(
    client, test_user, test_pool
):
    game_id = await _world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        ossek = await conn.fetchval(
            "UPDATE characters SET known_by_protagonist = true"
            " WHERE game_id = $1 AND true_name = 'Ossek' RETURNING id",
            game_id,
        )
        relation = await conn.fetchval(
            """SELECT type::text FROM relations
                WHERE game_id = $1 AND source_id = $2 AND end_cycle IS NULL LIMIT 1""",
            game_id,
            ossek,
        )

    payload = await _tooltip(client, test_user, game_id, ossek)

    assert payload["found"] is True and payload["tooltip"]["name"] == "Ossek"
    assert any(info.startswith("Métier") for info in payload["tooltip"]["infos"])
    assert payload["tooltip"]["relation"] == relation


async def test_entity_tooltip_by_id_follows_a_merge(client, test_user, test_pool):
    from repos import entities

    game_id = await _world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        keep = await conn.fetchval(
            "INSERT INTO characters (game_id, true_name, known_by_protagonist)"
            " VALUES ($1, 'Tesk Vahrun', true) RETURNING id",
            game_id,
        )
        drop = await conn.fetchval(
            "INSERT INTO characters (game_id, descriptor) VALUES ($1, $2) RETURNING id",
            game_id,
            "Le Kethari au tablier",
        )
        await entities.merge_entities(conn, keep, drop, "test", None)
    await _mentions(test_pool, game_id, "Le Kethari attend.", [(3, 10, drop)])

    payload = await _tooltip(client, test_user, game_id, drop)
    annotations = await _annotations(client, test_user, game_id)

    assert payload["found"] is True and payload["tooltip"]["name"] == "Tesk Vahrun"
    [span] = annotations["messages"][0]["annotations"]
    assert (span["entity_id"], span["label"]) == (str(keep), "Tesk Vahrun")


async def test_entity_tooltip_for_a_valid_id_is_never_found_false(
    client, test_user, test_pool
):
    """Every id a mention of the game holds (every type, the protagonist and the
    companion, a merge tombstone, an entity removed from the world) has a tooltip; only
    an id that is no entity of the game is not found."""
    from repos import entities

    game_id = await _world(client, test_user, test_pool)
    other_game = await _world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        keep = await conn.fetchval(
            "INSERT INTO characters (game_id, true_name) VALUES ($1, 'Tesk Vahrun')"
            " RETURNING id",
            game_id,
        )
        drop = await conn.fetchval(
            "INSERT INTO characters (game_id, true_name) VALUES ($1, 'Tesk Vahr')"
            " RETURNING id",
            game_id,
        )
        await entities.merge_entities(conn, keep, drop, "test", None)
        await conn.execute(
            "UPDATE characters SET removed_cycle = 1"
            " WHERE game_id = $1 AND true_name = 'Ossek'",
            game_id,
        )
        ids = [
            r["id"]
            for r in await conn.fetch(
                "SELECT id FROM entity_registry WHERE game_id = $1 ORDER BY handle",
                game_id,
            )
        ]
        foreign = await conn.fetchval(
            "SELECT id FROM entity_registry WHERE game_id = $1 LIMIT 1", other_game
        )
    await _mentions(
        test_pool, game_id, "x" * len(ids), [(n, n + 1, i) for n, i in enumerate(ids)]
    )
    async with test_pool.acquire() as conn:
        mentioned = {
            r["entity_id"]
            for r in await conn.fetch(
                "SELECT entity_id FROM entity_mentions WHERE game_id = $1", game_id
            )
        }

    not_found = [
        i
        for i in mentioned
        if not (await _tooltip(client, test_user, game_id, i))["found"]
    ]
    types = {
        (await _tooltip(client, test_user, game_id, i))["tooltip"]["type"]
        for i in mentioned
    }

    assert drop in mentioned and not_found == []
    assert {
        "character",
        "location",
        "organization",
        "protagonist",
        "companion",
    } <= types
    for missing in (UUID(int=0), foreign):
        assert await _tooltip(client, test_user, game_id, missing) == {"found": False}


async def test_arc_tooltip_is_served(client, test_user, test_pool):
    game_id = await _world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        arc = await conn.fetchrow(
            "SELECT id, title, domain FROM narrative_arcs WHERE game_id = $1 LIMIT 1",
            game_id,
        )

    payload = await _tooltip(client, test_user, game_id, arc["id"])

    assert payload == {
        "found": True,
        "tooltip": {
            "icon": "📖",
            "name": arc["title"],
            "type": "arc",
            "infos": [f"Domaine: {arc['domain']}"] if arc["domain"] else [],
            "relation": None,
        },
    }


async def test_tooltip_payloads_never_contain_a_hidden_true_name(
    client, test_user, test_pool
):
    """L = 0 on the whole JSON of the annotations and the tooltips: the unidentified
    NPC's true name, held by its occupation, ambient and description, and the name of a
    whole-secret place. The world panel never shows the NPC's true name (its secret
    places belong to the panel's own filter, task 21)."""
    game_id = await _world(client, test_user, test_pool)
    justine = await _hide_under_a_descriptor(test_pool, game_id)
    async with test_pool.acquire() as conn:
        await conn.execute(
            "UPDATE characters SET occupation = $2, ambient = $3, description = $4"
            " WHERE id = $1",
            justine,
            f"assistante de {SECRET_NAME}",
            f"{SECRET_NAME} fixe la porte",
            f"{SECRET_NAME}, ancienne pilote.",
        )
        place = await conn.fetchval(
            "INSERT INTO locations (game_id, name) VALUES ($1, $2) RETURNING id",
            game_id,
            SECRET_PLACE,
        )
        await conn.execute(
            "UPDATE entity_aliases SET secret = true WHERE entity_id = $1", place
        )
    await _mentions(
        test_pool,
        game_id,
        "Elle entre dans la crypte.",
        [(0, 4, justine), (19, 25, place)],
    )

    annotations = await _annotations(client, test_user, game_id)
    payloads_ = {
        "annotations": annotations,
        "npc": await _tooltip(client, test_user, game_id, justine),
        "place": await _tooltip(client, test_user, game_id, place),
    }
    world = await client.get(
        f"/api/games/{game_id}/world", headers=auth_headers(test_user["token"])
    )

    leaks = [
        label
        for label, payload in payloads_.items()
        for secret in (SECRET_NAME, SECRET_PLACE)
        if _holds(payload, secret)
    ]
    assert leaks == []
    assert not _holds(world.json(), SECRET_NAME)
    # Nothing readable of the place: no annotation, a tooltip without name nor detail.
    [message] = annotations["messages"]
    assert [a["entity_id"] for a in message["annotations"]] == [str(justine)]
    assert payloads_["place"]["found"] is True
    assert payloads_["place"]["tooltip"]["infos"] == []


async def test_regenerate_after_a_reveal_restores_the_panel_and_tooltips(
    harness, world_game
):
    """Review Focus 2: turn 2 reveals an unidentified NPC's name, which is another
    character's, so the two are merged; regenerating turn 2 undoes both, and the
    remaining messages' annotations resolve again under the descriptors, with a tooltip
    for each, and the panel no longer shows the revealed name."""
    revealed = "Dr. Yuki Tanaka"
    other = "La directrice en blouse"
    async with harness.pool.acquire() as conn:
        await conn.execute(
            "UPDATE characters SET true_name = $2, descriptor = $3,"
            " known_by_protagonist = false"
            " WHERE game_id = $1 AND true_name = 'Justine Lépicier'",
            world_game,
            SECRET_NAME,
            DESCRIPTOR,
        )
        await conn.execute(
            "UPDATE characters SET descriptor = $2 WHERE game_id = $1 AND true_name = $3",
            world_game,
            other,
            revealed,
        )
    text = json.loads(payloads.NARRATION)["narrative_text"]
    harness.llm._responses["narration"] = narration_with(
        narrative_text=f"{text}\n\n{DESCRIPTOR} croise {other.lower()}."
    )
    await harness.chat(world_game, "J'observe.")
    await harness.drain()
    harness.llm._responses["narration"] = narration_with(
        narrative_text=f"{DESCRIPTOR} te tend sa carte.",
        entity_reveals=[
            {
                "entity_type": "character",
                "current_name": DESCRIPTOR,
                "real_name": revealed,
            }
        ],
    )
    await harness.chat(world_game, "Je lui demande son nom.")
    await harness.drain()

    async def world() -> dict:
        r = await harness.client.get(
            f"/api/games/{world_game}/world", headers=harness.headers
        )
        return r.json()

    async def merges() -> int:
        async with harness.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM entity_merges WHERE game_id = $1", world_game
            )

    assert await merges() == 1
    assert _holds(await world(), revealed)

    r = await harness.client.post(
        f"/api/games/{world_game}/rollback",
        json={"messageId": str(await last_user_message_id(harness, world_game))},
        headers=harness.headers,
    )
    assert r.status_code == 200, r.text

    annotations = (
        await harness.client.get(
            "/api/tooltips/annotations",
            params={"gameId": world_game},
            headers=harness.headers,
        )
    ).json()
    spans = [a for m in annotations["messages"] for a in m["annotations"]]
    tooltips = {}
    for span in spans:
        r = await harness.client.get(
            "/api/tooltips/entity",
            params={"gameId": world_game, "id": span["entity_id"]},
            headers=harness.headers,
        )
        tooltips[span["entity_id"]] = r.json()
    assert await merges() == 0
    assert {DESCRIPTOR, other} <= {s["label"] for s in spans}
    assert all(t["found"] for t in tooltips.values())
    assert {t["tooltip"]["name"] for t in tooltips.values()} >= {DESCRIPTOR, other}
    assert not _holds(await world(), revealed)
    assert not any(_holds(p, revealed) for p in (annotations, tooltips))
