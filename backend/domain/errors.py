"""Domain failures: turn errors shown to the player, game access errors."""


class TurnError(Exception):
    """A turn failure whose message can be shown to the player as is."""

    def __init__(self, code: str, message: str, recoverable: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable

    def __str__(self) -> str:
        return self.message


class GameNotFound(Exception):
    """No active game with this id (HTTP 404 at the API edge)."""


class GameAccessDenied(Exception):
    """The game belongs to another user (HTTP 403 at the API edge)."""
