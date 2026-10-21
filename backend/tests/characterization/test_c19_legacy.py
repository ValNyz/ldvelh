"""C-19: rows written by the pre-refactor code must stay readable and playable.

The fixture is a frozen data-only dump (see make_legacy_fixture.py; header records the
schema version it was taken at). Every migration newer than that version is replayed over
it: their down sections run on the empty schema, the dump is loaded, then their up sections
run over the legacy rows, all in one transaction. So this guards both "legacy-shaped rows
are readable/playable by the current schema and code" and "the newer migrations keep
(or convert) legacy data", e.g. a roll left pending before #32 becomes expired.

Replica mode (see load_legacy_game) means triggers do not run on load: regenerate the
fixture when a migration adds triggers or derived tables, or they will be missing here.

The identity migration (#152) converts the legacy rows with its data section, then
scripts/identity_backfill.py finishes them (language, norms, classification): the loader
runs both, as a deploy does (entrypoint: sync_lang_packs, dbmate up, identity_backfill).
"""

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from services.auth_service import create_token
from tests.characterization import payloads
from tests.characterization.harness import ChatHarness
from tests.conftest import _db_unavailable
from tests.helpers import rollback_last_turn

Migration = tuple[str, str]  # (up SQL, down SQL)
Hook = Callable[[asyncpg.Connection], Awaitable[None]]
IDENTITY_MIGRATION = "20261020000001"
FIXTURE = Path(__file__).parent / "fixtures" / "legacy_game.sql"
MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"
LEGACY_PENDING_ROLL = "7c1d1f0e-5b7a-4c8e-9a51-2f4d3b6e8a10"
BEFORE_JOURNAL = (
    "Impossible de revenir sur un tour joué avant la mise en place du journal "
    "des tours."
)


def legacy_schema_version() -> str:
    """Latest migration version applied when the dump was taken (2nd header line)."""
    return FIXTURE.read_text(encoding="utf-8").splitlines()[1].split()[-1]


def newer_migrations(
    version: str, extra: Sequence[Migration] = ()
) -> list[tuple[str | None, str, str]]:
    """(version, up SQL, down SQL) of every dbmate migration newer than `version`, oldest
    first, then `extra` (version None)."""
    sections = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        number = path.name.split("_", 1)[0]
        if number <= version:
            continue
        text = path.read_text(encoding="utf-8")
        up, down = text.split("-- migrate:down", 1)
        sections.append((number, up.split("-- migrate:up", 1)[1], down))
    return sections + [(None, up, down) for up, down in extra]


def legacy_registry_ids() -> set[str]:
    """The registry ids of the dump: the old trigger's own ids, never the domain ids."""
    return set(
        re.findall(
            r"INSERT INTO public\.entity_registry \(id[^)]*\) VALUES \('([0-9a-f-]{36})'",
            FIXTURE.read_text(encoding="utf-8"),
        )
    )


