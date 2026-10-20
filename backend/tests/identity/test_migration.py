"""The data section of the identity migration, its dry-run report and its backfill (#152,
spec §5.2-5.3), over the legacy fixture of C-19 (tests/characterization/test_c19_legacy.py):
idempotence, the report's sections and verdicts, the name model of legacy characters,
normalised collisions, mentions, derived aliases, exceptions and the startup check."""

from pathlib import Path
from uuid import UUID

import pytest

from tests.characterization.test_c19_legacy import (
    COMMITMENT,
    IDENTITY_MIGRATION,
    OSSEK,
    _journal_a_turn_before_the_migration,
    add_legacy_character,
    identity_invariants,
    legacy_game_id,
    load_legacy_game,
)

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "db"
    / "migrations"
    / f"{IDENTITY_MIGRATION}_entity_identity.sql"
)


def data_section() -> str:
    """Section 3 of the migration: its data transformations, run again by the tests."""
    text = MIGRATION.read_text(encoding="utf-8").split("-- migrate:down", 1)[0]
    section = text.split("\n-- Section 3:", 1)[1].split("\n-- Section 4:", 1)[0]
    return "-- Section 3:" + section


# What the data section and the backfill write, ids of new rows aside (random).
SNAPSHOT = {
    "registry": "SELECT id, entity_type, name, name_norm, handle, merged_into"
    " FROM entity_registry",
    "aliases": "SELECT entity_id, alias, alias_norm, kind, known, secret, source"
    " FROM entity_aliases",
    "mentions": "SELECT message_id, start_pos, end_pos, surface, entity_id, decision"
    " FROM entity_mentions",
    "characters": "SELECT id, name, true_name, descriptor, label_suffix FROM characters",
    "names": "SELECT id, name FROM locations UNION ALL SELECT id, name FROM organizations"
    " UNION ALL SELECT id, name FROM objects",
    "facts": "SELECT id, known, secret, handle FROM facts",
    "edges": "SELECT id, source_id, target_id FROM relations"
    " UNION ALL SELECT id, entity_id, fact_id FROM fact_participants"
    " UNION ALL SELECT id, owner_id, object_id FROM inventory",
    # Synthetic alias rows have random ids: compared without them.
    "journal": "SELECT row_id, old_row::text, new_row::text FROM world_changes"
    " WHERE table_name <> 'entity_aliases'"
    " UNION ALL SELECT NULL, (old_row - 'id' - 'created_at')::text, NULL"
    " FROM world_changes WHERE table_name = 'entity_aliases'",
    "commitments": "SELECT id, related_entities FROM director_commitments",
    "events": "SELECT game_id, kind, payload::text FROM identity_events"
    " WHERE kind IN ('handle_reserved', 'identity_exception')",
    "games": "SELECT id, language FROM games",
}


async def snapshot(conn) -> dict[str, list]:
    return {
        name: sorted(tuple(map(str, r.values())) for r in await conn.fetch(query))
        for name, query in SNAPSHOT.items()
    }


async def _legacy_npcs(conn):
    """Unknown NPCs of the dev database's shapes (fixed ids: snapshots are compared)."""
    await add_legacy_character(
        conn, "Kethari âgée", "La Kethari âgée", "0a51c04c-260c-4faf-836c-ab4757ca680a"
    )
    await add_legacy_character(
        conn,
        "Tesk Vahrun-Oo",
        "Le Kethari au tablier",
        "dbe62e2d-e680-4a75-927f-a73d2b7beb33",
    )
    await add_legacy_character(
        conn, "Cheffe de serre", None, "5884b9bf-f6f9-4c29-9d18-81c1d0595b3e"
    )


