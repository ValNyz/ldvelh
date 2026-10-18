"""HTTP answers for domain errors raised outside a chat stream."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from domain.errors import GameAccessDenied, GameNotFound
from utils.rate_limit import RateLimited

# Same status and body as the HTTPException the service used to raise.
_ANSWERS = {
    GameNotFound: (404, "Game not found"),
    GameAccessDenied: (403, "Access denied"),
}


async def _answer(request: Request, exc: Exception) -> JSONResponse:
    status, detail = _ANSWERS[type(exc)]
    return JSONResponse(status_code=status, content={"detail": detail})


async def _rate_limited(request: Request, exc: RateLimited) -> JSONResponse:
    """The usual { detail } 429 body, plus a code the clients can test (#82)."""
    return JSONResponse(status_code=exc.status_code, headers=exc.headers,
                        content={"detail": exc.detail, "code": exc.code})


_TYPE_MESSAGES = {
    "missing": "champ obligatoire",
    "string_too_short": "valeur trop courte",
    "string_too_long": "valeur trop longue",
    "uuid_parsing": "identifiant invalide",
    "uuid_type": "identifiant invalide",
    "enum": "valeur non reconnue",
    "dict_type": "objet attendu",
    "json_invalid": "JSON invalide",
}


def _field_problem(error: dict) -> str:
    """One French clause per error: field path and kind only, never the submitted value."""
    field = ".".join(str(p) for p in error["loc"] if p != "body") or "requête"
    if error["type"] == "value_error":
        # Our own validators raise French messages; strip pydantic's prefix.
        text = str(error.get("msg", "")).removeprefix("Value error, ")
    else:
        text = _TYPE_MESSAGES.get(error["type"], "valeur invalide")
    return f"{field} : {text}"


async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 with a French, non-leaky detail (pydantic's default body echoes the input)."""
    problems = "; ".join(_field_problem(e) for e in exc.errors()[:5])
    return JSONResponse(status_code=422, content={"detail": f"Requête invalide : {problems}."})


def register_domain_error_handlers(app: FastAPI) -> None:
    for error in _ANSWERS:
        app.add_exception_handler(error, _answer)
    app.add_exception_handler(RateLimited, _rate_limited)
    app.add_exception_handler(RequestValidationError, _invalid_request)
