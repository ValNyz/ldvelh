"""Turn failure shown to the player: a stable code and a French message."""


class TurnError(Exception):
    """A turn failure whose message can be shown to the player as is."""

    def __init__(self, code: str, message: str, recoverable: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable

    def __str__(self) -> str:
        return self.message