async def test_migration_is_idempotent(test_pool):
    """The data section run twice (harness `extra`) leaves what it leaves once, journal of
    a turn played before the migration and director's commitments included; after the
    backfill, the data section and the backfill run again change nothing."""
    from scripts.identity_backfill import run as identity_backfill

    turn_id = "3d9d4c1e-0f6b-4a8e-9b2d-7c5e1a2b3c4d"

    async def hooks_body(conn):
        await _legacy_npcs(conn)
        await _journal_a_turn_before_the_migration(conn, turn_id)

    hooks = {IDENTITY_MIGRATION: hooks_body}
    await load_legacy_game(test_pool, before=hooks)
    async with test_pool.acquire() as conn:
        once = await snapshot(conn)
    game_id, _ = await load_legacy_game(
        test_pool, extra=[(data_section(), "")], before=hooks
    )
    async with test_pool.acquire() as conn:
        twice = await snapshot(conn)
        assert twice == once
        await conn.execute(data_section())
        await identity_backfill(conn, UUID(game_id))
        assert await snapshot(conn) == once
        await identity_invariants(conn, game_id)
        related = await conn.fetchval(
            "SELECT related_entities::text[] FROM director_commitments WHERE id = $1::uuid",
            COMMITMENT,
        )
    assert related == [OSSEK]


async def test_dry_run_report_has_every_section(test_pool):
    """The report, read on the legacy rows before the identity migration, has its eight
    sections and lists the companion the migration registers."""
    from scripts.identity_migration_report import SECTIONS, build_report, render

    texts = []

    async def hook(conn):
        texts.append(render(await build_report(conn)))

    await load_legacy_game(test_pool, before={IDENTITY_MIGRATION: hook})
    text = texts[0]
    assert [title for title in SECTIONS if f"### {title}" in text] == list(SECTIONS)
    assert legacy_game_id() in text
    assert "| companion | Célimène |" in text


async def test_report_classification_matches_the_migration(test_pool):
    """The verdicts the report prints before the migration are what the backfill does."""
    from scripts.identity_migration_report import build_report

    reports = []

    async def hook(conn):
        await _legacy_npcs(conn)
        reports.extend(await build_report(conn))

    game_id, _ = await load_legacy_game(test_pool, before={IDENTITY_MIGRATION: hook})
    async with test_pool.acquire() as conn:
        rows = {
            r["id"]: (r["true_name"], r["descriptor"])
            for r in await conn.fetch(
                "SELECT id, true_name, descriptor FROM characters WHERE game_id = $1::uuid",
                game_id,
            )
        }
    (report,) = reports
    verdicts = {i: (v.true_name, v.descriptor) for i, _, _, v in report.classification}
    assert {v.kind for _, _, _, v in report.classification} == {
        "true_name",
        "descriptor",
    }
    assert verdicts == {i: rows[i] for i in verdicts}


async def test_conventions_a_and_b_are_classified(test_pool):
    """« Kethari âgée » (convention A: name and unknown_name alike) and « Cheffe de serre »
    (B: a descriptor head) are descriptors; « Tesk Vahrun-Oo » is a true name."""
    game_id, _ = await load_legacy_game(
        test_pool, before={IDENTITY_MIGRATION: _legacy_npcs}
    )
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT c.true_name, c.descriptor, display_for_player(c.id) AS shown,"
            " find_entity(c.game_id, 'Kethari âgée', 'character') = c.id AS by_old_name"
            " FROM characters c WHERE c.game_id = $1::uuid ORDER BY c.created_at, c.name",
            game_id,
        )
        await identity_invariants(conn, game_id)
    model = {(r["true_name"], r["descriptor"]): r["shown"] for r in rows}
    assert model[(None, "La Kethari âgée")] == "La Kethari âgée"
    assert model[(None, "Cheffe de serre")] == "Cheffe de serre"
    assert model[("Tesk Vahrun-Oo", "Le Kethari au tablier")] == "Le Kethari au tablier"
    assert sum(bool(r["by_old_name"]) for r in rows) == 1  # still found by its old name


