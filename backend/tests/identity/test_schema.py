"""Identity schema (spec §4.2, #152): the registry id is the domain id, handles, typed
aliases, normalised uniqueness, typed find_entity, display_for_player, merge_entities."""

import json
from uuid import UUID, uuid4

import asyncpg
import pytest

from packs.loader import load_lang
from repos import turns
from repos.uow import uow

pytestmark = pytest.mark.integration


async def _game(conn, user_id: UUID, language: str | None = "fr") -> UUID:
    return await conn.fetchval(
        "INSERT INTO games (user_id, language) VALUES ($1, $2) RETURNING id",
        user_id,
        language,
    )


@pytest.fixture
async def game(test_pool, test_user) -> UUID:
    async with test_pool.acquire() as conn:
        return await _game(conn, test_user["id"])


async def _character(conn, game_id: UUID, **fields) -> UUID:
    fields = {"game_id": game_id, **fields}
    cols = ", ".join(fields)
    marks = ", ".join(f"${i}" for i in range(1, len(fields) + 1))
    return await conn.fetchval(
        f"INSERT INTO characters ({cols}) VALUES ({marks}) RETURNING id",
        *fields.values(),
    )


async def _named(conn, table: str, game_id: UUID, name: str) -> UUID:
    return await conn.fetchval(
        f"INSERT INTO {table} (game_id, name) VALUES ($1, $2) RETURNING id",
        game_id,
        name,
    )


async def _registry(conn, entity_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM entity_registry WHERE id = $1", entity_id)


async def _find(conn, game_id: UUID, ref: str, entity_type: str) -> UUID | None:
    return await conn.fetchval(
        "SELECT find_entity($1, $2, $3)", game_id, ref, entity_type
    )


async def _alias(conn, game_id: UUID, entity_id: UUID, alias: str, kind: str) -> None:
    await conn.execute(
        """INSERT INTO entity_aliases (game_id, entity_id, entity_type, alias, kind, known,
                                       source)
           SELECT game_id, id, entity_type, $3, $4, true, 'system'
             FROM entity_registry WHERE game_id = $1 AND id = $2""",
        game_id,
        entity_id,
        alias,
        kind,
    )


async def test_domain_insert_registers_the_same_id_with_a_handle(test_pool, game):
    async with test_pool.acquire() as conn:
        first = await _character(conn, game, true_name="Elara Voss")
        second = await _character(conn, game, descriptor="La Kethari âgée")
        reg_first, reg_second = (
            await _registry(conn, first),
            await _registry(conn, second),
        )
        labels = await conn.fetch(
            "SELECT entity_id, alias, kind, known, source FROM entity_aliases"
            " WHERE game_id = $1 ORDER BY alias",
            game,
        )

    assert reg_first["entity_type"] == "character"
    assert reg_first["name"] == "Elara Voss"
    assert reg_first["name_norm"] == "elara voss"
    assert (reg_first["handle"], reg_second["handle"]) == (1, 2)
    assert reg_first["created_turn_id"] is None
    # The name the registry starts with is an alias of its kind (true name unknown).
    assert [tuple(r) for r in labels] == [
        (first, "Elara Voss", "true_name", False, "system"),
        (second, "La Kethari âgée", "descriptor", True, "system"),
    ]


async def test_registry_rows_created_in_a_turn_carry_the_turn(test_pool, game):
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            loc = await _named(conn, "locations", game, "Quai 9")
        reg = await _registry(conn, loc)
        label = await conn.fetchrow(
            "SELECT kind, known, turn_id FROM entity_aliases WHERE entity_id = $1", loc
        )
    assert reg["created_turn_id"] == turn_id
    assert tuple(label) == ("label", True, turn_id)


async def test_companion_is_registered(test_pool, game):
    async with test_pool.acquire() as conn:
        comp = await _named(conn, "companions", game, "Nyx")
        prot = await _named(conn, "protagonists", game, "Rafe")
        reg = await _registry(conn, comp)
        found = await _find(conn, game, "COMPANION", "companion")
        pc = await _find(conn, game, " protagonist\n", "protagonist")
    assert (reg["entity_type"], reg["name"]) == ("companion", "Nyx")
    assert found == comp
    assert pc == prot


async def test_name_follows_true_name_then_descriptor(test_pool, game):
    async with test_pool.acquire() as conn:
        char = await _character(conn, game, descriptor="Le garde du sas")
        name_before = await conn.fetchval(
            "SELECT name FROM characters WHERE id = $1", char
        )
        await conn.execute(
            "UPDATE characters SET true_name = 'Tesk Vahrun-Oo' WHERE id = $1", char
        )
        row = await conn.fetchrow(
            "SELECT name, descriptor FROM characters WHERE id = $1", char
        )
        reg = await _registry(conn, char)
    assert name_before == "Le garde du sas"
    assert tuple(row) == ("Tesk Vahrun-Oo", "Le garde du sas")
    assert (reg["name"], reg["name_norm"]) == ("Tesk Vahrun-Oo", "tesk vahrun-oo")


async def test_check_requires_a_true_name_or_a_descriptor(test_pool, game):
    async with test_pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await _character(conn, game, name="Sans nom")
        char = await _character(conn, game, true_name="Voss")
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE characters SET true_name = NULL WHERE id = $1", char
            )


