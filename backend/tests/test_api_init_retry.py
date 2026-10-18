"""Retrying a failed world generation keeps the wizard parameters (#88).

The game list retries with a bare __INIT__: the server reads back what the first
__INIT__ sent (genre, lore, difficulty, duration, character sheet, manual entities).
"""

import json
from uuid import UUID

from api.request_types import WIZARD_FORM_MAX_CHARS
from helpers import OVERSIZED_WIZARD_FORM
from tests.characterization import payloads
from tests.characterization.harness import spy_narration

LORE = "Une station minière oubliée sous la glace d'Europe."
WORLD_CONFIG = {"genre": "cyberpunk", "difficulty": "hard", "duration": "short",
                "hardcore": False, "lore": LORE}
MANUAL_ENTITIES = {
    "npcs": [{"name": "Varek Osu", "description": "Contrebandier au bras mécanique"}],
    "locations": [{"name": "Puits Thalassa", "description": "Le puits de forage principal"}],
    "organizations": [],
}
FATE_SHEET = {**payloads.CHARACTER_DATA["fate_core"], "occupation": "Pilote de cargo"}
WIZARD = {"engine": "fate_core", "world_config": WORLD_CONFIG,
          "character_data": FATE_SHEET, "manual_entities": MANUAL_ENTITIES}


def _prompt_text(call: dict) -> str:
    return call["system"] + "\n".join(m["content"] for m in call["messages"])


async def _fail_then_retry(harness, monkeypatch, retry_extra: dict) -> tuple[str, list[dict]]:
    prompts = spy_narration(monkeypatch)
    harness.llm._responses["world_gen"] = ["pas du JSON", payloads.WORLD_GEN]
    game_id = await harness.create_game("fate_core")

    first = await harness.chat(game_id, "__INIT__", **WIZARD)
    await harness.drain()
    assert [e.get("code") for e in first if e.get("type") == "error"] == ["world_gen_failed"]

    second = await harness.chat(game_id, "__INIT__", **retry_extra)
    await harness.drain()
    assert "done" in harness.summarize(second), harness.summarize(second)
    assert harness.llm.purposes().count("world_gen") == 2
    return game_id, prompts


async def test_bare_retry_uses_the_original_wizard_parameters(harness, monkeypatch):
    game_id, prompts = await _fail_then_retry(harness, monkeypatch, {})

    retry_prompt = _prompt_text(prompts[1])
    assert retry_prompt == _prompt_text(prompts[0])  # same generation request, twice
    for expected in (LORE, "Varek Osu", "Puits Thalassa", "Occupation : Pilote de cargo",
                     "Genre : cyberpunk | Difficulté : hard"):
        assert expected in retry_prompt, expected

    gid = UUID(game_id)
    async with harness.pool.acquire() as conn:
        game = await conn.fetchrow(
            """SELECT g.engine, g.game_duration, g.world_config, gr.slug
               FROM games g LEFT JOIN genres gr ON gr.id = g.genre_id WHERE g.id = $1""", gid)
        aspects = await conn.fetch(
            "SELECT name, kind FROM aspects_fate WHERE game_id = $1 ORDER BY position", gid)
        pc_name = await conn.fetchval("SELECT name FROM protagonists WHERE game_id = $1", gid)
        skills = dict(await conn.fetch(
            "SELECT name, level FROM skills_fate WHERE game_id = $1", gid))
    world_config = game["world_config"]
    if isinstance(world_config, str):
        world_config = json.loads(world_config)
    assert (game["engine"], game["slug"], game["game_duration"]) == ("fate_core", "cyberpunk",
                                                                     "short")
    assert world_config["lore"] == LORE and world_config["difficulty"] == "hard"
    assert [(a["name"], a["kind"]) for a in aspects] == [
        (FATE_SHEET["aspects"]["high_concept"], "high_concept"),
        (FATE_SHEET["aspects"]["trouble"], "trouble"),
        (FATE_SHEET["aspects"]["other"][0], "other"),
    ]
    assert pc_name == FATE_SHEET["name"]  # the wizard name over the model's (#28)
    assert skills == FATE_SHEET["skills"]  # the wizard pyramid, not an empty sheet