async def load_legacy_game(
    pool,
    extra: Sequence[Migration] = (),
    *,
    before: Mapping[str, Hook] | None = None,
    backfill: bool = True,
) -> tuple[str, str]:
    """Replace the test DB content with the legacy dump; return (game_id, user_email).

    `extra` is a list of (up, down) migrations appended after the real ones (harness test
    only). `before` maps a migration version to a hook run on the loading connection just
    before that migration's up, in the same transaction: legacy rows the dump lacks (a turn
    journaled before the identity migration), or a read of the pre-migration state (the
    dry-run report). The language packs are synchronised before the ups, as the entrypoint
    does before `dbmate up`; then the identity backfill runs on the game (unless `backfill`
    is False: the state the migration alone leaves).
    """
    from scripts.identity_backfill import run as identity_backfill
    from scripts.sync_lang_packs import ensure_and_sync

    sql = FIXTURE.read_text(encoding="utf-8")
    game_id = sql.splitlines()[0].split()[-1]
    async with pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE games CASCADE; TRUNCATE users CASCADE; TRUNCATE genres CASCADE;"
        )
        # The dump has circular FKs (games <-> locations) and already contains the rows the
        # entity_registry triggers would create: load it as a replica (no FK checks, no
        # triggers), scoped to this transaction. Needs a superuser, as in the test DB.
        # The migrations newer than the dump go down first and up again over its rows.
        migrations = newer_migrations(legacy_schema_version(), extra)
        hooks = dict(before or {})
        async with conn.transaction():
            for _, _, down in reversed(migrations):
                if down.strip():  # asyncpg cannot execute an empty script
                    await conn.execute(down)
            try:
                await conn.execute("SET LOCAL session_replication_role = replica")
            except asyncpg.InsufficientPrivilegeError as exc:
                _db_unavailable(
                    f"C-19 needs a superuser role to load the legacy dump: {exc}"
                )
            await conn.execute(sql)
            await conn.execute("SET LOCAL session_replication_role = origin")
            await ensure_and_sync(conn)
            for version, up, _ in migrations:
                if version in hooks:
                    await hooks.pop(version)(conn)
                await conn.execute(up)
            assert not hooks, f"no migration {sorted(hooks)} to hook"
        if backfill:
            await identity_backfill(conn, UUID(game_id))
        email = await conn.fetchval(
            "SELECT u.email FROM users u JOIN games g ON g.user_id = u.id WHERE g.id = $1::uuid",
            game_id,
        )
    return game_id, email


async def legacy_invariants(conn, game_id: str) -> None:
    """Rows a migration must not damage: the legacy game keeps its messages, protagonist and rolls."""
    messages = await conn.fetch(
        "SELECT cycle FROM messages WHERE game_id = $1::uuid", game_id
    )
    assert len(messages) >= 4, f"legacy messages lost: {len(messages)}"
    assert all(m["cycle"] is not None for m in messages), (
        "a legacy message lost its cycle"
    )
    assert (
        await conn.fetchval(
            "SELECT COUNT(*) FROM protagonists WHERE game_id = $1::uuid", game_id
        )
        == 1
    )
    assert (
        await conn.fetchval(
            "SELECT COUNT(*) FROM mechanic_rolls WHERE game_id = $1::uuid", game_id
        )
        == 2
    )
    assert (
        await conn.fetchval(
            "SELECT current_cycle FROM games WHERE id = $1::uuid", game_id
        )
        >= 1
    )
    await identity_invariants(conn, game_id)