async def test_normalized_uniqueness_rejects_case_and_article_variants(test_pool, game):
    async with test_pool.acquire() as conn:
        await _character(conn, game, true_name="Voss")
        with pytest.raises(asyncpg.UniqueViolationError):
            await _character(conn, game, true_name="voss")
        await _named(conn, "locations", game, "Byte Bar")
        with pytest.raises(asyncpg.UniqueViolationError):
            await _named(conn, "locations", game, "Le Byte Bar")
        # Another type may carry the same name.
        org = await _named(conn, "organizations", game, "Voss")
    assert org is not None


async def test_norm_fill_trigger_uses_the_game_language(test_pool, test_user):
    async with test_pool.acquire() as conn:
        en = await _game(conn, test_user["id"], "en")
        fr = await _game(conn, test_user["id"], "fr")
        guild = await _named(conn, "organizations", en, "The Guild")
        guilde = await _named(conn, "organizations", fr, "La Guilde")
        alias_norm = await conn.fetchval(
            "SELECT alias_norm FROM entity_aliases WHERE entity_id = $1", guild
        )
        norms = [(await _registry(conn, i))["name_norm"] for i in (guild, guilde)]
    assert norms == ["guild", "guilde"]
    assert alias_norm == "guild"


async def test_norm_fill_trigger_raises_without_a_pack(test_pool, test_user):
    async with test_pool.acquire() as conn:
        async with conn.transaction():
            # games.language references lang_packs (deferrable): a game whose pack is gone.
            await conn.execute("SET CONSTRAINTS ALL DEFERRED")
            orphan = await _game(conn, test_user["id"], "xx")
            with pytest.raises(asyncpg.RaiseError, match="missing lang pack xx"):
                async with conn.transaction():
                    await _named(conn, "locations", orphan, "Quai 9")
            await conn.execute("DELETE FROM games WHERE id = $1", orphan)
        no_language = await _game(conn, test_user["id"], None)
        with pytest.raises(asyncpg.RaiseError, match="missing lang pack"):
            await _named(conn, "locations", no_language, "Quai 9")


async def test_games_get_the_default_language_at_creation(test_pool, test_user):
    from config import get_identity_config
    from kg.populator import KnowledgeGraphPopulator

    async with test_pool.acquire() as conn:
        game_id = await KnowledgeGraphPopulator(None).create_game(
            conn, "Partie", user_id=test_user["id"]
        )
        language = await conn.fetchval(
            "SELECT language FROM games WHERE id = $1", game_id
        )
    assert language == get_identity_config().default_language


async def test_delete_keeps_a_tombstone_only_when_merged(test_pool, game):
    async with test_pool.acquire() as conn:
        gone = await _character(conn, game, true_name="Gommé")
        kept = await _character(conn, game, true_name="Gardé")
        target = await _character(conn, game, true_name="Cible")
        await conn.execute(
            "UPDATE entity_registry SET merged_into = $2 WHERE id = $1", kept, target
        )
        await conn.execute("DELETE FROM characters WHERE id = ANY($1)", [gone, kept])
        assert await _registry(conn, gone) is None
        tombstone = await _registry(conn, kept)
        aliases = await conn.fetchval(
            "SELECT count(*) FROM entity_aliases WHERE entity_id = $1", gone
        )
    assert tombstone["merged_into"] == target
    assert aliases == 0


