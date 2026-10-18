"""Rollback restores the state a turn's own transaction wrote (stress, wounds, fate/force
points), never progression written by the extraction after the commit (#134)."""

from types import SimpleNamespace


from services.engine import d6, fate_core
from tests.characterization import payloads
from tests.helpers import STRESS, narration_with, rollback_last_turn


async def _engine_game(harness, engine):
    game_id = await harness.create_game(engine)
    await harness.init_world(game_id, engine=engine,
                             character_data=payloads.CHARACTER_DATA.get(engine))
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    await harness.chat(game_id, "Je regarde autour de moi.")  # turn N, plain
    await harness.drain()
    return game_id


async def test_fate_rollback_restores_stress_and_fate_points_but_not_progression(
        harness, monkeypatch):
    game_id = await _engine_game(harness, "fate_core")
    async with harness.pool.acquire() as conn:
        # Progression applied after turn N, as the extractor would.
        await conn.execute("UPDATE skills_fate SET level = level + 1 WHERE game_id = $1", game_id)
        await conn.execute("UPDATE character_fate SET refresh = refresh + 1 WHERE game_id = $1",
                           game_id)
        sheet = await conn.fetchrow(
            "SELECT stress_physical, fate_points, refresh FROM character_fate WHERE game_id = $1",
            game_id)
        levels = await conn.fetch(
            "SELECT name, level FROM skills_fate WHERE game_id = $1 ORDER BY name", game_id)

    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: 1))
    original = fate_core.FateCoreEngine.roll_dice

    def roll_with_stress(self, decision):
        roll = original(self, decision)
        roll.details.update(STRESS)
        return roll

    monkeypatch.setattr(fate_core.FateCoreEngine, "roll_dice", roll_with_stress)
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    harness.llm._responses["narration"] = narration_with(compel_result="accepted")
    await harness.chat(game_id, "Je force le passage.")
    await harness.drain()
    async with harness.pool.acquire() as conn:
        during = await conn.fetchrow(
            "SELECT stress_physical, fate_points FROM character_fate WHERE game_id = $1", game_id)
    assert during["stress_physical"] != sheet["stress_physical"]
    assert during["fate_points"] == sheet["fate_points"] + 1

    await rollback_last_turn(harness, game_id)
    async with harness.pool.acquire() as conn:
        after = await conn.fetchrow(
            "SELECT stress_physical, fate_points, refresh FROM character_fate WHERE game_id = $1",
            game_id)
        levels_after = await conn.fetch(
            "SELECT name, level FROM skills_fate WHERE game_id = $1 ORDER BY name", game_id)
    assert dict(after) == dict(sheet)  # stress and FP back to turn N's, progression (refresh) kept
    assert [dict(r) for r in levels_after] == [dict(r) for r in levels]


async def test_d6_rollback_restores_wounds_and_force_points_but_not_progression(
        harness, monkeypatch):
    game_id = await _engine_game(harness, "d6")
    async with harness.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO skills_d6 (game_id, attribute, name, dice_value)"
            " VALUES ($1, 'Dexterité', 'Esquive', '5D')", game_id)
        sheet = await conn.fetchrow(
            "SELECT wounds, force_points FROM character_d6 WHERE game_id = $1", game_id)
        skills = await conn.fetch(
            "SELECT name, dice_value FROM skills_d6 WHERE game_id = $1 ORDER BY name", game_id)
    assert skills

    monkeypatch.setattr(d6, "random", SimpleNamespace(randint=lambda a, b: 4))
    original = d6.D6Engine.roll_dice

    def roll_with_wound(self, decision):
        roll = original(self, decision)
        roll.details.update({"wound_level": "wounded", "force_points_spent": 1})
        return roll

    monkeypatch.setattr(d6.D6Engine, "roll_dice", roll_with_wound)
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    await harness.chat(game_id, "Je force le passage.")
    await harness.drain()
    async with harness.pool.acquire() as conn:
        during = await conn.fetchrow(
            "SELECT wounds, force_points FROM character_d6 WHERE game_id = $1", game_id)
    assert during["wounds"] != sheet["wounds"] and during["force_points"] < sheet["force_points"]

    await rollback_last_turn(harness, game_id)
    async with harness.pool.acquire() as conn:
        after = await conn.fetchrow(
            "SELECT wounds, force_points FROM character_d6 WHERE game_id = $1", game_id)
        skills_after = await conn.fetch(
            "SELECT name, dice_value FROM skills_d6 WHERE game_id = $1 ORDER BY name", game_id)
    assert dict(after) == dict(sheet)
    assert [dict(r) for r in skills_after] == [dict(r) for r in skills]  # the new skill is kept


async def test_narrative_rollback_leaves_traits_untouched(harness, caplog):
    game_id = await _engine_game(harness, "narrative")
    async with harness.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO traits_narrative (game_id, name, description, active, created_cycle)"
            " VALUES ($1, 'Aguerri', 'Gagné au tour N', TRUE, 1)", game_id)
        before = await conn.fetch(
            "SELECT name, active FROM traits_narrative WHERE game_id = $1 ORDER BY name", game_id)
    await harness.chat(game_id, "J'avance.")
    await harness.drain()
    await rollback_last_turn(harness, game_id)
    async with harness.pool.acquire() as conn:
        after = await conn.fetch(
            "SELECT name, active FROM traits_narrative WHERE game_id = $1 ORDER BY name", game_id)
    assert [dict(r) for r in after] == [dict(r) for r in before]
    assert any(r["name"] == "Aguerri" and r["active"] for r in after)
    assert "No engine snapshot" not in caplog.text  # an empty snapshot is not a legacy row


async def test_rollback_without_engine_snapshot_keeps_the_engine_state(harness, caplog):
    """Legacy messages saved before snapshots: the rollback works and warns, state is kept."""
    game_id = await _engine_game(harness, "d6")
    async with harness.pool.acquire() as conn:
        await conn.execute("UPDATE messages SET engine_snapshot = NULL WHERE game_id = $1",
                           game_id)
        sheet = await conn.fetchrow(
            "SELECT wounds, force_points FROM character_d6 WHERE game_id = $1", game_id)
    await harness.chat(game_id, "J'avance.")
    await harness.drain()
    await rollback_last_turn(harness, game_id)
    async with harness.pool.acquire() as conn:
        after = await conn.fetchrow(
            "SELECT wounds, force_points FROM character_d6 WHERE game_id = $1", game_id)
    assert dict(after) == dict(sheet)
    assert "No engine snapshot" in caplog.text