async def _stored(harness, game_id: str) -> dict:
    async with harness.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT world_config, character_data, manual_entities FROM games WHERE id = $1",
            UUID(game_id))
    return {k: json.loads(v) if isinstance(v, str) else v for k, v in dict(row).items()}


async def test_retry_with_parameters_replaces_the_stored_set(harness, monkeypatch):
    """The player edited the wizard before retrying: the parameters it sends replace the
    stored set entirely. The wizard sends null for a part it left empty (no entities, no
    character): that part is cleared, not restored from the first __INIT__."""
    edited = {k: v for k, v in WORLD_CONFIG.items() if k != "lore"}  # lore cleared
    game_id, prompts = await _fail_then_retry(harness, monkeypatch, {
        "engine": "fate_core", "world_config": edited, "character_data": FATE_SHEET,
        "manual_entities": None})

    retry_prompt = _prompt_text(prompts[1])
    assert LORE not in retry_prompt
    assert "Varek Osu" not in retry_prompt and "Puits Thalassa" not in retry_prompt
    assert "Occupation : Pilote de cargo" in retry_prompt
    stored = await _stored(harness, game_id)
    assert stored["world_config"] == edited  # no lore
    assert stored["manual_entities"] is None
    assert stored["character_data"] == FATE_SHEET


async def test_edited_retry_lore_wins(harness, monkeypatch):
    edited = {**WORLD_CONFIG, "lore": "Une colonie pénitentiaire sur Titan."}
    _, prompts = await _fail_then_retry(harness, monkeypatch, {**WIZARD, "world_config": edited})
    retry_prompt = _prompt_text(prompts[1])
    assert "Une colonie pénitentiaire sur Titan." in retry_prompt
    assert LORE not in retry_prompt


async def test_load_game_returns_the_stored_parameters_until_the_world_exists(harness):
    """'Modifier les paramètres' in a browser without the draft is prefilled from these."""
    harness.llm._responses["world_gen"] = ["pas du JSON", payloads.WORLD_GEN]
    game_id = await harness.create_game("fate_core")
    await harness.chat(game_id, "__INIT__", **WIZARD)
    await harness.drain()

    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.status_code == 200, r.text
    assert r.json()["init_params"] == {"engine": "fate_core", "world_config": WORLD_CONFIG,
                                       "character_data": FATE_SHEET,
                                       "manual_entities": MANUAL_ENTITIES}

    await harness.chat(game_id, "__INIT__")
    await harness.drain()
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    assert r.json()["state"]["world_created"] is True
    assert r.json().get("init_params") is None


async def test_wizard_form_over_the_whole_form_bound_is_refused(harness):
    """Each part fits, the whole form does not: refused like /world/enhance does."""
    game_id = await harness.create_game("fate_core")
    r = await harness.client.post("/api/chat", headers=harness.headers, json={
        "message": "__INIT__", "gameId": game_id, **OVERSIZED_WIZARD_FORM})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == (
        f"Requête invalide : requête : formulaire trop long (max {WIZARD_FORM_MAX_CHARS} caractères).")
    assert harness.llm.calls == []
    async with harness.pool.acquire() as conn:
        assert await conn.fetchval("SELECT world_config FROM games WHERE id = $1",
                                   UUID(game_id)) is None


async def test_oversized_wizard_parameters_are_refused_before_anything_is_stored(harness):
    game_id = await harness.create_game("fate_core")
    big = {**WORLD_CONFIG, "lore": "x" * 25_000}
    r = await harness.client.post("/api/chat", headers=harness.headers, json={
        "message": "__INIT__", "gameId": game_id, "world_config": big})
    assert r.status_code == 422, r.text
    assert r.json()["detail"].startswith("Requête invalide : world_config"), r.text
    many = {"npcs": [{"name": f"n{i}"} for i in range(25)]}
    r = await harness.client.post("/api/chat", headers=harness.headers, json={
        "message": "__INIT__", "gameId": game_id, "manual_entities": many})
    assert r.status_code == 422, r.text
    assert harness.llm.calls == []
    async with harness.pool.acquire() as conn:
        assert await conn.fetchval("SELECT world_config FROM games WHERE id = $1",
                                   UUID(game_id)) is None