async def test_find_entity_requires_a_type_and_returns_null_on_ambiguity(
    test_pool, game
):
    async with test_pool.acquire() as conn:
        elara = await _character(conn, game, true_name="Elara Voss")
        marek = await _character(conn, game, true_name="Marek Voss")
        kethari = await _character(conn, game, true_name="Nahle Irun-Sa")
        await _alias(conn, game, elara, "Voss", "short")
        await _alias(conn, game, marek, "Voss", "short")
        await _alias(conn, game, kethari, "La Kethari âgée", "descriptor")
        old = await _character(conn, game, descriptor="La vieille")
        await conn.execute(
            "UPDATE entity_registry SET merged_into = $2 WHERE id = $1", old, kethari
        )

        assert await _find(conn, game, "Voss", "character") is None
        assert await _find(conn, game, "E2", "character") == marek
        assert await _find(conn, game, "E2", "location") is None
        assert await _find(conn, game, "Kethari âgée", "character") == kethari
        assert await _find(conn, game, "la kethari agee", "character") == kethari
        assert await _find(conn, game, "Elara Voss", "character") == elara
        assert await _find(conn, game, "elara voss", "location") is None
        assert await _find(conn, game, str(marek), "character") == marek
        assert await _find(conn, game, str(uuid4()), "character") is None
        assert await _find(conn, game, "La vieille", "character") == kethari
        assert await _find(conn, game, f"E{4}", "character") == kethari
        assert await _find(conn, game, "", "character") is None
        with pytest.raises(asyncpg.RaiseError, match="type"):
            await _find(conn, game, "Elara Voss", None)
        with pytest.raises(asyncpg.UndefinedFunctionError):
            await conn.fetchval("SELECT find_entity($1, $2)", game, "Elara Voss")


async def test_find_fact_reads_a_handle_or_an_id(test_pool, game):
    async with test_pool.acquire() as conn:
        fact = await conn.fetchval(
            "SELECT create_fact($1, 1, 'action', 'Un fait')", game
        )
        handle = await conn.fetchval("SELECT handle FROM facts WHERE id = $1", fact)
        assert (
            await conn.fetchval("SELECT find_fact($1, $2)", game, f"F{handle}") == fact
        )
        assert await conn.fetchval("SELECT find_fact($1, $2)", game, str(fact)) == fact
        assert await conn.fetchval("SELECT find_fact($1, 'F999')", game) is None


async def test_create_fact_and_end_relation_take_ids(test_pool, game):
    async with test_pool.acquire() as conn:
        voss = await _character(conn, game, true_name="Voss")
        quai = await _named(conn, "locations", game, "Quai 9")
        fact = await conn.fetchval(
            "SELECT create_fact($1, 1, 'action', 'Un fait', p_participants => $2::jsonb)",
            game,
            [{"entity_id": str(voss), "role": "actor"}],
        )
        participants = await conn.fetch(
            "SELECT entity_id, role FROM fact_participants WHERE fact_id = $1", fact
        )
        await conn.fetchval(
            "SELECT upsert_relation($1, $2, $3, 'frequents'::relation_type, 1)",
            game,
            voss,
            quai,
        )
        ended = await conn.fetchval(
            "SELECT end_relation($1, $2, $3, 'frequents'::relation_type, 2, 'parti')",
            game,
            voss,
            quai,
        )
    assert [tuple(r) for r in participants] == [(voss, "actor")]
    assert ended is True


