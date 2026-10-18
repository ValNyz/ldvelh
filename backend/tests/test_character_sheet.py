"""F-26 / #93: the character sheet (aspects, skills, attributes) reaches the frontend.

Real DB, through the app: GET /games/{id} (load_game_state) and the `done` payload of a
narration turn both carry `player.sheet`, built by the engine's get_sheet_display.
"""

from services.engine.fate_core import sheet_aspects
from tests.characterization import payloads

FATE_ASPECTS = payloads.CHARACTER_DATA["fate_core"]["aspects"]


async def _played_game(harness, engine: str) -> tuple[str, dict]:
    """Game with world and arrival played, then one plain turn: (game_id, done event)."""
    game_id = await harness.create_game(engine)
    await harness.init_world(game_id, engine=engine,
                             character_data=payloads.CHARACTER_DATA.get(engine))
    if engine == "d6":
        # The wizard's D6 skills are not created yet (#29): seed the table directly.
        async with harness.pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO skills_d6 (game_id, attribute, name, dice_value) "
                "VALUES ($1, $2, $3, $4)",
                [(game_id, "Dextérité", "Blaster", "4D"),
                 (game_id, "Mécanique", "Pilotage", "3D+2")])
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    harness.llm._responses["mechanical"] = payloads.mechanical(requires_test=False)
    events = await harness.chat(game_id, "Je regarde autour de moi.")
    await harness.drain()
    done = [e for e in events if e["type"] == "done"]
    assert done, harness.summarize(events)
    return game_id, done[0]


async def _loaded_player(harness, game_id: str) -> dict:
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.status_code == 200, r.text
    return r.json()["state"]["player"]


def _done_player(done: dict) -> dict:
    return done["state"]["game_state"]["player"]


def _assert_fate_sheet(sheet: dict) -> None:
    assert sheet["aspects"] == [
        {"type": "high_concept", "name": FATE_ASPECTS["high_concept"]},
        {"type": "trouble", "name": FATE_ASPECTS["trouble"]},
        {"type": "other", "name": FATE_ASPECTS["other"][0]},
    ]
    levels = [(s["name"], s["level"]) for s in sheet["skills"]]
    assert levels[0] == ("Athlétisme", 4)
    assert sorted(lvl for _, lvl in levels) == [1, 1, 1, 1, 2, 2, 2, 3, 3, 4]
    assert sheet["skills"][0]["label"] == "Excellent"


def _assert_d6_sheet(sheet: dict) -> None:
    assert sheet["attributes"] == payloads.CHARACTER_DATA["d6"]["attributes"]
    assert [(s["attribute"], s["name"], s["dice_value"]) for s in sheet["skills"]] == [
        ("Dextérité", "Blaster", "4D"), ("Mécanique", "Pilotage", "3D+2")]


async def test_fate_sheet_in_load_game_state_and_done_payload(harness):
    game_id, done = await _played_game(harness, "fate_core")
    loaded = await _loaded_player(harness, game_id)
    _assert_fate_sheet(loaded["sheet"])
    _assert_fate_sheet(_done_player(done)["sheet"])
    # Vitals stay where they were.
    assert loaded["engine_stats"]["fate_points"] == 3
    assert "aspects" not in loaded["engine_stats"]


async def test_d6_sheet_in_load_game_state_and_done_payload(harness):
    game_id, done = await _played_game(harness, "d6")
    loaded = await _loaded_player(harness, game_id)
    _assert_d6_sheet(loaded["sheet"])
    _assert_d6_sheet(_done_player(done)["sheet"])
    assert "force_points" in loaded["engine_stats"]


async def test_narrative_game_has_no_sheet(harness):
    game_id, done = await _played_game(harness, "narrative")
    assert not (await _loaded_player(harness, game_id)).get("sheet")
    assert not _done_player(done).get("sheet")


def test_sheet_aspects_types_strings_by_position_and_keeps_dict_types():
    assert sheet_aspects(["Pilote", "Dettes", "Cargo", "Ami fidèle"]) == [
        {"type": "high_concept", "name": "Pilote"}, {"type": "trouble", "name": "Dettes"},
        {"type": "other", "name": "Cargo"}, {"type": "other", "name": "Ami fidèle"}]
    assert sheet_aspects([{"name": "Pilote", "type": "trouble"}, {"text": "Cargo"}, ""]) == [
        {"type": "trouble", "name": "Pilote"}, {"type": "trouble", "name": "Cargo"}]
    assert sheet_aspects(None) == []