@pytest.mark.parametrize(
    ("name", "unknown_name", "kind", "to_check"),
    [
        ("Kethari âgée", "La Kethari âgée", "descriptor", False),
        ("Cheffe de serre", "La cheffe de serre", "descriptor", False),
        (
            "Un client en bleu de travail",
            "Le type en bleu de travail",
            "descriptor",
            False,
        ),
        ("Tesk Vahrun-Oo", "Le Kethari au tablier", "true_name", False),
        ("Pervenche", None, "true_name", False),
        ("Dagny", "La femme aux cernes", "true_name", False),
        ("kethari", None, "true_name", True),
    ],
)
def test_classify_unknown_character_reads_the_pack(name, unknown_name, kind, to_check):
    from packs.loader import load_lang
    from services.identity.classify import classify_unknown_character
    from services.identity.lexicon import for_game
    from services.identity.normalize import Normalizer

    verdict = classify_unknown_character(
        name, unknown_name, Normalizer(load_lang("fr")), for_game("fr", None)
    )
    assert (verdict.kind, verdict.to_check) == (kind, to_check)
    expected = (
        (name, unknown_name) if kind == "true_name" else (None, unknown_name or name)
    )
    assert (verdict.true_name, verdict.descriptor) == expected


async def test_name_norm_collision_gets_a_suffix_and_is_reported(test_pool):
    """Legacy names unique only by case: the most recent gets the suffix « (2) » (a
    character in its internal label_suffix, never shown; a location in its name), and the
    report says so beforehand."""
    from scripts.identity_migration_report import build_report

    reports = []

    async def hook(conn):
        await add_legacy_character(conn, "OSSEK", None)
        await conn.execute(
            "INSERT INTO locations (game_id, name) VALUES ($1::uuid, 'terminal quai 7')",
            legacy_game_id(),
        )
        reports.extend(await build_report(conn))

    game_id, _ = await load_legacy_game(test_pool, before={IDENTITY_MIGRATION: hook})
    async with test_pool.acquire() as conn:
        clone = await conn.fetchrow(
            "SELECT c.name, c.true_name, c.label_suffix, er.name AS label,"
            " display_for_player(c.id) AS shown"
            " FROM characters c JOIN entity_registry er ON er.id = c.id"
            " WHERE c.game_id = $1::uuid AND c.true_name = 'OSSEK'",
            game_id,
        )
        places = await conn.fetch(
            "SELECT name FROM locations WHERE game_id = $1::uuid"
            " AND lower(name) LIKE 'terminal quai 7%' ORDER BY name",
            game_id,
        )
        await identity_invariants(conn, game_id)
    assert dict(clone) == {
        "name": "OSSEK (2)",
        "true_name": "OSSEK",
        "label_suffix": "2",
        "label": "OSSEK (2)",
        "shown": "Inconnu(e)",
    }
    assert [p["name"] for p in places] == ["Terminal Quai 7", "terminal quai 7 (2)"]
    assert {(c[0], c[2], c[3]) for c in reports[0].collisions} == {
        ("character", "OSSEK", "OSSEK (2)"),
        ("location", "terminal quai 7", "terminal quai 7 (2)"),
    }


async def test_mentions_are_rebuilt_from_narrator_context(test_pool):
    """A narrator_context span whose (name, type) resolves to one entity becomes a
    mention on its id; the others are dropped; narrator_context is kept."""

    async def hook(conn):
        await conn.execute(
            """UPDATE messages SET narrator_context =
                   '[[0, 5, "Ossek", "character"], [6, 13, "Fantôme", "character"],
                     [14, 29, "Escale Méridienne", "location"]]'::jsonb
                WHERE id = (SELECT id FROM messages WHERE game_id = $1::uuid
                             AND role = 'assistant' ORDER BY sequence LIMIT 1)""",
            legacy_game_id(),
        )

    game_id, _ = await load_legacy_game(test_pool, before={IDENTITY_MIGRATION: hook})
    async with test_pool.acquire() as conn:
        mentions = await conn.fetch(
            "SELECT m.start_pos, er.name, m.decision, m.surface = substr(mg.content, 1, 5)"
            " AS first_surface FROM entity_mentions m"
            " JOIN entity_registry er ON er.id = m.entity_id"
            " JOIN messages mg ON mg.id = m.message_id"
            " WHERE m.game_id = $1::uuid ORDER BY m.start_pos",
            game_id,
        )
        kept = await conn.fetchval(
            "SELECT count(*) FROM messages WHERE game_id = $1::uuid"
            " AND narrator_context IS NOT NULL",
            game_id,
        )
    assert [(m["start_pos"], m["name"], m["decision"]) for m in mentions] == [
        (0, "Ossek", "deterministic"),
        (14, "Escale Méridienne", "deterministic"),
    ]
    assert mentions[0]["first_surface"] and kept >= 1