async def test_display_for_player_hides_an_unknown_true_name(test_pool, game):
    unknown_label = load_lang("fr").unknown_character_label
    async with test_pool.acquire() as conn:
        hidden = await _character(
            conn, game, true_name="Nahle Irun-Sa", descriptor="La Kethari âgée"
        )
        nameless = await _character(conn, game, true_name="Tesk Vahrun-Oo")
        known = await _character(
            conn,
            game,
            true_name="Elara Voss",
            descriptor="La pilote",
            known_by_protagonist=True,
        )
        quai = await _named(conn, "locations", game, "Quai 9")
        merged = await _character(conn, game, descriptor="La vieille")
        await conn.execute(
            "UPDATE entity_registry SET merged_into = $2 WHERE id = $1", merged, known
        )
        shown = [
            await conn.fetchval("SELECT display_for_player($1)", i)
            for i in (hidden, nameless, known, quai, merged)
        ]
    assert shown == [
        "La Kethari âgée",
        unknown_label,
        "Elara Voss",
        "Quai 9",
        "Elara Voss",
    ]


async def test_v_active_arcs_shows_display_names_and_ids(test_pool, game):
    async with test_pool.acquire() as conn:
        hidden = await _character(
            conn, game, true_name="Nahle Irun-Sa", descriptor="La Kethari âgée"
        )
        arc = await conn.fetchval(
            "INSERT INTO narrative_arcs (game_id, title, created_cycle)"
            " VALUES ($1, 'Arc', 1) RETURNING id",
            game,
        )
        await conn.execute(
            "INSERT INTO arc_participants (arc_id, entity_id, role) VALUES ($1, $2, 'cible')",
            arc,
            hidden,
        )
        participants = await conn.fetchval(
            "SELECT participants FROM v_active_arcs WHERE id = $1", arc
        )
    assert len(participants) == 1
    part = participants[0]
    part = part if isinstance(part, dict) else json.loads(part)
    assert part == {
        "name": "La Kethari âgée",
        "type": "character",
        "role": "cible",
        "entity_id": str(hidden),
        "handle": 1,
    }


async def _count(conn, sql: str, *args) -> int:
    return await conn.fetchval(sql, *args)


