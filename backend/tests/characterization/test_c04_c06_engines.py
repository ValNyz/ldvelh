"""C-04..C-06: rule engines, Fate aspect invocation (pending roll + resume), compels."""

from types import SimpleNamespace

import pytest

from services.engine import d6, fate_core
from tests.characterization import payloads
from tests.characterization.harness import spy_narration
from tests.characterization.snapshot import assert_snapshot


async def _engine_game(harness, engine):
    game_id = await harness.create_game(engine)
    await harness.init_world(game_id, engine=engine,
                             character_data=payloads.CHARACTER_DATA.get(engine))
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    harness.llm.calls.clear()
    return game_id


async def _fate_points(harness, game_id):
    async with harness.pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT fate_points FROM character_fate WHERE game_id = $1", game_id)


def _roll_fields(events):
    """Stable fields of the roll_result event (no ids/timestamps)."""
    rolls = [e["roll"] for e in events if e["type"] == "roll_result"]
    if not rolls:
        return None
    r = rolls[0]
    d = r.get("details", {})
    return {
        "dice": r["dice"], "total": r["total"], "skill_total": r["skill_total"],
        "shifts": r.get("shifts"), "outcome": r["outcome"],
        "skill": d.get("skill_name"), "difficulty": d.get("difficulty"),
        "invoked_aspects": d.get("invoked_aspects"),
        "invocation_bonus": d.get("invocation_bonus"),
        "fate_points_spent": d.get("fate_points_spent"),
    }


@pytest.mark.parametrize("engine", ["narrative", "fate_core", "d6"])
async def test_c04_engine_turn_with_test(harness, engine, monkeypatch):
    game_id = await _engine_game(harness, engine)
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=2, difficulty=1)
    # Dice stubbed so the outcome does not depend on the global seed's call count.
    # Fate: all +1 (success; a failure would pause on roll_pending). D6: every die shows 4.
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: 1))
    monkeypatch.setattr(d6, "random", SimpleNamespace(randint=lambda a, b: 4))
    events = await harness.chat(game_id, "Je saute par-dessus la barrière.")
    await harness.drain()
    snap = harness.snapshot(events, await harness.db_summary(game_id))
    snap["roll"] = _roll_fields(events)
    assert_snapshot(f"c04_engine_turn[{engine}]", snap)


@pytest.mark.parametrize("engine", ["fate_core", "d6"])
async def test_c04b_mechanical_failure_warns_and_narrates(harness, engine):
    """#10: an unusable mechanical answer sends a warning; the turn still narrates, no roll."""
    game_id = await _engine_game(harness, engine)
    harness.llm._responses["mechanical"] = "pas du JSON"
    events = await harness.chat(game_id, "Je force la porte.")
    await harness.drain()
    warnings = [e for e in events if e["type"] == "warning"]
    assert_snapshot(f"c04b_mechanical_failure[{engine}]", {
        "sse": harness.summarize(events),
        "warnings": [w.get("message") for w in warnings],
        "llm_calls": harness.llm.purposes(),
    })


async def test_c04c_arrival_turn_never_rolls_dice(harness):
    """The arrival text is narration only: no mechanical call even if one would ask for a test."""
    game_id = await harness.create_game("fate_core")
    await harness.init_world(game_id, engine="fate_core",
                             character_data=payloads.CHARACTER_DATA["fate_core"])
    harness.llm._responses["mechanical"] = payloads.mechanical(requires_test=True, difficulty=4)
    harness.llm.calls.clear()
    events = await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    assert "mechanical" not in harness.llm.purposes()
    assert "roll_pending" not in harness.summarize(events)


