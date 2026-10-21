"""Tooltips and world panel on the identity model (#152, #155, spec §4.9): annotations are
the stored mentions, served by entity id with what the player may read
(display_for_player, never a secret name); a tooltip is read by id, and an NPC the PC has
not identified shows only what anyone can observe."""

import json
from uuid import UUID

import pytest
from helpers import auth_headers, last_user_message_id, narration_with

from domain.identity import MentionRow
from packs.loader import load_lang
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


async def _mentions(
    test_pool, game_id: UUID, content: str, spans: list, sequence: int = 1
) -> UUID:
    """A narrator message holding `content` at `sequence`, with a stored mention per
    (start, end, entity id) of `spans`."""
    from repos import entities

    async with test_pool.acquire() as conn:
        conversation = await conn.fetchval(
            "INSERT INTO conversations (game_id, start_cycle) VALUES ($1, 1) RETURNING id",
            game_id,
        )
        message = await conn.fetchval(
            """INSERT INTO messages (game_id, conversation_id, role, content, sequence)
               VALUES ($1, $2, 'assistant', $3, $4) RETURNING id""",
            game_id,
            conversation,
            content,
            sequence,
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
    """The relation line is the protagonist's latest open relation to the NPC, never
    one of the NPC's own relations (a workplace, a home) nor an ended one."""
    game_id = await _world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        ossek = await conn.fetchval(
            "UPDATE characters SET known_by_protagonist = true"
            " WHERE game_id = $1 AND true_name = 'Ossek' RETURNING id",
            game_id,
        )
        protagonist = await _id(test_pool, game_id, "entity_type = 'protagonist'")
        place = await _id(test_pool, game_id, "entity_type = 'location'")
        await conn.execute(
            "DELETE FROM relations WHERE game_id = $1 AND (source_id = $2 OR target_id = $2)",
            game_id,
            ossek,
        )
        await conn.executemany(
            """INSERT INTO relations
                   (game_id, type, source_id, target_id, start_cycle, end_cycle, created_at)
               VALUES ($1, $2, $3, $4, 1, $5, now() + make_interval(secs => $6))""",
            [
                (game_id, "works_at", ossek, place, None, 30),
                (game_id, "knows", protagonist, ossek, None, 0),
                (game_id, "friend_of", protagonist, ossek, None, 10),
                (game_id, "enemy_of", protagonist, ossek, 1, 20),
            ],
        )

    payload = await _tooltip(client, test_user, game_id, ossek)

    assert payload["found"] is True and payload["tooltip"]["name"] == "Ossek"
    assert any(info.startswith("Métier") for info in payload["tooltip"]["infos"])
    assert payload["tooltip"]["relation"] == "friend_of"


async def test_a_known_npc_without_a_protagonist_relation_shows_none(
    client, test_user, test_pool
):
    game_id = await _world(client, test_user, test_pool)
    async with test_pool.acquire() as conn:
        ossek = await conn.fetchval(
            "UPDATE characters SET known_by_protagonist = true"
            " WHERE game_id = $1 AND true_name = 'Ossek' RETURNING id",
            game_id,
        )
        place = await _id(test_pool, game_id, "entity_type = 'location'")
        await conn.execute(
            "DELETE FROM relations WHERE game_id = $1 AND target_id = $2",
            game_id,
            ossek,
        )
        await conn.execute(
            """INSERT INTO relations (game_id, type, source_id, target_id, start_cycle)
               VALUES ($1, 'works_at', $2, $3, 1)""",
            game_id,
            ossek,
            place,
        )

    payload = await _tooltip(client, test_user, game_id, ossek)

    assert payload["found"] is True and payload["tooltip"]["relation"] is None


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
        await conn.execute(
            "INSERT INTO objects (game_id, name, category) VALUES ($1, 'Clé d''os', 'outil')",
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
        foreign_arc = await conn.fetchval(
            "SELECT id FROM narrative_arcs WHERE game_id = $1 LIMIT 1", other_game
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
        "object",
        "protagonist",
        "companion",
    } <= types
    assert foreign_arc is not None
    for missing in (UUID(int=0), foreign, foreign_arc):
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


async def test_batch_tooltips_match_the_single_lookups(client, test_user, test_pool):
    """Ruling R52: `/tooltips/entities` serves, by the id asked for, the tooltip each id
    gets from `/tooltips/entity` (an unidentified NPC, a merge tombstone's survivor, an
    arc); an id that is no entity nor arc of the game is absent."""
    from api.tooltips import MAX_TOOLTIP_IDS
    from repos import entities

    game_id = await _world(client, test_user, test_pool)
    justine = await _hide_under_a_descriptor(test_pool, game_id)
    async with test_pool.acquire() as conn:
        arc = await conn.fetchval(
            "SELECT id FROM narrative_arcs WHERE game_id = $1 LIMIT 1", game_id
        )
        place = await conn.fetchval(
            "SELECT id FROM locations WHERE game_id = $1 LIMIT 1", game_id
        )
        keep = await conn.fetchval(
            "INSERT INTO characters (game_id, true_name, known_by_protagonist)"
            " VALUES ($1, 'Tesk Vahrun', true) RETURNING id",
            game_id,
        )
        tombstone = await conn.fetchval(
            "INSERT INTO characters (game_id, descriptor) VALUES ($1, $2) RETURNING id",
            game_id,
            "Le Kethari au tablier",
        )
        await entities.merge_entities(conn, keep, tombstone, "test", None)
    missing = "00000000-0000-0000-0000-0000000000ff"
    ids = [str(justine), str(arc), str(place), str(tombstone), missing]
    found = ids[:4]
    headers = auth_headers(test_user["token"])

    resp = await client.get(
        "/api/tooltips/entities",
        params={"gameId": str(game_id), "ids": ",".join(ids)},
        headers=headers,
    )

    assert resp.status_code == 200
    batch = resp.json()["tooltips"]
    assert set(batch) == set(found)
    for entity_id in found:
        single = await _tooltip(client, test_user, game_id, entity_id)
        assert batch[entity_id] == single["tooltip"]
    assert batch[str(justine)]["name"] == DESCRIPTOR
    # The tombstone is keyed by the id asked for and carries its survivor's tooltip.
    assert str(keep) not in batch
    assert batch[str(tombstone)]["name"] == "Tesk Vahrun"
    too_many = ",".join(str(UUID(int=i)) for i in range(1, MAX_TOOLTIP_IDS + 2))
    for bad in ("not-a-uuid", "", too_many):
        resp = await client.get(
            "/api/tooltips/entities",
            params={"gameId": str(game_id), "ids": bad},
            headers=headers,
        )
        assert resp.status_code == 422, bad


async def test_annotations_page_back_with_before(client, test_user, test_pool):
    """`before` serves the page of annotated messages older than a sequence, so the
    frontend covers every message it shows, not only the latest `limit`."""
    game_id = await _world(client, test_user, test_pool)
    place = await _id(test_pool, game_id, "entity_type = 'location'")
    async with test_pool.acquire() as conn:
        name = await conn.fetchval("SELECT display_for_player($1)", place)
    ids = [
        await _mentions(test_pool, game_id, name, [(0, len(name), place)], sequence)
        for sequence in (1, 2, 3)
    ]

    async def page(**params) -> list[str]:
        resp = await client.get(
            "/api/tooltips/annotations",
            params={"gameId": str(game_id), **params},
            headers=auth_headers(test_user["token"]),
        )
        assert resp.status_code == 200
        return [m["message_id"] for m in resp.json()["messages"]]

    assert await page(limit=2) == [str(ids[2]), str(ids[1])]
    assert await page(limit=2, before=2) == [str(ids[0])]
    assert await page(limit=2, before=1) == []


async def test_tooltip_payloads_never_contain_a_hidden_true_name(
    client, test_user, test_pool
):
    """L = 0 on the whole JSON of the annotations and the tooltips: the unidentified
    NPC's true name, held by its occupation, ambient and description, and the name of a
    whole-secret place. The world panel has its own test
    (test_world_panel_never_contains_a_hidden_true_name)."""
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
    # A place is no person: the neutral unknown label (M4).
    assert payloads_["place"]["tooltip"]["name"] == load_lang("fr").unknown_entity_label


async def test_world_panel_never_contains_a_hidden_true_name(
    client, test_user, test_pool
):
    """Ruling R51: L = 0 on the world panel JSON. The unidentified NPC is listed under its
    descriptor, `known: false`, without its occupation and description (which hold its
    true name), and its workplace, a whole-secret place, is not named; that place and a
    whole-secret organization are left out, as is the parent of a place inside it; a
    secret place with a readable descriptor is listed under it, its sector (which holds
    the secret name) left out."""
    from repos import entities

    game_id = await _world(client, test_user, test_pool)
    justine = await _hide_under_a_descriptor(test_pool, game_id)
    secret_org = "Cercle Vauquelin"
    vault_name = f"Ossuaire {SECRET_PLACE}"
    async with test_pool.acquire() as conn:
        crypt = await conn.fetchval(
            "INSERT INTO locations (game_id, name) VALUES ($1, $2) RETURNING id",
            game_id,
            SECRET_PLACE,
        )
        cellar = await conn.fetchval(
            "INSERT INTO locations (game_id, name, parent_id) VALUES ($1, 'Cave basse', $2)"
            " RETURNING id",
            game_id,
            crypt,
        )
        vault = await conn.fetchval(
            "INSERT INTO locations (game_id, name, sector) VALUES ($1, $2, $3) RETURNING id",
            game_id,
            vault_name,
            f"Sous {vault_name}",
        )
        org = await conn.fetchval(
            "INSERT INTO organizations (game_id, name) VALUES ($1, $2) RETURNING id",
            game_id,
            secret_org,
        )
        await conn.execute(
            "UPDATE entity_aliases SET secret = true WHERE entity_id = ANY($1::uuid[])",
            [crypt, vault, org],
        )
        await entities.insert_alias(
            conn, game_id, vault, "location", "la salle aux os", "descriptor",
            known=True, source="world_gen",
        )  # fmt: skip
        await conn.execute(
            "UPDATE characters SET occupation = $2, description = $3, workplace_id = $4"
            " WHERE id = $1",
            justine,
            f"assistante de {SECRET_NAME}",
            f"{SECRET_NAME}, ancienne pilote.",
            crypt,
        )

    r = await client.get(
        f"/api/games/{game_id}/world", headers=auth_headers(test_user["token"])
    )
    assert r.status_code == 200
    world = r.json()

    for secret in (SECRET_NAME, SECRET_PLACE, "Vauquelin"):
        assert not _holds(world, secret), secret
    [npc] = [n for n in world["npcs"] if n["id"] == str(justine)]
    assert (npc["name"], npc["known"]) == (DESCRIPTOR, False)
    assert (npc["occupation"], npc["description"], npc["location"]) == (None,) * 3
    assert (npc["relationship"], npc["relation_level"]) == (None, None)
    places = {loc["id"]: loc for loc in world["locations"]}
    assert str(crypt) not in places
    assert places[str(cellar)]["parent"] is None
    assert (places[str(vault)]["name"], places[str(vault)]["sector"]) == (
        "la salle aux os",
        None,
    )
    assert str(org) not in {o["id"] for o in world["organizations"]}


async def test_free_text_holding_an_entitys_own_secret_name_never_reaches_a_tooltip(
    client, test_user, test_pool
):
    """I1: L = 0 on the tooltip JSON. A place whose name is secret but which has a readable
    descriptor keeps its descriptor as name, and its sector and atmosphere, which hold the
    secret name, are left out; an identified NPC with a secret identity keeps its name, but
    its occupation and ambient, which hold the secret identity, are left out."""
    from repos import entities

    game_id = await _world(client, test_user, test_pool)
    alias = "Le Corbeau Noir"
    async with test_pool.acquire() as conn:
        place = await conn.fetchval(
            "INSERT INTO locations (game_id, name, sector, atmosphere, location_type)"
            " VALUES ($1, $2, $3, $4, 'crypt') RETURNING id",
            game_id,
            SECRET_PLACE,
            f"Sous {SECRET_PLACE}",
            f"froide comme {SECRET_PLACE}",
        )
        await conn.execute(
            "UPDATE entity_aliases SET secret = true WHERE entity_id = $1", place
        )
        await entities.insert_alias(
            conn, game_id, place, "location", "la crypte humide", "descriptor",
            known=True, source="world_gen",
        )  # fmt: skip
        ossek = await conn.fetchval(
            "UPDATE characters SET known_by_protagonist = true, mood = 'calme',"
            " species = NULL,"
            " occupation = $2, ambient = $3"
            " WHERE game_id = $1 AND true_name = 'Ossek' RETURNING id",
            game_id,
            f"agent du {alias}",
            f"{alias} essuie le comptoir",
        )
        await entities.insert_alias(
            conn, game_id, ossek, "character", alias, "true_name",
            known=False, secret=True, source="world_gen",
        )  # fmt: skip

    place_tooltip = await _tooltip(client, test_user, game_id, place)
    npc_tooltip = await _tooltip(client, test_user, game_id, ossek)

    assert not _holds(place_tooltip, SECRET_PLACE)
    assert not _holds(place_tooltip, "Vauquelin")
    assert place_tooltip["tooltip"]["name"] == "la crypte humide"
    assert place_tooltip["tooltip"]["infos"] == ["Type: crypt"]
    assert not _holds(npc_tooltip, alias)
    assert npc_tooltip["tooltip"]["name"] == "Ossek"
    assert npc_tooltip["tooltip"]["infos"] == ["Humeur: calme"]


async def test_unknown_npc_tooltip_drops_an_ambient_holding_its_secret_descriptor(
    client, test_user, test_pool
):
    """M2: a secret descriptor is a hidden name like any secret alias."""
    from repos import entities

    game_id = await _world(client, test_user, test_pool)
    justine = await _hide_under_a_descriptor(test_pool, game_id)
    async with test_pool.acquire() as conn:
        await entities.insert_alias(
            conn, game_id, justine, "character", "la balafrée", "descriptor",
            known=False, secret=True, source="world_gen",
        )  # fmt: skip
        await conn.execute(
            "UPDATE characters SET ambient = 'la balafrée attend', mood = 'lasse'"
            " WHERE id = $1",
            justine,
        )

    payload = await _tooltip(client, test_user, game_id, justine)

    assert payload["tooltip"]["infos"] == ["Humeur: lasse"]


async def test_annotation_limit_counts_only_messages_with_a_readable_mention(
    client, test_user, test_pool
):
    """M3: the latest message names only a whole-secret place; with limit 1 the older
    readable message is served."""
    game_id = await _world(client, test_user, test_pool)
    justine = await _hide_under_a_descriptor(test_pool, game_id)
    async with test_pool.acquire() as conn:
        place = await conn.fetchval(
            "INSERT INTO locations (game_id, name) VALUES ($1, $2) RETURNING id",
            game_id,
            SECRET_PLACE,
        )
        await conn.execute(
            "UPDATE entity_aliases SET secret = true WHERE entity_id = $1", place
        )
    readable = await _mentions(test_pool, game_id, "Elle attend.", [(0, 4, justine)])
    hidden = await _mentions(test_pool, game_id, "La crypte.", [(3, 9, place)])
    async with test_pool.acquire() as conn:
        await conn.execute("UPDATE messages SET sequence = 2 WHERE id = $1", hidden)

    resp = await client.get(
        "/api/tooltips/annotations",
        params={"gameId": str(game_id), "limit": 1},
        headers=auth_headers(test_user["token"]),
    )

    assert [m["message_id"] for m in resp.json()["messages"]] == [str(readable)]


def test_tooltip_service_holds_no_display_text():
    """I2: the line labels, the unknown labels and the default species live in the packs
    and the identity config, never in services/tooltips.py."""
    import ast
    from pathlib import Path

    from config import get_identity_config
    from packs.loader import available_langs

    texts = {get_identity_config().default_species}
    for lang in available_langs():
        pack = load_lang(lang)
        texts |= set(pack.tooltip_labels.values())
        texts |= {pack.unknown_character_label}
        texts |= {pack.unknown_entity_label}
    source = Path(__file__).resolve().parents[1] / "services" / "tooltips.py"
    literals = {
        node.value
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert literals & texts == set()


def test_an_english_game_reads_the_english_labels_and_its_genre_species():
    """I2: the labels follow the game's language pack; the species not worth a line
    follows the genre pack, else the identity config."""
    from uuid import uuid4

    from config import get_identity_config
    from repos.entities import TooltipRow
    from packs.loader import TOOLTIP_LABEL_KEYS, available_langs
    from services.tooltips import CHECKED_FIELDS, Display, entity_tooltip

    labels = load_lang("en").tooltip_labels
    display = Display.for_packs("en", None)
    common = get_identity_config().default_species
    row = TooltipRow(
        uuid4(), "character", "Rafe Collins", False,
        {"known_by_protagonist": True, "true_name": "Rafe Collins", "mood": "tired",
         "occupation": "grinder", "species": common},
        None, frozenset(),
    )  # fmt: skip
    rare = TooltipRow(
        uuid4(), "character", "Rafe Collins", False,
        {"known_by_protagonist": True, "true_name": "Rafe Collins", "species": "elf"},
        None, frozenset(),
    )  # fmt: skip

    assert entity_tooltip(row, display).infos == [
        f"{labels['occupation']}: grinder",
        f"{labels['mood']}: tired",
    ]
    assert entity_tooltip(rare, display).infos == [f"{labels['species']}: elf"]
    assert display.default_species == common
    assert set(CHECKED_FIELDS) - {"ambient", "description"} == TOOLTIP_LABEL_KEYS
    for lang in available_langs():
        assert set(load_lang(lang).tooltip_labels) == TOOLTIP_LABEL_KEYS


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

    async def first_turn_spans() -> dict[str, dict]:
        """The turn-1 annotation of each descriptor, by its label at turn 1."""
        r = await harness.client.get(
            "/api/tooltips/annotations",
            params={"gameId": world_game},
            headers=harness.headers,
        )
        [turn_1] = [
            m for m in r.json()["messages"] if m["message_id"] == str(turn_1_id)
        ]
        return {
            text[a["start"] : a["end"]].casefold(): a for a in turn_1["annotations"]
        }

    async with harness.pool.acquire() as conn:
        turn_1_id = await conn.fetchval(
            """SELECT id FROM messages WHERE game_id = $1 AND role = 'assistant'
               ORDER BY sequence DESC OFFSET 1 LIMIT 1""",
            world_game,
        )
        text = await conn.fetchval(
            "SELECT content FROM messages WHERE id = $1", turn_1_id
        )
        survivor = await conn.fetchval(
            "SELECT kept_id FROM entity_merges WHERE game_id = $1", world_game
        )
    merged = (await first_turn_spans())[DESCRIPTOR.casefold()]
    assert await merges() == 1
    assert _holds(await world(), revealed)
    assert (merged["entity_id"], merged["label"]) == (str(survivor), revealed)

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
    async with harness.pool.acquire() as conn:
        hidden_npc = await conn.fetchval(
            "SELECT id FROM characters WHERE game_id = $1 AND descriptor = $2",
            world_game,
            DESCRIPTOR,
        )
    restored = (await first_turn_spans())[DESCRIPTOR.casefold()]
    assert (restored["entity_id"], restored["label"]) == (str(hidden_npc), DESCRIPTOR)
    assert {DESCRIPTOR, other} <= {s["label"] for s in spans}
    assert all(t["found"] for t in tooltips.values())
    assert {t["tooltip"]["name"] for t in tooltips.values()} >= {DESCRIPTOR, other}
    assert not _holds(await world(), revealed)
    assert not any(_holds(p, revealed) for p in (annotations, tooltips))
