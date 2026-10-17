"""Every route that takes a game id answers 403/404 to a user who does not own the game (#81).

The route list is discovered from the FastAPI app: a new game-scoped route fails
`test_every_game_scoped_route_is_covered` until it is added to GAME_SCOPED_CALLS,
which then runs it through the second_user ownership check.
"""

import pytest

from helpers import auth_headers

pytestmark = pytest.mark.integration

GAME_ID_NAMES = {"game_id", "gameId"}
GAME = "<game_id>"  # replaced by the owner's game id in each request

# (method, path) -> httpx request kwargs, GAME standing for the game id.
GAME_SCOPED_CALLS = {
    ("GET", "/api/games/{game_id}"): {},
    ("DELETE", "/api/games/{game_id}"): {},
    ("PATCH", "/api/games/{game_id}"): {"json": {"gameId": GAME, "name": "Volée"}},
    ("GET", "/api/games/{game_id}/world"): {},
    ("POST", "/api/games/{game_id}/rollback"): {"json": {"fromIndex": 0}},
    ("POST", "/api/chat"): {"json": {"gameId": GAME, "message": "Salut"}},
    ("GET", "/api/tooltips/annotations"): {"params": {"gameId": GAME}},
    ("GET", "/api/tooltips/entity"): {
        "params": {"gameId": GAME, "name": "Rook", "entityType": "character"},
    },
}
TOOLTIP_ROUTES = [key for key in GAME_SCOPED_CALLS if key[1].startswith("/api/tooltips/")]


def _body_fields(schema, components) -> set[str]:
    """Top-level property names of a request body schema (follows $ref, anyOf/oneOf/allOf)."""
    if "$ref" in schema:
        schema = components[schema["$ref"].rsplit("/", 1)[-1]]
    names = set(schema.get("properties", {}))
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key, []):
            names |= _body_fields(sub, components)
    return names


def _game_scoped_routes() -> set[tuple[str, str]]:
    """(method, path) of every API operation reading a game id from path, query or JSON body.

    Read from the OpenAPI schema (public, follows included routers and dependencies);
    a route hidden with include_in_schema=False would escape it, so do not hide game routes.
    """
    from main import app

    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    scoped = set()
    for path, operations in spec["paths"].items():
        for method, op in operations.items():
            names = {param["name"] for param in op.get("parameters", [])}
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {})
            names |= _body_fields(body.get("schema", {}), components)
            if names & GAME_ID_NAMES:
                scoped.add((method.upper(), path))
    return scoped


def _request(method, path, game_id):
    def fill(value):
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return game_id if value == GAME else value

    kwargs = fill(GAME_SCOPED_CALLS[(method, path)])
    return method, path.replace("{game_id}", game_id), kwargs


def test_every_game_scoped_route_is_covered():
    """A route taking gameId/game_id must be listed here, hence checked for ownership below."""
    assert _game_scoped_routes() == set(GAME_SCOPED_CALLS)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", sorted(GAME_SCOPED_CALLS))
async def test_other_user_is_denied(client, test_user, second_user, method, path):
    game_id = (await client.post("/api/games",
                                 headers=auth_headers(test_user["token"]))).json()["gameId"]

    method, url, kwargs = _request(method, path, game_id)
    resp = await client.request(method, url, headers=auth_headers(second_user["token"]), **kwargs)

    assert (resp.status_code, resp.json()) == (403, {"detail": "Access denied"})


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", TOOLTIP_ROUTES)
async def test_tooltips_unknown_game_is_not_found(client, test_user, method, path):
    method, url, kwargs = _request(method, path, "00000000-0000-0000-0000-000000000000")
    resp = await client.request(method, url, headers=auth_headers(test_user["token"]), **kwargs)

    assert (resp.status_code, resp.json()) == (404, {"detail": "Game not found"})


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", TOOLTIP_ROUTES)
async def test_tooltips_owner_still_served(client, test_user, method, path):
    game_id = (await client.post("/api/games",
                                 headers=auth_headers(test_user["token"]))).json()["gameId"]

    method, url, kwargs = _request(method, path, game_id)
    resp = await client.request(method, url, headers=auth_headers(test_user["token"]), **kwargs)

    assert resp.status_code == 200
