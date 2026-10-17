"""Any turn failure becomes one French TurnError, sent once on the sink (#45)."""

import logging
from collections.abc import Awaitable
from typing import TypeVar

from pydantic import ValidationError

from config import get_settings
from domain.errors import TurnError
from pipeline.narration_stream import ProviderCallFailed
from pipeline.ports import EventSink
from schema.narration import NARRATION_INVALID_MESSAGE, NarrationInvalid
from utils.log_safe import has_validation_error, log_exception

logger = logging.getLogger(__name__)

T = TypeVar("T")

SAVED_DISPLAY_FAILED = ("Ton action est enregistrée, mais l'affichage a échoué. "
                        "Recharge la partie.")
WORLD_SAVED_DISPLAY_FAILED = ("Ton monde est enregistré, mais l'affichage a échoué. "
                              "Recharge la partie.")


def saved_display_failed(*, world: bool = False) -> TurnError:
    """Failure after the save: never retryable, worded for the world or for an action (#80)."""
    message = WORLD_SAVED_DISPLAY_FAILED if world else SAVED_DISPLAY_FAILED
    return TurnError("saved_display_failed", message, recoverable=False)


async def finish_saved(step: Awaitable[T], *, ref: str, world: bool = False) -> T:
    """Run what follows a save: any failure there is reported as saved, never retryable.

    A retryable message would make the player resend an action already saved (played twice).
    Not logged here: `report_error` logs the TurnError with its cause (or, when the caller is
    gone, `finish_despite_cancel` does), so each failure is logged exactly once.
    """
    try:
        return await step
    except Exception as exc:
        raise saved_display_failed(world=world) from exc


def internal_error(ref: str) -> TurnError:
    """The generic player-facing error: no internal detail, only the reference to report."""
    return TurnError(
        "internal",
        f"Erreur interne (réf. {ref}). Réessaie ; si ça persiste, signale cette référence.",
    )


def _provider_error(exc: ProviderCallFailed, provider_name: str | None) -> TurnError:
    provider = exc.provider or provider_name or "le fournisseur"
    status = getattr(exc.__cause__, "status_code", None)
    if status in (401, 403):
        return TurnError(
            "provider_auth",
            f"Clé API refusée par {provider}. Vérifie-la dans Paramètres > Modèle IA.",
            recoverable=False,
        )
    if status == 429:
        return TurnError(
            "provider_rate_limit",
            f"{provider} limite les requêtes pour le moment. Réessaie dans un instant.",
        )
    return TurnError("provider_error", f"{provider} n'a pas répondu correctement. Réessaie.")


def to_turn_error(exc: BaseException, provider_name: str | None, ref: str) -> TurnError:
    """Translate an exception into a player-facing error; unknown text is never shown."""
    if isinstance(exc, TurnError):
        return exc
    if isinstance(exc, ProviderCallFailed):
        return _provider_error(exc, provider_name)
    if isinstance(exc, (ValidationError, NarrationInvalid)):
        return TurnError("narration_invalid", NARRATION_INVALID_MESSAGE)
    return internal_error(ref)


async def report_error(sink: EventSink, exc: BaseException, *,
                       provider_name: str | None, ref: str) -> None:
    """Log the failure, then send exactly one error event (details stay None)."""
    error = to_turn_error(exc, provider_name, ref)
    detail = get_settings().log_prompts
    if isinstance(exc, TurnError):
        # A chained cause (e.g. a ValidationError) keeps its traceback in the log.
        level = logging.ERROR if error.code == "saved_display_failed" else logging.WARNING
        message = f"[TURN:{ref}] {error.code}: {error.message}"
        if exc.__cause__:
            log_exception(logger, level, message, exc, debug_detail=detail)
        else:
            logger.log(level, message)
    else:
        # log_exception appends the redacted cause chain itself when it holds a ValidationError.
        shown = type(exc).__name__ if has_validation_error(exc) else repr(exc)
        log_exception(logger, logging.ERROR, f"[TURN:{ref}] {error.code}: {shown}", exc,
                      debug_detail=detail)
    await sink.send_error(error.message, recoverable=error.recoverable, code=error.code, ref=ref)
