"""#93: the kind of a Fate aspect (high_concept / trouble / other) is stored, not inferred.

Real DB: aspects_fate rows written by create_character and kept by progression renames,
at most one high concept and one trouble per character, and the migration that moved
character_fate.aspects (jsonb) into aspects_fate (up / down / up).
"""

from pathlib import Path

import asyncpg
import pytest

from services.engine import get_engine

FATE = get_engine("fate_core")


def _migration() -> tuple[str, str]:
    """(up, down) SQL of the migration that stores the aspect kind."""
    sql = next(Path(__file__).resolve().parents[2].joinpath("db/migrations").glob(
        "*_fate_aspect_kind.sql")).read_text(encoding="utf-8")
    up, down = sql.split("-- migrate:down")
    return up.replace("-- migrate:up", ""), down


def _wizard(high_concept="", trouble="", other=()):
    return {"aspects": {"high_concept": high_concept, "trouble": trouble, "other": list(other)},
            "skills": {"Combat": 2}}


async def _fate_character(harness, data: dict) -> str:
    game_id = await harness.create_game("fate_core")
    async with harness.pool.acquire() as conn:
        await FATE.create_character(conn, game_id, data)
    return game_id


async def _sheet_aspects(harness, game_id: str) -> list[dict]:
    async with harness.pool.acquire() as conn:
        return (await FATE.get_sheet_display(conn, game_id))["aspects"]


async def test_empty_high_concept_labels_no_aspect_as_concept(harness):
    game_id = await _fate_character(harness, _wizard(trouble="Dettes", other=["Cargo", ""]))
    assert await _sheet_aspects(harness, game_id) == [
        {"type": "trouble", "name": "Dettes"}, {"type": "other", "name": "Cargo"}]


async def test_empty_trouble_promotes_no_other_aspect(harness):
    game_id = await _fate_character(harness, _wizard(high_concept="Pilote", other=["Cargo"]))
    assert await _sheet_aspects(harness, game_id) == [
        {"type": "high_concept", "name": "Pilote"}, {"type": "other", "name": "Cargo"}]


async def test_rename_keeps_kind_and_position(harness):
    game_id = await _fate_character(
        harness, _wizard(high_concept="Pilote", trouble="Dettes", other=["Cargo"]))
    async with harness.pool.acquire() as conn:
        await FATE.apply_progression(conn, game_id, {"aspect_renames": [
            {"old_name": "Dettes", "new_name": "Dettes envers la Guilde"}]})
    assert await _sheet_aspects(harness, game_id) == [
        {"type": "high_concept", "name": "Pilote"},
        {"type": "trouble", "name": "Dettes envers la Guilde"},
        {"type": "other", "name": "Cargo"}]


async def test_at_most_one_high_concept_and_one_trouble(harness):
    game_id = await _fate_character(harness, _wizard(high_concept="Pilote", trouble="Dettes"))
    async with harness.pool.acquire() as conn:
        for kind in ("high_concept", "trouble"):
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO aspects_fate (game_id, position, name, kind) "
                    "VALUES ($1, 10, 'Doublon', $2)", game_id, kind)
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO aspects_fate (game_id, position, name, kind) "
                "VALUES ($1, 11, 'Inconnu', 'nemesis')", game_id)


async def test_migration_down_then_up_keeps_aspects(harness):
    """Down writes the legacy string list back; up rebuilds the rows with the backfill
    heuristic: with two aspects or more, first = high concept, second = trouble."""
    full = await _fate_character(
        harness, _wizard(high_concept="Pilote", trouble="Dettes", other=["Cargo"]))
    alone = await _fate_character(harness, _wizard(trouble="Dettes"))
    up, down = _migration()
    async with harness.pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute(down)
            legacy = {g: await conn.fetchval(
                "SELECT aspects FROM character_fate WHERE game_id = $1", g) for g in (full, alone)}
            assert legacy == {full: ["Pilote", "Dettes", "Cargo"], alone: ["Dettes"]}
            # A legacy dict-shaped row keeps its own kinds; a duplicate kind becomes 'other'.
            await conn.execute(
                "UPDATE character_fate SET aspects = $1 WHERE game_id = $2",
                [{"name": "A", "type": "trouble"}, {"text": "B", "type": "trouble"}, "", "C"],
                alone)
            await conn.execute(up)
            rows = {g: [tuple(r) for r in await conn.fetch(
                "SELECT position, name, kind FROM aspects_fate WHERE game_id = $1 ORDER BY position",
                g)] for g in (full, alone)}
            assert rows == {
                full: [(0, "Pilote", "high_concept"), (1, "Dettes", "trouble"), (2, "Cargo", "other")],
                alone: [(0, "A", "trouble"), (1, "B", "other"), (2, "C", "other")],
            }
            assert await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'character_fate' AND column_name = 'aspects'") == 0
        finally:
            await tr.rollback()