async def test_c05_fate_invocation_pending_then_resume(harness, monkeypatch):
    game_id = await _engine_game(harness, "fate_core")
    harness.llm._responses["mechanical"] = payloads.mechanical(
        requires_test=True, skill="Athlétisme", skill_value=0, difficulty=4)
    # fate_core only uses random.choice for Fudge dice: force four -1 dice (failure).
    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: -1))
    events = await harness.chat(game_id, "Je tente un saut impossible.")
    pending = [e for e in events if e["type"] == "roll_pending"]
    assert pending, harness.summarize(events)
    roll_id = pending[0]["roll_id"]
    aspect = pending[0]["aspects"][0]
    aspect_name = aspect["name"] if isinstance(aspect, dict) else aspect

    fp_before = await _fate_points(harness, game_id)
    resumed = await harness.chat(game_id, "Je tente un saut impossible.",
                                 roll_id=roll_id, invoked_aspects=[aspect_name])
    await harness.drain()
    assert_snapshot("c05_fate_invocation", {
        "first": harness.summarize(events),
        "pending_roll": {k: pending[0]["roll"][k] for k in ("dice", "total", "skill_total", "outcome", "shifts")},
        "pending_fate_points": pending[0]["fate_points"],
        "fate_points_before_resume": fp_before,
        "fate_points_after_resume": await _fate_points(harness, game_id),
        "resume_roll": _roll_fields(resumed),
        "resume": harness.summarize(resumed),
        # Sorted: resolver and director run as concurrent tasks (see ChatHarness.snapshot).
        "llm_calls": sorted(harness.llm.purposes()),
        "db_counts": await harness.db_summary(game_id),
    })


@pytest.mark.parametrize("result,start_fp", [
    ("proposed", None), ("accepted", None), ("refused", None), ("refused", 0),
], ids=["proposed", "accepted", "refused", "refused_at_zero"])
async def test_c06_fate_compel(harness, result, start_fp):
    game_id = await _engine_game(harness, "fate_core")
    if start_fp is not None:
        async with harness.pool.acquire() as conn:
            await conn.execute(
                "UPDATE character_fate SET fate_points = $1 WHERE game_id = $2", start_fp, game_id)
    harness.llm._responses["narration"] = payloads.narration_with_compel(
        payloads.NARRATION, result)
    fp_before = await _fate_points(harness, game_id)
    events = await harness.chat(game_id, "Je traverse le marché.")
    await harness.drain()
    done = [e for e in events if e["type"] == "done"]
    stats = ((done[0].get("state") or {}).get("game_state") or {}).get("engine_stats") if done else None
    assert_snapshot(f"c06_fate_compel[{result if start_fp is None else result + '_at_zero'}]", {
        "sse": harness.summarize(events),
        "done_keys": sorted(done[0].keys()) if done else [],
        "done_fate_points": (stats or {}).get("fate_points"),
        "fate_points_before": fp_before,
        "fate_points_after": await _fate_points(harness, game_id),
        "db_counts": await harness.db_summary(game_id),
    })


async def test_c18_dark_fantasy_arrival_uses_genre_arrival_prompt(harness, monkeypatch):
    """#9: the arrival turn of a real game sends the genre's arrival_prompt, not the
    protocol token nor the SF-only "IA personnelle" fallback."""
    narration_calls = spy_narration(monkeypatch)
    # Preset genres carry an arrival_prompt in production (baseline migration);
    # the test seed does not, so give dark_fantasy one before the game starts.
    async with harness.pool.acquire() as conn:
        await conn.execute(
            "UPDATE genres SET arrival_prompt = $1 WHERE slug = 'dark_fantasy'",
            "{protagonist_name} arrive a {world_name}, une lanterne a la main.")
    game_id = await harness.create_game("none")
    await harness.chat(game_id, "__INIT__", engine="none",
                       world_config={"genre": "dark_fantasy", "difficulty": "moderate"})
    await harness.drain()
    narration_calls.clear()
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    assert narration_calls, "spy captured no narration call"
    sent = str(narration_calls[-1]["messages"])
    assert "une lanterne a la main" in sent
    assert "{world_name}" not in sent and "{protagonist_name}" not in sent
    assert "__ARRIVEE__" not in sent
    assert "IA personnelle" not in sent
