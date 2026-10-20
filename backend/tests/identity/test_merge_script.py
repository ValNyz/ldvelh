"""The operator merge script (#153): a refusal on stdin changes nothing, --yes merges."""

import builtins
import json
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


async def _run(argv) -> int:
    return await merge_entities._main(merge_entities.build_parser().parse_args(argv))


@pytest.mark.parametrize("case", ["unknown_handle", "bad_uuid", "other_game"])
async def test_merge_script_rejects_a_bad_entity_reference(
    test_pool, test_user, case, monkeypatch
):
    monkeypatch.setattr(builtins, "input", lambda prompt="": pytest.fail("prompted"))
    async with test_pool.acquire() as conn:
        game, keep, drop, _ = await _setup(conn, test_user["id"])
        elsewhere = await _setup(conn, test_user["id"])
    ref = {
        "unknown_handle": "E999999",
        "bad_uuid": "not-a-uuid",
        "other_game": str(elsewhere[2]),
    }[case]
    with pytest.raises(SystemExit, match="no entity"):
        await _run(_args(game, keep, ref, "--yes"))
    async with test_pool.acquire() as conn:
        assert await _state(conn, game, drop) == (0, None)


async def test_edge_preview_matches_what_the_merge_moves(test_pool, test_user):
    from repos import entities

    async with test_pool.acquire() as conn:
        game, keep, drop, _other = await _setup(conn, test_user["id"])
        await conn.fetchval(
            "SELECT create_fact($1, 1, 'action', 'Un fait', p_participants => $2::jsonb)",
            game,
            [{"entity_id": str(drop), "role": "actor"}],
        )
        before = await conn.fetchval("SELECT count(*) FROM world_changes")
        preview = await entities.edge_preview(conn, keep, drop, "character")
        assert await conn.fetchval("SELECT count(*) FROM world_changes") == before
        assert await _state(conn, game, drop) == (0, None)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM relations WHERE source_id = $1", drop
            )
            == 1
        )
        merge_id = await conn.fetchval(
            "SELECT merge_entities($1, $2, 't', NULL)", keep, drop
        )
        moved = await conn.fetchval(
            "SELECT moved_edges FROM entity_merges WHERE id = $1", merge_id
        )
    moved = moved if isinstance(moved, dict) else json.loads(moved)
    assert preview == {k: len(v) for k, v in moved.items() if v}
    assert preview["relations.source_id"] == 1
    assert preview["fact_participants.entity_id"] == 1


async def test_a_guard_refusal_exits_without_prompt_event_or_write(
    test_pool, test_user, monkeypatch, capsys
):
    monkeypatch.setattr(builtins, "input", lambda prompt="": pytest.fail("prompted"))
    async with test_pool.acquire() as conn:
        game, keep, _, _ = await _setup(conn, test_user["id"])
        location = await conn.fetchval(
            "INSERT INTO locations (game_id, name) VALUES ($1, 'Quai 7') RETURNING id",
            game,
        )
        events = await conn.fetchval("SELECT count(*) FROM identity_events")
    assert await _run(_args(game, keep, location, "--yes")) == 1
    assert "type_mismatch" in capsys.readouterr().out
    async with test_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM identity_events") == events
        assert await _state(conn, game, location) == (0, None)


async def test_merge_script_requires_one_database_url_option(monkeypatch):
    base = ["--game", str(UUID(int=1)), "--keep", "E1", "--drop", "E2", "--reason", "x"]
    with pytest.raises(SystemExit):
        merge_entities.main(base)
    monkeypatch.delenv("MERGE_URL", raising=False)
    with pytest.raises(SystemExit):
        merge_entities.main([*base, "--database-url-env", "MERGE_URL"])
    with pytest.raises(SystemExit):
        merge_entities.main([*base, "--database-url", "x", "--database-url-env", "Y"])


async def test_a_failed_connection_prints_no_url_and_no_traceback(capsys):
    url = "postgres://nobody:secretpw@127.0.0.1:1/none"
    args = merge_entities.build_parser().parse_args(_args(UUID(int=1), "E1", "E2"))
    args.database_url = url
    assert await merge_entities._main(args) == 2
    err = capsys.readouterr().err
    assert "Cannot connect" in err and "secretpw" not in err and "Traceback" not in err