# Each query counts what breaks an identity invariant (#152, spec §5.3): all must be 0.
IDENTITY_BREACHES = {
    "domain row without registry row at its id": """
        SELECT count(*) FROM (
            SELECT id, game_id, 'character' AS t FROM characters
            UNION ALL SELECT id, game_id, 'location' FROM locations
            UNION ALL SELECT id, game_id, 'organization' FROM organizations
            UNION ALL SELECT id, game_id, 'object' FROM objects
            UNION ALL SELECT id, game_id, 'protagonist' FROM protagonists
            UNION ALL SELECT id, game_id, 'companion' FROM companions) AS dom
         WHERE dom.game_id = $1::uuid AND NOT EXISTS (
            SELECT 1 FROM entity_registry er WHERE er.id = dom.id AND er.entity_type = dom.t)""",
    "orphan registry row": """
        SELECT count(*) FROM entity_registry er WHERE er.game_id = $1::uuid
           AND er.merged_into IS NULL AND identity_domain_row(er.entity_type, er.id) IS NULL""",
    "registry row without name_norm": """
        SELECT count(*) FROM entity_registry WHERE game_id = $1::uuid AND name_norm IS NULL""",
    "alias without alias_norm": """
        SELECT count(*) FROM entity_aliases WHERE game_id = $1::uuid AND alias_norm IS NULL""",
    "game without language": """
        SELECT count(*) FROM games WHERE id = $1::uuid AND language IS NULL""",
    "entity without an alias of its name_norm": """
        SELECT count(*) FROM entity_registry er WHERE er.game_id = $1::uuid
           AND er.merged_into IS NULL AND NOT EXISTS (
               SELECT 1 FROM entity_aliases al
                WHERE al.entity_id = er.id AND al.alias_norm = er.name_norm)""",
    "character whose names disagree": """
        SELECT count(*) FROM characters ch JOIN entity_registry er ON er.id = ch.id
         WHERE ch.game_id = $1::uuid
           AND (ch.true_name IS NULL AND ch.descriptor IS NULL
                OR ch.name <> COALESCE(ch.true_name, ch.descriptor)
                              || COALESCE(' (' || ch.label_suffix || ')', '')
                OR er.name <> ch.name)""",
    # display_for_player would show the hidden true name (I1).
    "unknown character whose descriptor is its true name": """
        SELECT count(*) FROM characters ch
         WHERE ch.game_id = $1::uuid AND NOT COALESCE(ch.known_by_protagonist, false)
           AND ch.true_name IS NOT NULL
           AND ldvelh_norm_for_game(ch.game_id, ch.descriptor)
               = ldvelh_norm_for_game(ch.game_id, ch.true_name)""",
    "stale norm": """
        SELECT (SELECT count(*) FROM entity_registry WHERE game_id = $1::uuid
                   AND name_norm <> ldvelh_norm_for_game(game_id, name))
             + (SELECT count(*) FROM entity_aliases WHERE game_id = $1::uuid
                   AND alias_norm <> ldvelh_norm_for_game(game_id, alias))""",
    "mention of a missing entity": """
        SELECT count(*) FROM entity_mentions m WHERE m.game_id = $1::uuid
           AND NOT EXISTS (SELECT 1 FROM entity_registry er WHERE er.id = m.entity_id)""",
    "unregistered companion": """
        SELECT count(*) FROM companions cm WHERE cm.game_id = $1::uuid AND NOT EXISTS (
            SELECT 1 FROM entity_registry er WHERE er.id = cm.id AND er.entity_type = 'companion')""",
}


async def identity_invariants(conn, game_id: str) -> None:
    """The legacy game in the identity model (#152): every domain row has its registry row
    at its own id, no orphan, every name normalised with the game's language, an alias of
    each entity's name, consistent character names, mentions on live ids, the companion
    registered, and no id of the old registry left anywhere (edges, journal)."""
    breaches = {
        what: n
        for what, query in IDENTITY_BREACHES.items()
        if (n := await conn.fetchval(query, game_id))
    }
    assert breaches == {}, breaches
    old_ids = legacy_registry_ids()
    left = await conn.fetchval(
        """SELECT count(*) FROM (
               SELECT id::text FROM entity_registry
               UNION ALL SELECT source_id::text FROM relations
               UNION ALL SELECT target_id::text FROM relations
               UNION ALL SELECT entity_id::text FROM fact_participants
               UNION ALL SELECT entity_id::text FROM arc_participants
               UNION ALL SELECT entity_id::text FROM chronology_participants
               UNION ALL SELECT entity_id::text FROM event_participants
               UNION ALL SELECT owner_id::text FROM inventory
               UNION ALL SELECT owner_id::text FROM narrative_arcs
               UNION ALL SELECT unnest(related_entities)::text
                           FROM director_commitments) AS ref (id)
            WHERE ref.id = ANY($1::text[])""",
        list(old_ids),
    )
    assert left == 0, f"{left} references to old registry ids"
    journal = await conn.fetchval(
        "SELECT string_agg(row_id::text || coalesce(old_row::text, '') || coalesce(new_row::text, ''), ' ')"
        " FROM world_changes"
    )
    assert not any(old in (journal or "") for old in old_ids), (
        "old id left in the journal"
    )


@pytest_asyncio.fixture
async def legacy_game(test_pool, scripted_llm):
    return await load_legacy_game(test_pool)