async def test_backfill_adds_short_and_title_aliases_once(test_pool):
    """Derived aliases (« Dr. Yuki Tanaka » → « Yuki Tanaka », « Tanaka », « Yuki »), and a
    second backfill adds nothing."""
    from scripts.identity_backfill import run as identity_backfill

    game_id, _ = await load_legacy_game(test_pool)
    count = (
        "SELECT kind, count(*) FROM entity_aliases WHERE game_id = $1::uuid"
        " AND kind IN ('short', 'title') GROUP BY kind ORDER BY kind"
    )
    async with test_pool.acquire() as conn:
        first = [tuple(r) for r in await conn.fetch(count, game_id)]
        tanaka = {
            r["alias"]: r["kind"]
            for r in await conn.fetch(
                "SELECT al.alias, al.kind FROM entity_aliases al"
                " JOIN characters c ON c.id = al.entity_id WHERE c.name = 'Dr. Yuki Tanaka'"
            )
        }
        counts = await identity_backfill(conn, UUID(game_id))
        assert [tuple(r) for r in await conn.fetch(count, game_id)] == first
    assert {k for k, _ in first} == {"short", "title"}
    assert {
        "Yuki Tanaka": "title",
        "Tanaka": "short",
        "Yuki": "short",
    }.items() <= tanaka.items()
    assert counts["derived_aliases"] == 0


async def _exception_npcs(conn):
    """Unknown NPCs the exceptions correct: a descriptive-looking true name (with a turn
    journaled before the migration), a wrongly kept true name (Tesk, whose correction
    collides with Kethari's label), a mandatory one."""
    await _legacy_npcs(conn)
    await add_legacy_character(conn, "Vieux Marn", "Le vieil homme", MARN)
    await add_legacy_character(conn, "Sela Voor", None, SELA, mandatory=True)
    await conn.execute(
        """WITH t AS (INSERT INTO turns (game_id, status) VALUES ($1::uuid, 'committed')
                      RETURNING id)
           INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row, new_row)
           SELECT t.id, 'characters', $2, 'U', '{"name": "Vieux Marn"}', '{"mood": "x"}'
             FROM t""",
        legacy_game_id(),
        UUID(MARN),
    )


MARN = "1b2c3d4e-5f60-4718-8293-a4b5c6d7e8f9"
SELA = "3d4e5f60-7182-4930-a4b5-c6d7e8f90112"
TESK = "dbe62e2d-e680-4a75-927f-a73d2b7beb33"


