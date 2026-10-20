"""The data section of the identity migration, its dry-run report and its backfill (#152,
spec §5.2-5.3), over the legacy fixture of C-19 (tests/characterization/test_c19_legacy.py):
idempotence, the report's sections and verdicts, the name model of legacy characters,
normalised collisions, mentions, derived aliases, exceptions and the startup check."""

from pathlib import Path
from uuid import UUID

import pytest

from tests.characterization.test_c19_legacy import (
    IDENTITY_MIGRATION,
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
    "journal": "SELECT id, row_id, old_row::text, new_row::text FROM world_changes",
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
    """The data section run twice (harness `extra`) leaves what it leaves once; after the
    backfill, the data section and the backfill run again change nothing."""
    from scripts.identity_backfill import run as identity_backfill

    hooks = {IDENTITY_MIGRATION: _legacy_npcs}
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


async def test_exceptions_override_the_classification(test_pool, tmp_path):
    """The user's exceptions file, read after the report, wins over the verdict."""
    from scripts.identity_backfill import load_exceptions
    from scripts.identity_backfill import run as identity_backfill

    game_id, _ = await load_legacy_game(
        test_pool, before={IDENTITY_MIGRATION: _legacy_npcs}
    )
    async with test_pool.acquire() as conn:
        ids = {
            r["key"]: r["id"]
            for r in await conn.fetch(
                "SELECT COALESCE(true_name, descriptor) AS key, id FROM characters"
                " WHERE game_id = $1::uuid",
                game_id,
            )
        }
        path = tmp_path / "exceptions.yaml"
        path.write_text(
            f"{ids['Cheffe de serre']}: {{true_name: Oriane}}\n"
            f"{ids['Tesk Vahrun-Oo']}: {{descriptor: Le Kethari au tablier}}\n",
            encoding="utf-8",
        )
        counts = await identity_backfill(conn, UUID(game_id), load_exceptions(path))
        again = await identity_backfill(conn, UUID(game_id), load_exceptions(path))
        rows = {
            r["id"]: (r["true_name"], r["descriptor"])
            for r in await conn.fetch(
                "SELECT id, true_name, descriptor FROM characters WHERE id = ANY($1::uuid[])",
                [ids["Cheffe de serre"], ids["Tesk Vahrun-Oo"]],
            )
        }
        await identity_invariants(conn, game_id)
    assert (counts["exceptions"], again["exceptions"]) == (2, 0)
    assert rows == {
        ids["Cheffe de serre"]: ("Oriane", "Cheffe de serre"),
        ids["Tesk Vahrun-Oo"]: (None, "Le Kethari au tablier"),
    }
    path.write_text("abc: {nickname: x}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="true_name, descriptor"):
        load_exceptions(path)


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