@pytest_asyncio.fixture
async def legacy_token(test_pool, legacy_game):
    _, email = legacy_game
    async with test_pool.acquire() as conn:
        user_id = await conn.fetchval("SELECT id FROM users WHERE email = $1", email)
    return create_token(user_id, email)


async def test_c19_legacy_game_loads_and_plays(
    client, test_pool, legacy_game, legacy_token, scripted_llm
):
    """A legacy-shaped game loads with its Fate stats and accepts a new turn (see module docstring for scope)."""
    game_id, _ = legacy_game
    h = ChatHarness(client, test_pool, legacy_token, scripted_llm)
    async with test_pool.acquire() as conn:
        await legacy_invariants(conn, game_id)

    r = await client.get(f"/api/games/{game_id}", headers=h.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    before = len(body["messages"])
    assert before >= 4
    stats = body["state"]["player"]["engine_stats"]
    assert stats["fate_points"] >= 1 and stats["refresh"] >= 1, stats
    assert "stress_physical" in stats and "consequences" in stats
    # The legacy jsonb aspect list became typed aspects_fate rows (#93 backfill: with two
    # aspects or more, first = high concept, second = trouble) and reaches the sheet.
    assert body["state"]["player"]["sheet"]["aspects"] == [
        {"type": "high_concept", "name": "Pilote déchu en quête de rédemption"},
        {"type": "trouble", "name": "Je dois de l'argent à tout le monde"},
        {"type": "other", "name": "Mon vieux cargo est ma maison"},
    ]
    async with test_pool.acquire() as conn:
        rolls = await conn.fetchval(
            "SELECT COUNT(*) FROM mechanic_rolls WHERE game_id = $1::uuid", game_id
        )
    assert rolls == 2
    assert body["state"]["pending_roll"] is None

    events = await h.chat(game_id, "Je reprends ma partie.")
    await h.drain()
    assert "done" in h.summarize(events)

    r = await client.get(f"/api/games/{game_id}", headers=h.headers)
    assert len(r.json()["messages"]) > before


async def test_c19_harness_catches_a_data_breaking_migration(test_pool, scripted_llm):
    """Meta-test: a migration that damages legacy rows must make the invariants fail."""
    breaking = ("UPDATE messages SET cycle = NULL WHERE role = 'assistant';", "")
    game_id, _ = await load_legacy_game(test_pool, extra=[breaking])
    async with test_pool.acquire() as conn:
        with pytest.raises(AssertionError, match="lost its cycle"):
            await legacy_invariants(conn, game_id)


async def test_legacy_pending_rows_are_expired(test_pool, legacy_game):
    """#32: a roll left without a message by the old code is expired, the resolved one kept."""
    game_id, _ = legacy_game
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, status, message_id IS NULL AS orphan FROM mechanic_rolls"
            " WHERE game_id = $1::uuid ORDER BY created_at",
            game_id,
        )
    assert [(r["status"], r["orphan"]) for r in rows] == [
        ("resolved", False),
        ("expired", True),
    ]
    assert rows[1]["id"] == LEGACY_PENDING_ROLL


async def test_legacy_users_start_at_token_version_zero(client, test_pool, legacy_game):
    """#83: users saved before token_version get version 0 and can sign in again."""
    _, email = legacy_game
    async with test_pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT token_version FROM users WHERE email = $1", email
            )
            == 0
        )
    login = await client.post(
        "/api/auth/login", json={"identifier": email, "password": "testpassword"}
    )
    assert login.status_code == 200, login.text
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    assert me.status_code == 200