async def test_exceptions_follow_the_classification_rules(test_pool, tmp_path):
    """The owner's corrections, applied by the backfill in the same run as the
    classification (I3): a restored true name gets its derived aliases, is not known
    through a stale descriptor alias and is secret for a mandatory unknown character; a
    descriptor that another character holds gets a label suffix; the journal follows;
    each correction is applied once."""
    from scripts.identity_backfill import run as identity_backfill
    from scripts.identity_exceptions import load_exceptions

    path = tmp_path / "exceptions.yaml"
    path.write_text(
        f"{MARN}: {{true_name: Vieux Marn}}\n"
        f"{TESK}: {{descriptor: La kethari âgée}}\n"
        f"{SELA}: {{true_name: Sela Voor-An}}\n",
        encoding="utf-8",
    )
    game_id, _ = await load_legacy_game(
        test_pool, before={IDENTITY_MIGRATION: _exception_npcs}, backfill=False
    )
    async with test_pool.acquire() as conn:
        counts = await identity_backfill(conn, UUID(game_id), load_exceptions(path))
        again = await identity_backfill(conn, UUID(game_id), load_exceptions(path))
        model = {
            str(r["id"]): (r["true_name"], r["descriptor"], r["label_suffix"])
            for r in await conn.fetch(
                "SELECT id, true_name, descriptor, label_suffix FROM characters"
                " WHERE id = ANY($1::uuid[])",
                [UUID(MARN), UUID(TESK), UUID(SELA)],
            )
        }
        aliases = {
            (str(r["entity_id"]), r["alias"]): (r["kind"], r["known"], r["secret"])
            for r in await conn.fetch(
                "SELECT entity_id, alias, kind, known, secret FROM entity_aliases"
                " WHERE entity_id = ANY($1::uuid[])",
                [UUID(MARN), UUID(TESK), UUID(SELA)],
            )
        }
        journal = await conn.fetchval(
            "SELECT old_row::text FROM world_changes WHERE row_id = $1::uuid", MARN
        )
        await identity_invariants(conn, game_id)
    assert (counts["characters_reclassified"], counts["exceptions"]) == (3, 3)
    assert again["exceptions"] == 0
    assert model == {
        MARN: ("Vieux Marn", "Le vieil homme", None),
        TESK: (None, "La kethari âgée", "2"),  # Kethari's label
        SELA: ("Sela Voor-An", None, None),
    }
    # Restored true name: not known through the former descriptor alias, derived forms.
    assert aliases[(MARN, "Vieux Marn")] == ("true_name", False, False)
    assert aliases[(MARN, "Marn")] == ("short", False, False)
    assert aliases[(SELA, "Sela Voor-An")] == ("true_name", False, True)
    assert not any(
        e == TESK and kind == "true_name" for (e, _), (kind, _, _) in aliases.items()
    )
    assert '"true_name": "Vieux Marn"' in journal


