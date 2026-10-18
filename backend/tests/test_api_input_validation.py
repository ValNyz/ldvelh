"""Bad client input answers 4xx with a French message that never echoes the input (#91)."""

import logging

import pytest

from helpers import auth_headers

pytestmark = pytest.mark.integration

# Marker put in every rejected value: it must never come back in the body.
SECRET = "ZZSECRETZZ"


def _assert_french_no_echo(resp, field=None, status=422):
    assert resp.status_code == status, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, str)
    assert SECRET not in resp.text
    assert detail.startswith("Requête invalide : "), detail
    if field:
        assert field in detail, detail


async def _new_game(client, user):
    resp = await client.post("/api/games", headers=auth_headers(user["token"]))
    return resp.json()["gameId"]


@pytest.mark.asyncio
async def test_rollback_bad_message_id(client, test_user):
    game_id = await _new_game(client, test_user)
    resp = await client.post(
        f"/api/games/{game_id}/rollback", json={"messageId": SECRET},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "messageId")


@pytest.mark.asyncio
async def test_rename_too_long(client, test_user):
    game_id = await _new_game(client, test_user)
    resp = await client.patch(
        f"/api/games/{game_id}", json={"name": SECRET + "x" * 300},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "name")


@pytest.mark.asyncio
async def test_rename_blank(client, test_user):
    game_id = await _new_game(client, test_user)
    resp = await client.patch(
        f"/api/games/{game_id}", json={"name": "   "},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "name")


@pytest.mark.asyncio
async def test_create_game_unknown_engine_rejected_and_not_stored(client, test_user):
    resp = await client.post(
        "/api/games", json={"engine": SECRET},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "engine")
    listing = await client.get("/api/games", headers=auth_headers(test_user["token"]))
    assert listing.json()["games"] == []


@pytest.mark.asyncio
async def test_create_game_valid_engine_still_works(client, test_user):
    resp = await client.post(
        "/api/games", json={"engine": "fate_core"},
        headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    game_id = resp.json()["gameId"]
    load = await client.get(f"/api/games/{game_id}", headers=auth_headers(test_user["token"]))
    assert load.status_code == 200


def _register(**over):
    body = {"email": "ok@test.com", "password": "secure123", "password_confirm": "secure123"}
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_register_bad_email(client):
    resp = await client.post("/api/auth/register", json=_register(email=SECRET))
    _assert_french_no_echo(resp, "email")


@pytest.mark.asyncio
async def test_register_display_name_too_long(client):
    resp = await client.post(
        "/api/auth/register", json=_register(display_name=SECRET + "x" * 100))
    _assert_french_no_echo(resp, "display_name")


@pytest.mark.asyncio
async def test_preferences_api_keys_not_a_dict(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences", json={"preferences": {"api_keys": [SECRET]}},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "preferences")


@pytest.mark.asyncio
async def test_preferences_api_key_too_long(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"api_keys": {"anthropic": SECRET + "k" * 600}}},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "preferences")


@pytest.mark.asyncio
async def test_preferences_too_large(client, test_user):
    resp = await client.patch(
        "/api/auth/preferences",
        json={"preferences": {"notes": SECRET + "n" * 20_000}},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "preferences")


@pytest.mark.asyncio
async def test_chat_unknown_engine(client, test_user):
    game_id = await _new_game(client, test_user)
    resp = await client.post(
        "/api/chat", json={"gameId": game_id, "message": "x", "engine": SECRET},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "engine")


@pytest.mark.asyncio
async def test_world_enhance_unknown_engine(client, test_user):
    resp = await client.post(
        "/api/world/enhance", json={"engine": SECRET},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "engine")


@pytest.mark.asyncio
async def test_profile_display_name_too_long(client, test_user):
    resp = await client.patch(
        "/api/auth/profile", json={"display_name": SECRET + "x" * 100},
        headers=auth_headers(test_user["token"]))
    _assert_french_no_echo(resp, "display_name")


@pytest.mark.asyncio
async def test_malformed_json_body(client, test_user):
    resp = await client.post(
        "/api/games", content="{" + SECRET,
        headers={**auth_headers(test_user["token"]), "Content-Type": "application/json"})
    _assert_french_no_echo(resp)


@pytest.mark.asyncio
async def test_email_with_trailing_newline_rejected(client):
    resp = await client.post("/api/auth/register", json=_register(email="a@b.co\n"))
    _assert_french_no_echo(resp, "email")


@pytest.mark.asyncio
async def test_preferences_cap_applies_to_the_merged_result(client, test_user):
    h = auth_headers(test_user["token"])
    first = await client.patch(
        "/api/auth/preferences", json={"preferences": {"a": "x" * 10_000}}, headers=h)
    assert first.status_code == 200
    second = await client.patch(
        "/api/auth/preferences", json={"preferences": {"b": "y" * 10_000}}, headers=h)
    _assert_french_no_echo(second)
    stored = (await client.get("/api/auth/preferences", headers=h)).json()["preferences"]
    assert "a" in stored and "b" not in stored