async def test_merge_entities_repoints_every_edge_and_leaves_a_tombstone(
    test_pool, game
):
    async with test_pool.acquire() as conn:
        keep = await _character(conn, game, descriptor="La Kethari âgée", mood="calme")
        drop = await _character(
            conn,
            game,
            true_name="Nahle Irun-Sa",
            occupation="pilote",
            known_by_protagonist=True,
        )
        other = await _character(conn, game, true_name="Voss")
        quai = await _named(conn, "locations", game, "Quai 9")
        quai_bis = await _named(conn, "locations", game, "Quai neuf")
        obj = await _named(conn, "objects", game, "Clé")
        worker = await _character(conn, game, true_name="Docker", workplace_id=quai_bis)
        await _alias(conn, game, drop, "Nahle", "short")
        for source, target in ((drop, other), (keep, other), (other, drop)):
            await conn.fetchval(
                "SELECT upsert_relation($1, $2, $3, 'knows'::relation_type, 1)",
                game,
                source,
                target,
            )
        fact = await conn.fetchval(
            "SELECT create_fact($1, 1, 'action', 'Un fait', p_participants => $2::jsonb)",
            game,
            [
                {"entity_id": str(drop), "role": "actor"},
                {"entity_id": str(keep), "role": "witness"},
            ],
        )
        arc = await conn.fetchval(
            "INSERT INTO narrative_arcs (game_id, title, created_cycle, owner_id)"
            " VALUES ($1, 'Arc', 1, $2) RETURNING id",
            game,
            drop,
        )
        arc_part = await conn.fetchval(
            "INSERT INTO arc_participants (arc_id, entity_id, role)"
            " VALUES ($1, $2, 'cible') RETURNING id",
            arc,
            drop,
        )
        await conn.execute(
            "INSERT INTO inventory (game_id, object_id, owner_id, quantity)"
            " VALUES ($1, $2, $3, 2), ($1, $2, $4, 3)",
            game,
            obj,
            drop,
            keep,
        )

        merge_id = await conn.fetchval(
            "SELECT merge_entities($1, $2, 'reveal', 'evidence')", keep, drop
        )
        loc_merge = await conn.fetchval(
            "SELECT merge_entities($1, $2, 'duplicate', NULL)", quai, quai_bis
        )

        merge = await conn.fetchrow(
            "SELECT * FROM entity_merges WHERE id = $1", merge_id
        )
        tombstone = await _registry(conn, drop)
        kept_row = await conn.fetchrow("SELECT * FROM characters WHERE id = $1", keep)
        kept_reg = await _registry(conn, keep)
        open_rel = await conn.fetch(
            "SELECT source_id, target_id FROM relations"
            " WHERE game_id = $1 AND end_cycle IS NULL ORDER BY source_id, target_id",
            game,
        )
        assert (
            await _count(conn, "SELECT count(*) FROM characters WHERE id = $1", drop)
            == 0
        )
        assert (
            await _count(
                conn,
                "SELECT count(*) FROM relations WHERE $1 IN (source_id, target_id)"
                " AND end_cycle IS NULL",
                drop,
            )
            == 0
        )
        fact_parts = await conn.fetch(
            "SELECT entity_id FROM fact_participants WHERE fact_id = $1", fact
        )
        arc_parts = await conn.fetch(
            "SELECT entity_id FROM arc_participants WHERE arc_id = $1", arc
        )
        arc_owner = await conn.fetchval(
            "SELECT owner_id FROM narrative_arcs WHERE id = $1", arc
        )
        inventory = await conn.fetch(
            "SELECT owner_id, quantity FROM inventory WHERE object_id = $1", obj
        )
        moved_alias = await conn.fetchval(
            "SELECT kind FROM entity_aliases WHERE entity_id = $1 AND alias = 'Nahle'",
            keep,
        )
        adopted = await conn.fetchval(
            "SELECT kind FROM entity_aliases WHERE entity_id = $1 AND alias = 'Nahle Irun-Sa'",
            keep,
        )
        former = await conn.fetchval(
            "SELECT kind FROM entity_aliases WHERE entity_id = $1 AND alias = 'Quai neuf'",
            quai,
        )
        workplace = await conn.fetchval(
            "SELECT workplace_id FROM characters WHERE id = $1", worker
        )
        events = await _count(
            conn,
            "SELECT count(*) FROM identity_events WHERE game_id = $1 AND kind = 'merge'",
            game,
        )

    assert tombstone["merged_into"] == keep
    assert (kept_row["true_name"], kept_row["descriptor"]) == (
        "Nahle Irun-Sa",
        "La Kethari âgée",
    )
    assert kept_row["occupation"] == "pilote" and kept_row["mood"] == "calme"
    assert kept_row["known_by_protagonist"] is True
    assert kept_reg["name"] == "Nahle Irun-Sa"
    # keep -> other existed: drop -> other is closed, not duplicated; other -> drop moves.
    assert sorted(map(tuple, open_rel)) == sorted([(keep, other), (other, keep)])
    assert sorted(r["entity_id"] for r in fact_parts) == [keep]
    assert [r["entity_id"] for r in arc_parts] == [keep]
    assert arc_owner == keep
    assert [tuple(r) for r in inventory] == [(keep, 5)]
    assert moved_alias == "short"
    # The drop's true name became keep's: it stays a true_name alias. A label keep does not
    # carry any more becomes a former name.
    assert adopted == "true_name"
    assert former == "former_name"
    assert workplace == quai
    assert loc_merge is not None
    assert events == 2
    assert (merge["kept_id"], merge["dropped_id"], merge["reason"]) == (
        keep,
        drop,
        "reveal",
    )
    assert merge["evidence"] == "evidence"
    for snapshot in ("dropped_registry", "dropped_row", "moved_edges"):
        assert merge[snapshot], snapshot
    assert merge["dropped_row"]["true_name"] == "Nahle Irun-Sa"
    assert merge["dropped_registry"]["handle"] == tombstone["handle"]
    assert merge["dropped_registry"]["merged_into"] is None
    assert "inventory.owner_id" not in merge["moved_edges"]  # added up, then deleted
    assert merge["moved_edges"]["arc_participants.entity_id"] == [str(arc_part)]


async def test_merge_entities_refuses_two_types(test_pool, game):
    async with test_pool.acquire() as conn:
        char = await _character(conn, game, true_name="Voss")
        org = await _named(conn, "organizations", game, "Voss")
        with pytest.raises(asyncpg.RaiseError, match="type"):
            await conn.fetchval("SELECT merge_entities($1, $2, 'x', NULL)", char, org)


