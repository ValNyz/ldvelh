"""Any turn failure becomes one French TurnError, sent once on the sink (#45)."""

import logging
from collections.abc import Awaitable

from pydantic import ValidationError

from domain.errors import TurnError
from pipeline.narration_stream import ProviderCallFailed
from pipeline.ports import EventSink
from schema.narration import NARRATION_INVALID_MESSAGE, NarrationInvalid

logger = logging.getLogger(__name__)

SAVED_DISPLAY_FAILED = ("Ton action est enregistrée, mais l'affichage a échoué. "
                        "Recharge la partie.")


async def finish_saved(step: Awaitable[None], *, ref: str) -> None:
    """Run what follows a save: any failure there is reported as saved, never retryable.

    A retryable message would make the player resend an action already saved (played twice).
    """
    try:
        await step
    except Exception as exc:
        logger.error(f"[TURN:{ref}] Saved, but the post-save step failed", exc_info=exc)
        raise TurnError("saved_display_failed", SAVED_DISPLAY_FAILED,
                        recoverable=False) from exc


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
    return TurnError(
        "internal",
        f"Erreur interne (réf. {ref}). Réessaie ; si ça persiste, signale cette référence.",
    )


async def report_error(sink: EventSink, exc: BaseException, *,
                       provider_name: str | None, ref: str) -> None:
    """Log the failure, then send exactly one error event (details stay None)."""
    error = to_turn_error(exc, provider_name, ref)
    if isinstance(exc, TurnError):
        # A chained cause (e.g. a ValidationError) keeps its traceback in the log.
        logger.warning(f"[TURN:{ref}] {error.code}: {error.message}",
                       exc_info=exc if exc.__cause__ else None)
    else:
        logger.exception(f"[TURN:{ref}] {error.code}: {exc!r}", exc_info=exc)
    await sink.send_error(error.message, recoverable=error.recoverable, code=error.code, ref=ref)