@pytest.mark.asyncio
async def test_request_bounds_equal_the_db_columns(test_pool):
    from typing import get_args

    from api.request_types import DisplayName, Email, GameName

    def width(tp):
        return next(m.max_length for m in get_args(tp) if getattr(m, "max_length", None))

    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT table_name, column_name, character_maximum_length FROM information_schema.columns"
            " WHERE (table_name, column_name) IN (('games','name'),('users','email'),"
            "('users','display_name'))")
    widths = {(r["table_name"], r["column_name"]): r["character_maximum_length"] for r in rows}
    assert widths == {("games", "name"): width(GameName), ("users", "email"): width(Email),
                      ("users", "display_name"): width(DisplayName)}


# --- French client-facing messages (#91 round 1) ---------------------------------------

@pytest.mark.asyncio
async def test_login_wrong_password_is_french(client, test_user):
    resp = await client.post("/api/auth/login", json={
        "identifier": "test@example.com", "password": "nope-nope"})
    assert (resp.status_code, resp.json()["detail"]) == (401, "E-mail ou mot de passe incorrect.")


@pytest.mark.asyncio
async def test_register_conflict_and_mismatch_are_french(client, test_user):
    dup = await client.post("/api/auth/register", json=_register(email="test@example.com"))
    assert (dup.status_code, dup.json()["detail"]) == (409, "Cette adresse e-mail est déjà utilisée.")
    bad = await client.post("/api/auth/register", json=_register(password_confirm="autre123"))
    assert (bad.status_code, bad.json()["detail"]) == (400, "Les mots de passe ne correspondent pas.")


@pytest.mark.asyncio
async def test_token_errors_are_french(client):
    none = await client.get("/api/games")
    assert (none.status_code, none.json()["detail"]) == (401, "Jeton manquant ou invalide.")
    bad = await client.get("/api/games", headers=auth_headers("garbage"))
    assert (bad.status_code, bad.json()["detail"]) == (401, "Jeton invalide.")


@pytest.mark.asyncio
async def test_change_password_errors_are_french(client, test_user):
    h = auth_headers(test_user["token"])
    resp = await client.post("/api/auth/change-password", headers=h, json={
        "current_password": "x", "new_password": "abcdef", "new_password_confirm": "abcdeg"})
    assert resp.json()["detail"] == "Les nouveaux mots de passe ne correspondent pas."
    resp = await client.post("/api/auth/change-password", headers=h, json={
        "current_password": "x", "new_password": "abc", "new_password_confirm": "abc"})
    assert resp.json()["detail"] == "Le mot de passe doit faire au moins 6 caractères."
    resp = await client.post("/api/auth/change-password", headers=h, json={
        "current_password": "wrong-one", "new_password": "abcdef", "new_password_confirm": "abcdef"})
    assert resp.json()["detail"] == "Mot de passe actuel incorrect."


@pytest.mark.asyncio
async def test_verify_and_unknown_provider_and_genre_are_french(client, test_user):
    h = auth_headers(test_user["token"])
    resp = await client.get("/api/auth/verify", params={"token": "short"})
    assert resp.json()["detail"] == "Lien de vérification invalide."
    resp = await client.get("/api/auth/verify", params={"token": "x" * 20})
    assert resp.json()["detail"].startswith("Lien de vérification invalide ou expiré")
    resp = await client.patch("/api/auth/preferences", headers=h,
                              json={"preferences": {"api_keys": {SECRET: "k"}}})
    assert resp.status_code == 400 and resp.json()["detail"].startswith("Fournisseur inconnu")
    assert SECRET not in resp.text
    resp = await client.get("/api/genres/00000000-0000-0000-0000-000000000000", headers=h)
    assert resp.status_code == 404 and resp.json()["detail"] == "Genre introuvable."


# --- games stored with an unknown engine still load (#91 round 1) ----------------------

def test_coerce_engine():
    from schema import EngineType, coerce_engine

    assert coerce_engine("d6") is EngineType.D6
    assert coerce_engine(None) is EngineType.NONE and coerce_engine("") is EngineType.NONE


def test_coerce_engine_unknown_warns_with_game_id(caplog):
    from schema import EngineType, coerce_engine

    with caplog.at_level(logging.WARNING):
        assert coerce_engine("foo", "game-42") is EngineType.NONE
    assert "game-42" in caplog.text and "foo" in caplog.text


@pytest.mark.asyncio
async def test_game_with_stored_unknown_engine_loads_as_none(client, test_user, test_pool, caplog):
    game_id = await _new_game(client, test_user)
    async with test_pool.acquire() as conn:
        await conn.execute("UPDATE games SET engine = 'foo' WHERE id = $1::uuid", game_id)
    with caplog.at_level(logging.WARNING):
        resp = await client.get(f"/api/games/{game_id}", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"]["game"]["engine"] == "none"
    assert any(game_id in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.asyncio
async def test_migration_rewrites_invalid_engines(test_pool, client, test_user):
    from pathlib import Path

    game_id = await _new_game(client, test_user)
    sql = next(Path(__file__).resolve().parents[2].joinpath("db/migrations").glob(
        "*_invalid_game_engine.sql")).read_text()
    up = sql.split("-- migrate:down")[0].replace("-- migrate:up", "")
    async with test_pool.acquire() as conn:
        await conn.execute("UPDATE games SET engine = 'foo' WHERE id = $1::uuid", game_id)
        await conn.execute(up)
        assert await conn.fetchval("SELECT engine FROM games WHERE id = $1::uuid", game_id) == "none"
