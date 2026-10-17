"""HTTP answers for domain errors raised outside a chat stream."""

from fastapi import FastAPI, Request
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


def register_domain_error_handlers(app: FastAPI) -> None:
    for error in _ANSWERS:
        app.add_exception_handler(error, _answer)
    app.add_exception_handler(RateLimited, _rate_limited)