async def test_orphans_are_repointed_or_dropped_with_their_journal(test_pool):
    """Step 2 (I1, I2): an orphan registry row named like a live entity's alias gives it
    its edges and its journal rows; one matching nothing loses them, its id leaves the
    commitments; the report says so beforehand; undoing the pre-migration turn commits."""
    from scripts.identity_backfill import run as identity_backfill
    from scripts.identity_migration_report import build_report

    game = legacy_game_id()
    kept, lost, turn = (
        "4e5f6071-8293-4a41-b5c6-d7e8f9011223",
        "5f607182-93a4-4b52-86d7-e8f901122334",
        "60718293-a4b5-4c63-97e8-f90112233445",
    )
    reports = []

    async def hook(conn):
        await add_legacy_character(conn, "Mira Sol", "La gardienne du quai", MIRA)
        await conn.execute(
            f"""DO $$
            DECLARE
                v_game uuid := '{game}';
                v_pc uuid := (SELECT id FROM entity_registry
                               WHERE game_id = v_game AND entity_type = 'protagonist');
                v_fact uuid := (SELECT id FROM facts WHERE game_id = v_game LIMIT 1);
                v_rel jsonb;
            BEGIN
                INSERT INTO entity_registry (id, game_id, entity_type, name) VALUES
                    ('{kept}', v_game, 'character', 'Gardienne du quai'),
                    ('{lost}', v_game, 'character', 'Fantôme');
                INSERT INTO relations (game_id, type, source_id, target_id, start_cycle)
                VALUES (v_game, 'knows', '{kept}', v_pc, 1),
                       (v_game, 'knows', '{lost}', v_pc, 1);
                INSERT INTO fact_participants (fact_id, entity_id, role)
                VALUES (v_fact, '{kept}', 'actor'), (v_fact, '{lost}', 'actor');
                INSERT INTO director_commitments (game_id, kind, text, related_entities)
                VALUES (v_game, 'clock', 'Une horloge', ARRAY['{lost}', '{kept}']::uuid[]);
                INSERT INTO turns (id, game_id, status) VALUES ('{turn}', v_game, 'committed');
                -- The turn deleted a relation of each orphan.
                FOR v_rel IN SELECT jsonb_build_object(
                        'id', gen_random_uuid(), 'game_id', v_game, 'type', 'enemy_of',
                        'source_id', src, 'target_id', v_pc, 'start_cycle', 1,
                        'known_by_protagonist', true) FROM unnest(ARRAY['{kept}', '{lost}']::uuid[]) AS src
                LOOP
                    INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row)
                    VALUES ('{turn}', 'relations', (v_rel ->> 'id')::uuid, 'D', v_rel);
                END LOOP;
            END $$;"""
        )
        reports.extend(await build_report(conn))

    game_id, _ = await load_legacy_game(
        test_pool, before={IDENTITY_MIGRATION: hook}, backfill=False
    )
    async with test_pool.acquire() as conn:
        counts = await identity_backfill(conn, UUID(game_id))
        edges = await conn.fetch(
            "SELECT source_id::text AS id FROM relations WHERE type IN ('knows')"
            " AND game_id = $1::uuid AND source_id::text = ANY($2::text[])",
            game_id,
            [MIRA, kept, lost],
        )
        participants = await conn.fetchval(
            "SELECT count(*) FROM fact_participants WHERE entity_id = $1::uuid", MIRA
        )
        related = await conn.fetchval(
            "SELECT related_entities::text[] FROM director_commitments WHERE kind = 'clock'"
        )
        journal = [
            r["src"]
            for r in await conn.fetch(
                "SELECT old_row ->> 'source_id' AS src FROM world_changes"
                " WHERE turn_id = $1::uuid ORDER BY id",
                UUID(turn),
            )
        ]
        await identity_invariants(conn, game_id)
        async with conn.transaction():
            await conn.fetchval("SELECT world_changes_undo($1::uuid[])", [UUID(turn)])
        restored = await conn.fetchval(
            "SELECT count(*) FROM relations WHERE type = 'enemy_of' AND source_id = $1::uuid",
            MIRA,
        )
    assert (counts["orphans_repointed"], counts["orphans_deleted"]) == (1, 1)
    assert counts["orphan_journal_rows_repointed"] == 1
    assert counts["orphan_commitments_purged"] == 1
    assert [e["id"] for e in edges] == [MIRA] and participants == 1
    assert related == [MIRA]  # the lost orphan purged, the kept one re-pointed
    assert journal == [MIRA] and restored == 1
    orphans = {(o[1], o[2], o[3], o[4]) for o in reports[0].orphans}
    assert orphans == {
        ("Gardienne du quai", 2, 1, "Mira Sol"),
        ("Fantôme", 2, 1, None),
    }


MIRA = "71829304-b5c6-4d74-a8f9-011223344556"


