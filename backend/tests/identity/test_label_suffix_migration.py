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


async def _state(conn, entity_id: UUID) -> dict:
    row = await conn.fetchrow(
        "SELECT l.name, to_jsonb(l) ->> 'label_suffix' AS label_suffix, er.name AS label,"
        " display_for_player(l.id) AS shown"
        " FROM locations l JOIN entity_registry er ON er.id = l.id WHERE l.id = $1",
        entity_id,
    )
    kinds = {
        r["alias"]: r["kind"]
        for r in await conn.fetch(
            "SELECT alias, kind FROM entity_aliases WHERE entity_id = $1", entity_id
        )
    }
    return {**dict(row), "aliases": kinds}


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
            # The identity migration's state: the oldest keeps its name, the homonym gets
            # a displayed suffix (identity_legacy_normalise step c, before this migration).
            # (Names unique only by case before it; written here in an order the
            # normalised uniqueness accepts.)
            oldest = await conn.fetchval(
                "INSERT INTO locations (game_id, name) VALUES ($1, 'Terminal')"
                " RETURNING id",
                game,
            )
            clone = await conn.fetchval(
                "INSERT INTO locations (game_id, name) VALUES ($1, 'terminal quai 7')"
                " RETURNING id",
                game,
            )
            await conn.execute(
                "UPDATE locations SET name = name || ' (2)' WHERE id = $1", clone
            )
            await conn.execute(
                "UPDATE locations SET name = 'Terminal Quai 7' WHERE id = $1", oldest
            )
            # A name ending with a number in brackets that no other entity explains.
            lone = await conn.fetchval(
                "INSERT INTO locations (game_id, name) VALUES ($1, 'Secteur (4)')"
                " RETURNING id",
                game,
            )
            before = await _state(conn, clone)
            await conn.execute(up)
            after_up = await _state(conn, clone)
            lone_after_up = await _state(conn, lone)
            await conn.execute(down)
            after_down = await _state(conn, clone)
            await conn.execute(up)
            after_up_again = await _state(conn, clone)
        finally:
            await tx.rollback()
    assert before == {
        "name": "terminal quai 7 (2)",
        "label_suffix": None,
        "label": "terminal quai 7 (2)",
        "shown": "terminal quai 7 (2)",
        "aliases": {"terminal quai 7": "former_name", "terminal quai 7 (2)": "label"},
    }
    assert after_up == {
        "name": "terminal quai 7",
        "label_suffix": "2",
        "label": "terminal quai 7 (2)",
        "shown": "terminal quai 7",
        "aliases": {"terminal quai 7": "label", "terminal quai 7 (2)": "label"},
    }
    assert (
        lone_after_up["name"] == "Secteur (4)" and lone_after_up["label_suffix"] is None
    )
    assert after_down == {**before, "label_suffix": None}
    assert after_up_again == after_up