async def test_legacy_arrival_facts_get_protagonist_keys(test_pool, legacy_game):
    """#28: the migration renames the system semantic keys valentin:* to protagonist:*."""
    from uuid import UUID

    from kg.reader import KnowledgeGraphReader

    game_id, _ = legacy_game
    async with test_pool.acquire() as conn:
        keys = await conn.fetch(
            "SELECT semantic_key FROM facts WHERE game_id = $1::uuid AND cycle = 1"
            " ORDER BY semantic_key",
            game_id,
        )
        arrival = await KnowledgeGraphReader(
            test_pool, UUID(game_id)
        ).get_arrival_event(conn)
    assert arrival is not None
    assert [k["semantic_key"] for k in keys] == [
        "protagonist:arrival:incident",
        "protagonist:arrival:mood",
        "protagonist:arrival:need",
        "protagonist:arrival:sensory",
        "protagonist:arrival:station",
    ]
    assert arrival["arrival_description"].startswith(
        "Arrivée sur la station via navette cargo"
    )
    assert arrival["initial_mood"] == "fatigué, nauséeux, décalé"
    assert arrival["immediate_need"] == "Trouver l'appartement et dormir"
    assert arrival["incident"] == "Systèmes bagages en panne, attente indéterminée"


async def test_legacy_game_new_turn_rolls_back_through_the_journal(
    client, test_pool, legacy_game, legacy_token, scripted_llm
):
    """#22: a turn played on a legacy game is journaled and undone like any other."""
    game_id, _ = legacy_game
    h = ChatHarness(client, test_pool, legacy_token, scripted_llm)
    # llm_calls: paid calls are kept (#106); identity_events: telemetry, never journaled
    # (the turn's reveal event outlives its rollback, Documentation §7).
    ignored = {"turns", "llm_calls", "identity_events"}
    before = {
        k: v for k, v in (await h.db_summary(game_id)).items() if k not in ignored
    }
    scripted_llm._responses["identity"] = payloads.IDENTITY_NEW_CHARACTER
    scripted_llm._responses["narration"] = payloads.NARRATION_NEW_CHARACTER
    scripted_llm._responses["extract:extract_characters"] = (
        payloads.extract_characters_new
    )
    await h.chat(game_id, "Je reprends ma partie.")
    await h.drain()
    async with test_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT 1 FROM characters WHERE game_id = $1::uuid AND name = $2",
            game_id,
            payloads.NEW_CHARACTER_NAME,
        )
        journaled = await conn.fetchval(
            """SELECT count(*) FROM world_changes w JOIN turns t ON t.id = w.turn_id
               WHERE t.game_id = $1::uuid""",
            game_id,
        )
    assert journaled > 0  # the turn wrote through the journal

    await rollback_last_turn(h, game_id)
    after = {k: v for k, v in (await h.db_summary(game_id)).items() if k not in ignored}
    assert after == before
    async with test_pool.acquire() as conn:
        assert not await conn.fetchval(
            "SELECT 1 FROM characters WHERE game_id = $1::uuid AND name = $2",
            game_id,
            payloads.NEW_CHARACTER_NAME,
        )


