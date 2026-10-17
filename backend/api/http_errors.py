"""HTTP answers for domain errors raised outside a chat stream."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from domain.errors import GameAccessDenied, GameNotFound

# Same status and body as the HTTPException the service used to raise.
_ANSWERS = {
    GameNotFound: (404, "Game not found"),
    GameAccessDenied: (403, "Access denied"),
}


async def _answer(request: Request, exc: Exception) -> JSONResponse:
    status, detail = _ANSWERS[type(exc)]
    return JSONResponse(status_code=status, content={"detail": detail})


def register_domain_error_handlers(app: FastAPI) -> None:
    for error in _ANSWERS:
        app.add_exception_handler(error, _answer)