async def test_fact_flags_secret_true_name_and_canonical_alias(test_pool):
    """§5.2 step 4 on legacy rows: a world-generation fact without the protagonist is
    unknown, an extracted one known, a fact of type secret secret; the true name of a
    mandatory unknown NPC is a secret alias; an object's canonical key becomes a label."""

    async def hook(conn):
        await add_legacy_character(conn, "Sela Voor", None, SELA, mandatory=True)
        await conn.execute(
            """INSERT INTO facts (game_id, cycle, type, description, created_at) VALUES
                   ($1::uuid, 1, 'secret', 'Un secret du monde', '2026-01-01'),
                   ($1::uuid, 3, 'action', 'Un fait extrait', now())""",
            legacy_game_id(),
        )
        await conn.execute(
            """UPDATE objects SET canonical_name = 'bagage_principal'
                WHERE game_id = $1::uuid AND name = 'Valise cabine'""",
            legacy_game_id(),
        )

    game_id, _ = await load_legacy_game(test_pool, before={IDENTITY_MIGRATION: hook})
    async with test_pool.acquire() as conn:
        facts = {
            r["description"]: (r["known"], r["secret"])
            for r in await conn.fetch(
                "SELECT description, known, secret FROM facts WHERE game_id = $1::uuid",
                game_id,
            )
        }
        secret = await conn.fetchval(
            "SELECT secret FROM entity_aliases WHERE entity_id = $1::uuid"
            " AND kind = 'true_name'",
            SELA,
        )
        canonical = await conn.fetchrow(
            "SELECT al.kind, al.source,"
            " find_entity(al.game_id, 'bagage principal', 'object') = al.entity_id AS found"
            " FROM entity_aliases al WHERE al.alias = 'bagage_principal'"
        )
    assert facts["Un secret du monde"] == (False, True)
    assert facts["Un fait extrait"] == (True, False)
    assert secret is True
    assert dict(canonical) == {"kind": "label", "source": "migration", "found": True}


async def test_ambiguous_journal_pairs_do_not_abort_the_migration(test_pool):
    """M4: two journaled registry rows pairing with one domain row: one pair is kept, the
    migration goes on."""
    game = legacy_game_id()

    async def hook(conn):
        await conn.execute(
            f"""DO $$
            DECLARE
                v_turn uuid := gen_random_uuid();
                v_row jsonb := jsonb_build_object(
                    'id', '82930415-c6d7-4e85-b9f0-122334455667', 'game_id', '{game}',
                    'name', 'Double', 'known_by_protagonist', false);
            BEGIN
                INSERT INTO turns (id, game_id, status) VALUES (v_turn, '{game}', 'committed');
                INSERT INTO world_changes (turn_id, table_name, row_id, op, old_row) VALUES
                    (v_turn, 'characters', (v_row ->> 'id')::uuid, 'D', v_row),
                    (v_turn, 'entity_registry', gen_random_uuid(), 'D',
                     jsonb_build_object('game_id', '{game}', 'entity_type', 'character',
                                        'name', 'Double')),
                    (v_turn, 'entity_registry', gen_random_uuid(), 'D',
                     jsonb_build_object('game_id', '{game}', 'entity_type', 'character',
                                        'name', 'Double'));
            END $$;"""
        )

    await load_legacy_game(test_pool, before={IDENTITY_MIGRATION: hook})
    async with test_pool.acquire() as conn:
        paired = await conn.fetchval(
            "SELECT count(*) FROM world_changes WHERE table_name = 'entity_registry'"
            " AND row_id = '82930415-c6d7-4e85-b9f0-122334455667'"
        )
    assert paired == 1


def test_to_check_needs_a_script_with_letter_case():
    """M7: a lower-case single word is « à vérifier » only where the pack says names take
    capitals."""
    from packs.loader import load_lang
    from services.identity.classify import classify_unknown_character
    from services.identity.lexicon import for_game
    from services.identity.normalize import Normalizer

    caseless = load_lang("fr").model_copy(update={"proper_name_uses_capitals": False})
    verdict = classify_unknown_character(
        "kethari", None, Normalizer(caseless), for_game("fr", None)
    )
    assert verdict.to_check is False


async def test_startup_refuses_to_serve_before_the_backfill(test_pool):
    """Before the backfill the legacy game has no language and its names no norm: the
    startup check lists them; after it, nothing."""
    from scripts.identity_backfill import run as identity_backfill
    from startup_checks import identity_backfill_errors

    game_id, _ = await load_legacy_game(test_pool, backfill=False)
    async with test_pool.acquire() as conn:
        errors = await identity_backfill_errors(conn)
        assert [e.split(" ", 1)[1] for e in errors] == [
            "entity_registry rows have no name_norm",
            "entity_aliases rows have no alias_norm",
            "active games have no language",
        ]
        await identity_backfill(conn, UUID(game_id))
        assert await identity_backfill_errors(conn) == []
