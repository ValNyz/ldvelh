"""Every route that takes a game id answers 403/404 to a user who does not own the game (#81).

The route list is discovered from the app's OpenAPI schema: a new game-scoped route fails
`test_every_game_scoped_route_is_covered` until it is added to GAME_SCOPED_CALLS, which then
runs it through the second_user ownership check. `test_no_route_is_hidden_from_the_schema`
closes the include_in_schema=False hole.
"""

import re
from uuid import UUID

import pytest

from helpers import auth_headers, save_pair

pytestmark = pytest.mark.integration

GAME_ID_NAME = re.compile(r"game_?id", re.IGNORECASE)
GAMES_PATH_PARAM = re.compile(r"/games/\{")  # any {param} right under /games/ is a game id
MAX_SCHEMA_DEPTH = 8
GAME = "<game_id>"  # replaced by the owner's game id in each request

# (method, path) -> httpx request kwargs, GAME standing for the game id.
GAME_SCOPED_CALLS = {
    ("GET", "/api/games/{game_id}"): {},
    ("DELETE", "/api/games/{game_id}"): {},
    ("PATCH", "/api/games/{game_id}"): {"json": {"name": "Volée"}},
    ("GET", "/api/games/{game_id}/world"): {},
    ("POST", "/api/games/{game_id}/rollback"): {"json": {"messageId": "00000000-0000-0000-0000-000000000000"}},
    ("POST", "/api/chat"): {"json": {"gameId": GAME, "message": "Salut"}},
    ("GET", "/api/tooltips/annotations"): {"params": {"gameId": GAME}},
    ("GET", "/api/tooltips/entity"): {
        "params": {"gameId": GAME, "name": "Rook", "entityType": "character"},
    },
}
TOOLTIP_ROUTES = [key for key in GAME_SCOPED_CALLS if key[1].startswith("/api/tooltips/")]


def _schema_field_names(schema, components, depth=0) -> set[str]:
    """Every property name of a body schema, nested objects and list items included."""
    if depth > MAX_SCHEMA_DEPTH or not isinstance(schema, dict):
        return set()
    if "$ref" in schema:
        schema = components.get(schema["$ref"].rsplit("/", 1)[-1], {})
    names = set(schema.get("properties", {}))
    children = [*schema.get("properties", {}).values(), schema.get("items"),
                schema.get("additionalProperties")]
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        children += schema.get(key, [])
    for child in children:
        names |= _schema_field_names(child, components, depth + 1)
    return names


def _reads_game_id(path, op, components) -> bool:
    params = op.get("parameters", [])
    if GAMES_PATH_PARAM.search(path) and any(p["in"] == "path" for p in params):
        return True
    names = {p["name"] for p in params}
    for content in op.get("requestBody", {}).get("content", {}).values():  # JSON, form, multipart
        names |= _schema_field_names(content.get("schema", {}), components)
    return any(GAME_ID_NAME.fullmatch(name) for name in names)


def _game_scoped_routes() -> set[tuple[str, str]]:
    """(method, path) of every API operation reading a game id (path, query, header or body)."""
    from main import app

    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    return {
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method, op in operations.items()
        if _reads_game_id(path, op, components)
    }


def _api_routes(routes):
    """Every APIRoute of the app, through included routers (lazy `original_router`) and mounts."""
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        nested = getattr(getattr(route, "original_router", None), "routes", None)
        nested = nested if nested is not None else getattr(route, "routes", None)
        if nested:
            yield from _api_routes(nested)


def _request(method, path, game_id):
    def fill(value):
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return game_id if value == GAME else value

    kwargs = fill(GAME_SCOPED_CALLS[(method, path)])
    return method, path.replace("{game_id}", game_id), kwargs


def test_every_game_scoped_route_is_covered():
    """A route taking a game id must be listed here, hence checked for ownership below."""
    assert _game_scoped_routes() == set(GAME_SCOPED_CALLS)


def test_no_route_is_hidden_from_the_schema():
    """The discovery above reads the OpenAPI schema: a hidden route would escape it."""
    from main import app

    routes = list(_api_routes(app.routes))
    operations = sum(len(ops) for ops in app.openapi()["paths"].values())
    assert sum(len(r.methods) for r in routes) >= operations  # the walk really sees the routes
    assert [r.path for r in routes if not r.include_in_schema] == []


@pytest.mark.parametrize("name", ["gameId", "game_id", "gameID", "GAME_ID"])
def test_discovery_matches_game_id_spellings(name):
    op = {"parameters": [{"name": name, "in": "query"}]}
    assert _reads_game_id("/api/x", op, {})


def test_discovery_matches_any_path_param_under_games():
    op = {"parameters": [{"name": "id", "in": "path"}]}
    assert _reads_game_id("/api/games/{id}/notes", op, {})


def test_discovery_reads_nested_list_and_form_bodies():
    components = {"Target": {"properties": {"gameId": {"type": "string"}}}}
    nested = {"requestBody": {"content": {"application/json": {"schema": {
        "properties": {"target": {"$ref": "#/components/schemas/Target"}}}}}}}
    listed = {"requestBody": {"content": {"application/json": {"schema": {
        "type": "array", "items": {"$ref": "#/components/schemas/Target"}}}}}}
    form = {"requestBody": {"content": {"multipart/form-data": {"schema": {
        "properties": {"game_id": {"type": "string"}}}}}}}
    assert all(_reads_game_id("/api/x", op, components) for op in (nested, listed, form))
    assert not _reads_game_id("/api/x", {"parameters": [{"name": "genre_id", "in": "path"}]}, {})


async def _owner_view(client, owner, game_id) -> tuple:
    """What a denied request must not change: the game exists, its name, its messages."""
    resp = await client.get(f"/api/games/{game_id}", headers=auth_headers(owner["token"]))
    if resp.status_code != 200:  # e.g. deleted: compare the status, not a missing body
        return resp.status_code, None, 0
    body = resp.json()
    return resp.status_code, body["state"]["game"]["name"], len(body["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", sorted(GAME_SCOPED_CALLS))
async def test_other_user_is_denied_and_changes_nothing(client, test_pool, test_user, second_user,
                                                        method, path):
    game_id = (await client.post("/api/games",
                                 headers=auth_headers(test_user["token"]))).json()["gameId"]
    await save_pair(test_pool, UUID(game_id), "Je regarde autour.", "La coursive est vide.")
    before = await _owner_view(client, test_user, game_id)

    method, url, kwargs = _request(method, path, game_id)
    resp = await client.request(method, url, headers=auth_headers(second_user["token"]), **kwargs)

    assert (resp.status_code, resp.json()) == (403, {"detail": "Accès refusé."})
    assert await _owner_view(client, test_user, game_id) == before
    assert before[0] == 200 and before[2] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", TOOLTIP_ROUTES)
async def test_tooltips_unknown_game_is_not_found(client, test_user, method, path):
    method, url, kwargs = _request(method, path, "00000000-0000-0000-0000-000000000000")
    resp = await client.request(method, url, headers=auth_headers(test_user["token"]), **kwargs)

    assert (resp.status_code, resp.json()) == (404, {"detail": "Partie introuvable."})


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", TOOLTIP_ROUTES)
async def test_tooltips_owner_still_served(client, test_user, method, path):
    game_id = (await client.post("/api/games",
                                 headers=auth_headers(test_user["token"]))).json()["gameId"]

    method, url, kwargs = _request(method, path, game_id)
    resp = await client.request(method, url, headers=auth_headers(test_user["token"]), **kwargs)

    assert resp.status_code == 200
