"""The operator merge script (#153): a refusal on stdin changes nothing, --yes merges."""

import builtins
from uuid import UUID

import pytest

from scripts import merge_entities

pytestmark = pytest.mark.integration


def _url() -> str:
    from tests.conftest import TEST_DB_URL

    return TEST_DB_URL


async def _setup(conn, user_id) -> tuple[UUID, UUID, UUID, UUID]:
    game = await conn.fetchval(
        "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id", user_id
    )
    keep = await conn.fetchval(
        "INSERT INTO characters (game_id, true_name) VALUES ($1, 'Oriane Mbeki-Larsson')"
        " RETURNING id",
        game,
    )
    drop = await conn.fetchval(
        "INSERT INTO characters (game_id, descriptor) VALUES ($1, 'La cheffe de serre')"
        " RETURNING id",
        game,
    )
    other = await conn.fetchval(
        "INSERT INTO characters (game_id, true_name) VALUES ($1, 'Tesk Vahrun') RETURNING id",
        game,
    )
    await conn.execute(
        """INSERT INTO relations (game_id, type, source_id, target_id, start_cycle)
           VALUES ($1, 'knows', $2, $3, 1)""",
        game,
        drop,
        other,
    )
    return game, keep, drop, other


def _args(game, keep, drop, *extra) -> list[str]:
    return [
        "--database-url",
        _url(),
        "--game",
        str(game),
        "--keep",
        str(keep),
        "--drop",
        str(drop),
        "--reason",
        "same person",
        *extra,
    ]


async def _state(conn, game, drop):
    return (
        await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        ),
        await conn.fetchval(
            "SELECT merged_into FROM entity_registry WHERE id = $1", drop
        ),
    )


async def test_merge_script_refuses_without_confirmation_and_merges_with_yes(
    test_pool, test_user, monkeypatch, capsys
):
    async with test_pool.acquire() as conn:
        game, keep, drop, other = await _setup(conn, test_user["id"])
        handle = await conn.fetchval(
            "SELECT handle FROM entity_registry WHERE id = $1", drop
        )

    monkeypatch.setattr(builtins, "input", lambda prompt="": "n")
    args = merge_entities.build_parser().parse_args(_args(game, keep, f"E{handle}"))
    assert await merge_entities._main(args) == 1
    shown = capsys.readouterr().out
    assert "backup" in shown and "La cheffe de serre" in shown and "relations" in shown
    assert "Cancelled" in shown
    async with test_pool.acquire() as conn:
        assert await _state(conn, game, drop) == (0, None)

    yes = merge_entities.build_parser().parse_args(_args(game, keep, drop, "--yes"))
    assert await merge_entities._main(yes) == 0
    assert "Merged" in capsys.readouterr().out
    async with test_pool.acquire() as conn:
        count, merged_into = await _state(conn, game, drop)
        moved = await conn.fetchval(
            "SELECT count(*) FROM relations WHERE source_id = $1 AND target_id = $2",
            keep,
            other,
        )
    assert (count, merged_into, moved) == (1, keep, 1)


def test_merge_script_requires_a_database_url():
    with pytest.raises(SystemExit):
        merge_entities.build_parser().parse_args(
            [
                "--game",
                str(UUID(int=1)),
                "--keep",
                "E1",
                "--drop",
                "E2",
                "--reason",
                "x",
            ]
        )