async def test_legacy_turn_rollback_is_refused_with_a_clear_message(
    client, test_pool, legacy_game, legacy_token
):
    """#22: a message saved before the journal cannot be rolled back (400, nothing deleted)."""
    game_id, _ = legacy_game
    async with test_pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT id FROM messages WHERE game_id = $1::uuid ORDER BY sequence DESC LIMIT 1",
            game_id,
        )
        count = "SELECT count(*) FROM messages WHERE game_id = $1::uuid"
        before = await conn.fetchval(count, game_id)
    r = await client.post(
        f"/api/games/{game_id}/rollback",
        json={"messageId": str(last)},
        headers={"Authorization": f"Bearer {legacy_token}"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == BEFORE_JOURNAL
    async with test_pool.acquire() as conn:
        assert await conn.fetchval(count, game_id) == before


def legacy_game_id() -> str:
    return FIXTURE.read_text(encoding="utf-8").splitlines()[0].split()[-1]


OSSEK = "7b474354-16c0-4f1a-a77a-1cce67c116a5"  # domain id
OSSEK_OLD_REGISTRY = "bc1cfcf3-f620-487d-8516-b26e0a992de9"
PROTAGONIST_OLD_REGISTRY = "87685f6f-4d8f-40db-b738-addd7793eb12"
LIVES_AT_RELATION = "87880d42-83b1-4076-a964-936971f9ee0c"
COMMITMENT = "5c0aa7e1-3f39-4c55-9d7e-6a1b8c2d4e01"


async def add_legacy_character(
    conn,
    name: str,
    unknown_name: str | None,
    character_id: str | None = None,
    *,
    mandatory: bool = False,
) -> None:
    """A character written by the pre-identity code: the old trigger registers it under
    its own id (hook run before the identity migration)."""
    await conn.execute(
        """INSERT INTO characters
                  (id, game_id, name, unknown_name, known_by_protagonist, is_mandatory)
           VALUES (COALESCE($4::uuid, gen_random_uuid()), $1::uuid, $2, $3, false, $5)""",
        legacy_game_id(),
        name,
        unknown_name,
        character_id,
        mandatory,
    )


async def test_c19_legacy_reveal_by_descriptor_works_after_migration(test_pool):
    """Review Focus 5: a legacy unknown NPC stored under a description is classified as a
    descriptor by the migration; a reveal naming it with an article finds it, sets its
    true name, marks it known and renames its registry row by id."""
    from services.identity.service import IdentityService
    from domain.identity import EntityRef

    async def hook(conn):
        await add_legacy_character(conn, "Kethari âgée", "La Kethari âgée")

    game_id, _ = await load_legacy_game(test_pool, before={IDENTITY_MIGRATION: hook})
    async with test_pool.acquire() as conn:
        await legacy_invariants(conn, game_id)
        kethari = await conn.fetchrow(
            "SELECT id, true_name, descriptor FROM characters"
            " WHERE game_id = $1::uuid AND descriptor = 'La Kethari âgée'",
            game_id,
        )
        assert kethari["true_name"] is None
        identity = await IdentityService.for_game(conn, UUID(game_id))
        revealed = await identity.reveal(
            conn,
            EntityRef("La Kethari âgée", "character"),
            "Nom Révélé",
            turn_id=None,
            source="reveal", disclosed=frozenset(),
        )
        assert revealed.kind == "applied"
        row = await conn.fetchrow(
            "SELECT c.known_by_protagonist, c.true_name, er.name AS label,"
            " display_for_player(c.id) AS shown"
            " FROM characters c JOIN entity_registry er ON er.id = c.id WHERE c.id = $1",
            kethari["id"],
        )
        await identity_invariants(conn, game_id)
    assert dict(row) == {
        "known_by_protagonist": True,
        "true_name": "Nom Révélé",
        "label": "Nom Révélé",
        "shown": "Nom Révélé",
    }


async def _journal_a_turn_before_the_migration(conn, turn_id: str) -> None:
    """A turn played between P5a and the identity migration (#152, I7): it deleted a
    character (registry row under the old trigger's id) and a fact written before the
    first message (world generation, no protagonist: unknown by the rule), renamed Ossek,
    and touched a relation and a director's commitment citing old registry ids."""
    await conn.execute(
        f"""DO $$
        DECLARE
            v_game uuid := '{legacy_game_id()}';
            v_char jsonb;
            v_reg jsonb;
            v_fact jsonb;
        BEGIN
            INSERT INTO turns (id, game_id, status, committed_at)
            VALUES ('{turn_id}', v_game, 'committed', now());
            INSERT INTO characters (id, game_id, name, unknown_name, known_by_protagonist,
                                    created_at, updated_at)
            VALUES ('6f1e2d3c-4b5a-4968-8776-655443322110', v_game, 'Ferrin Dask',
                    'Le garde du sas', false, '2026-01-02', '2026-01-02');
            SELECT to_jsonb(ch) INTO v_char FROM characters ch
             WHERE ch.game_id = v_game AND ch.name = 'Ferrin Dask';
            SELECT to_jsonb(er) INTO v_reg FROM entity_registry er
             WHERE er.game_id = v_game AND er.name = 'Ferrin Dask';
            DELETE FROM characters WHERE id = (v_char ->> 'id')::uuid;
            DELETE FROM entity_registry WHERE id = (v_reg ->> 'id')::uuid;
            INSERT INTO facts (id, game_id, cycle, type, description, created_at)
            VALUES ('7a2b3c4d-5e6f-4a1b-8c2d-9e0f1a2b3c4d', v_game, 1, 'action',
                    'Un fait que le tour a effacé', '2026-01-01');
            INSERT INTO director_commitments (id, game_id, kind, text, related_entities)
            VALUES ('{COMMITMENT}', v_game, 'secret', 'Un secret',
                    ARRAY['{OSSEK_OLD_REGISTRY}']::uuid[]);
            SELECT to_jsonb(ft) INTO v_fact FROM facts ft
             WHERE ft.game_id = v_game AND ft.description = 'Un fait que le tour a effacé';
            DELETE FROM facts WHERE id = (v_fact ->> 'id')::uuid;
            INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row, new_row)
            VALUES ('{turn_id}', 'characters', (v_char ->> 'id')::uuid, 'D', v_char, NULL),
                   ('{turn_id}', 'entity_registry', (v_reg ->> 'id')::uuid, 'D', v_reg, NULL),
                   ('{turn_id}', 'facts', (v_fact ->> 'id')::uuid, 'D', v_fact, NULL),
                   ('{turn_id}', 'entity_registry', '{OSSEK_OLD_REGISTRY}', 'U',
                    '{{"name": "Ossek Varn"}}', '{{"name": "Ossek"}}'),
                   ('{turn_id}', 'characters', '{OSSEK}', 'U',
                    '{{"name": "Ossek Varn"}}', '{{"name": "Ossek"}}'),
                   ('{turn_id}', 'relations', '{LIVES_AT_RELATION}', 'U',
                    '{{"source_id": "{PROTAGONIST_OLD_REGISTRY}"}}',
                    '{{"source_id": "{PROTAGONIST_OLD_REGISTRY}"}}'),
                   ('{turn_id}', 'director_commitments', '{COMMITMENT}', 'U',
                    '{{"related_entities": ["{OSSEK_OLD_REGISTRY}"]}}',
                    '{{"related_entities": []}}');
        END $$;"""
    )


async def test_c19_world_changes_ids_are_rewritten(test_pool):
    """I7: the journal of a turn played before the identity migration is rewritten to the
    new ids and column set, so that undoing it after the deploy is exact: a deleted entity
    comes back at its domain id with its handle, norm and aliases, a deleted fact with a
    reserved handle and the flags of the rule, the commitment with the new id."""
    import json
    import uuid

    turn_id = str(uuid.uuid4())

    async def hook(conn):
        await _journal_a_turn_before_the_migration(conn, turn_id)

    game_id, _ = await load_legacy_game(test_pool, before={IDENTITY_MIGRATION: hook})
    async with test_pool.acquire() as conn:
        await legacy_invariants(conn, game_id)  # no old registry id left in the journal
        protagonist = await conn.fetchval(
            "SELECT id::text FROM protagonists WHERE game_id = $1::uuid", game_id
        )
        rows = {
            (r["table_name"], r["op"]): (
                str(r["row_id"]),
                json.loads(r["old"] or "null"),
            )
            for r in await conn.fetch(
                "SELECT table_name, op, row_id, old_row::text AS old FROM world_changes"
                " WHERE turn_id = $1::uuid AND table_name <> 'entity_aliases'",
                turn_id,
            )
        }
        aliases = {
            (r["alias"], r["kind"], r["known"], r["norm"])
            for r in await conn.fetch(
                "SELECT old_row ->> 'alias' AS alias, old_row ->> 'kind' AS kind,"
                " (old_row ->> 'known')::boolean AS known,"
                " old_row ->> 'alias_norm' AS norm FROM world_changes"
                " WHERE turn_id = $1::uuid AND table_name = 'entity_aliases'",
                turn_id,
            )
        }
        ferrin_id, ferrin = rows[("characters", "D")]
        registry_id, registry = rows[("entity_registry", "D")]
        assert registry_id == ferrin_id == registry["id"]  # paired by type and name
        assert "unknown_name" not in ferrin
        assert (ferrin["true_name"], ferrin["descriptor"]) == (
            "Ferrin Dask",
            "Le garde du sas",
        )
        assert registry["name_norm"] == "ferrin dask" and registry["handle"] > 0
        assert aliases == {  # the deleted Ferrin's names, Ossek's former name
            ("Ferrin Dask", "true_name", False, "ferrin dask"),
            ("Le garde du sas", "descriptor", True, "garde du sas"),
            ("Ossek Varn", "true_name", False, "ossek varn"),
        }
        fact = rows[("facts", "D")][1]
        assert (fact["known"], fact["secret"]) == (False, False)
        assert rows[("entity_registry", "U")] == (
            OSSEK,
            {"name": "Ossek Varn", "name_norm": "ossek varn"},
        )
        assert rows[("characters", "U")][1] == {
            "name": "Ossek Varn",
            "true_name": "Ossek Varn",
        }
        assert rows[("relations", "U")][1] == {"source_id": protagonist}
        assert rows[("director_commitments", "U")][1] == {"related_entities": [OSSEK]}
        reserved = {
            (r["tbl"], r["handle"])
            for r in await conn.fetch(
                "SELECT payload ->> 'table' AS tbl, (payload ->> 'handle')::int AS handle"
                " FROM identity_events WHERE game_id = $1::uuid AND kind = 'handle_reserved'",
                game_id,
            )
        }
        assert reserved == {
            ("entity_registry", registry["handle"]),
            ("facts", fact["handle"]),
        }

        # A row created outside a turn after the deploy never takes a reserved handle.
        await conn.execute(
            "INSERT INTO locations (game_id, name) VALUES ($1::uuid, 'Sas neuf')",
            game_id,
        )
        new_handle = await conn.fetchval(
            "SELECT er.handle FROM entity_registry er JOIN locations l ON l.id = er.id"
            " WHERE l.name = 'Sas neuf'"
        )
        assert new_handle > registry["handle"]

        async with conn.transaction():
            await conn.fetchval(
                "SELECT world_changes_undo($1::uuid[])", [UUID(turn_id)]
            )
        ossek = await conn.fetchrow(
            "SELECT ch.true_name, er.name, er.name_norm FROM characters ch"
            " JOIN entity_registry er ON er.id = ch.id WHERE ch.id = $1::uuid",
            OSSEK,
        )
        back = await conn.fetchrow(
            "SELECT ch.true_name, ch.descriptor, er.name, er.name_norm, er.handle,"
            " find_entity(ch.game_id, 'le garde du sas', 'character') = ch.id AS found"
            " FROM characters ch JOIN entity_registry er ON er.id = ch.id"
            " WHERE ch.id = $1::uuid",
            ferrin_id,
        )
        fact_back = await conn.fetchrow(
            "SELECT handle, known FROM facts WHERE id = $1::uuid",
            rows[("facts", "D")][0],
        )
        await identity_invariants(
            conn, game_id
        )  # aliases of the restored entity included
    assert dict(ossek) == {
        "true_name": "Ossek Varn",
        "name": "Ossek Varn",
        "name_norm": "ossek varn",
    }
    assert dict(back) == {
        "true_name": "Ferrin Dask",
        "descriptor": "Le garde du sas",
        "name": "Ferrin Dask",
        "name_norm": "ferrin dask",
        "handle": registry["handle"],
        "found": True,
    }
    assert dict(fact_back) == {"handle": fact["handle"], "known": False}