async def test_handle_is_kept_when_provided(test_pool, game):
    async with test_pool.acquire() as conn:
        char = await _character(conn, game, true_name="Voss")
        await conn.execute("DELETE FROM characters WHERE id = $1", char)
        reg_id = await conn.fetchval(
            "INSERT INTO entity_registry (game_id, entity_type, name, handle)"
            " VALUES ($1, 'location', 'Quai 9', 7) RETURNING id",
            game,
        )
        nxt = await _named(conn, "locations", game, "Quai 10")
        fact = await conn.fetchval(
            "INSERT INTO facts (game_id, cycle, type, description, handle)"
            " VALUES ($1, 1, 'action', 'Un fait', 7) RETURNING id",
            game,
        )
        handles = [
            await conn.fetchval(
                "SELECT handle FROM entity_registry WHERE id = $1", reg_id
            ),
            (await _registry(conn, nxt))["handle"],
            await conn.fetchval("SELECT handle FROM facts WHERE id = $1", fact),
        ]
    assert handles == [7, 8, 7]


async def test_facts_allow_known_and_secret_updates_only(test_pool, game):
    async with test_pool.acquire() as conn:
        fact = await conn.fetchval(
            "SELECT create_fact($1, 1, 'action', 'Un fait')", game
        )
        await conn.execute(
            "UPDATE facts SET known = false, secret = true WHERE id = $1", fact
        )
        row = await conn.fetchrow("SELECT known, secret FROM facts WHERE id = $1", fact)
        with pytest.raises(asyncpg.RaiseError, match="immutable"):
            await conn.execute(
                "UPDATE facts SET description = 'Autre' WHERE id = $1", fact
            )
        with pytest.raises(asyncpg.RaiseError, match="immutable"):
            await conn.execute(
                "UPDATE facts SET known = true, importance = 5 WHERE id = $1", fact
            )
    assert tuple(row) == (False, True)


async def test_undo_reinserts_a_registry_row_at_the_same_id(test_pool, game):
    async with test_pool.acquire() as conn:
        await _character(conn, game, true_name="Premier")
        char = await _character(
            conn, game, true_name="Nahle Irun-Sa", descriptor="La Kethari âgée"
        )
        before_reg = await _registry(conn, char)
        before_aliases = await conn.fetch(
            "SELECT * FROM entity_aliases WHERE entity_id = $1 ORDER BY id", char
        )
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            await conn.execute("DELETE FROM characters WHERE id = $1", char)
        assert await _registry(conn, char) is None
        await conn.fetchval("SELECT world_changes_undo($1::uuid[])", [turn_id])
        after_reg = await _registry(conn, char)
        after_aliases = await conn.fetch(
            "SELECT * FROM entity_aliases WHERE entity_id = $1 ORDER BY id", char
        )
        name = await conn.fetchval("SELECT name FROM characters WHERE id = $1", char)
    assert dict(after_reg) == dict(before_reg)
    assert after_reg["handle"] == 2
    assert [dict(r) for r in after_aliases] == [dict(r) for r in before_aliases]
    assert len(after_aliases) == 2
    assert name == "Nahle Irun-Sa"


async def test_undo_of_a_merge_restores_both_entities(test_pool, game):
    async with test_pool.acquire() as conn:
        keep = await _character(conn, game, descriptor="La Kethari âgée")
        drop = await _character(conn, game, true_name="Nahle Irun-Sa")
        other = await _character(conn, game, true_name="Voss")
        await conn.fetchval(
            "SELECT upsert_relation($1, $2, $3, 'knows'::relation_type, 1)",
            game,
            drop,
            other,
        )
        snapshot_sql = (
            "SELECT to_jsonb(t)::text FROM {} t WHERE game_id = $1 ORDER BY id"
        )
        tables = ("characters", "entity_registry", "entity_aliases", "relations")
        before = {t: await conn.fetch(snapshot_sql.format(t), game) for t in tables}
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            await conn.fetchval(
                "SELECT merge_entities($1, $2, 'reveal', NULL)", keep, drop
            )
        await conn.fetchval("SELECT world_changes_undo($1::uuid[])", [turn_id])
        after = {t: await conn.fetch(snapshot_sql.format(t), game) for t in tables}
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
    assert after == before
    assert merges == 0
