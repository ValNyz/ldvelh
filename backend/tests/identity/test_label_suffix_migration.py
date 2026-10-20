"""The internal label suffix of every entity type (#153, ruling R14): the migration turns the
displayed homonym suffix « Nom (2) » the identity migration gave a location, an
organization or an object into the internal one, and its down gives it back."""

from pathlib import Path
from uuid import UUID

import pytest

pytestmark = pytest.mark.integration

MIGRATION = next(
    (Path(__file__).resolve().parents[3] / "db" / "migrations").glob(
        "*_identity_label_suffix.sql"
    )
)


def _sections() -> tuple[str, str]:
    up, down = MIGRATION.read_text(encoding="utf-8").split("-- migrate:down", 1)
    return up.split("-- migrate:up", 1)[1], down


async def _state(conn, table: str, entity_id: UUID) -> dict:
    row = await conn.fetchrow(
        f"SELECT d.name, to_jsonb(d) ->> 'label_suffix' AS label_suffix,"
        f" er.name AS label, display_for_player(d.id) AS shown"
        f" FROM {table} d JOIN entity_registry er ON er.id = d.id WHERE d.id = $1",
        entity_id,
    )
    aliases = {
        r["alias"]: (r["kind"], r["known"])
        for r in await conn.fetch(
            "SELECT alias, kind, known FROM entity_aliases WHERE entity_id = $1",
            entity_id,
        )
    }
    return {**dict(row), "aliases": aliases}


async def _legacy_homonym(
    conn, table: str, game: UUID, oldest: str, clone: str
) -> UUID:
    """The identity migration's state (identity_legacy_normalise step c, before this
    migration): the oldest keeps its name, the homonym gets a displayed suffix, its bare
    name demoted to a former name. Names unique only by case before it are written here in
    an order the normalised uniqueness accepts."""
    first = await conn.fetchval(
        f"INSERT INTO {table} (game_id, name) VALUES ($1, 'Provisoire') RETURNING id",
        game,
    )
    second = await conn.fetchval(
        f"INSERT INTO {table} (game_id, name) VALUES ($1, $2) RETURNING id", game, clone
    )
    await conn.execute(
        f"UPDATE {table} SET name = name || ' (2)' WHERE id = $1", second
    )
    await conn.execute(f"UPDATE {table} SET name = $2 WHERE id = $1", first, oldest)
    return second


async def test_displayed_suffixes_become_internal_and_back(test_pool, test_user):
    up, down = _sections()
    async with test_pool.acquire() as conn:
        game = await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
            test_user["id"],
        )
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(down)
            clone = await _legacy_homonym(
                conn, "locations", game, "Terminal Quai 7", "terminal quai 7"
            )
            guild = await _legacy_homonym(
                conn, "organizations", game, "Guilde des Pilotes", "guilde des pilotes"
            )
            # Names ending with a number in brackets that step c did not write: no other
            # entity holds the bare form, or one does but the name was never renamed (no
            # former-name alias of the bare form).
            lone = await conn.fetchval(
                "INSERT INTO locations (game_id, name) VALUES ($1, 'Secteur (4)')"
                " RETURNING id",
                game,
            )
            await conn.execute(
                "INSERT INTO locations (game_id, name) VALUES ($1, 'Pod')", game
            )
            pod = await conn.fetchval(
                "INSERT INTO locations (game_id, name) VALUES ($1, 'Pod (2)') RETURNING id",
                game,
            )
            before = await _state(conn, "locations", clone)
            await conn.execute(up)
            after_up = await _state(conn, "locations", clone)
            guild_after_up = await _state(conn, "organizations", guild)
            untouched = [await _state(conn, "locations", i) for i in (lone, pod)]
            await conn.execute(down)
            after_down = await _state(conn, "locations", clone)
            await conn.execute(up)
            after_up_again = await _state(conn, "locations", clone)
        finally:
            await tx.rollback()
    assert before == {
        "name": "terminal quai 7 (2)",
        "label_suffix": None,
        "label": "terminal quai 7 (2)",
        "shown": "terminal quai 7 (2)",
        "aliases": {
            "terminal quai 7": ("former_name", True),
            "terminal quai 7 (2)": ("label", True),
        },
    }
    # The suffixed label is internal: never known (M7).
    assert after_up == {
        "name": "terminal quai 7",
        "label_suffix": "2",
        "label": "terminal quai 7 (2)",
        "shown": "terminal quai 7",
        "aliases": {
            "terminal quai 7": ("label", True),
            "terminal quai 7 (2)": ("label", False),
        },
    }
    assert {
        k: guild_after_up[k] for k in ("name", "label_suffix", "label", "shown")
    } == {
        "name": "guilde des pilotes",
        "label_suffix": "2",
        "label": "guilde des pilotes (2)",
        "shown": "guilde des pilotes",
    }
    assert [(s["name"], s["label_suffix"]) for s in untouched] == [
        ("Secteur (4)", None),
        ("Pod (2)", None),
    ]
    assert after_down == before
    assert after_up_again == after_up
