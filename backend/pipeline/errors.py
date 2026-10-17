"""Any turn failure becomes one French TurnError, sent once on the sink (#45)."""

import logging

from pydantic import ValidationError

from domain.errors import TurnError
from pipeline.narration_stream import ProviderCallFailed
from pipeline.ports import EventSink

logger = logging.getLogger(__name__)


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
    if isinstance(exc, ValidationError):
        return TurnError("narration_invalid",
                         "La réponse du narrateur était inutilisable. Réessaie.")
    return TurnError(
        "internal",
        f"Erreur interne (réf. {ref}). Réessaie ; si ça persiste, signale cette référence.",
    )


async def report_error(sink: EventSink, exc: BaseException, *,
                       provider_name: str | None, ref: str) -> None:
    """Log the failure, then send exactly one error event (details stay None)."""
    error = to_turn_error(exc, provider_name, ref)
    if isinstance(exc, TurnError):
        logger.warning(f"[TURN:{ref}] {error.code}: {error.message}")
    else:
        logger.exception(f"[TURN:{ref}] {error.code}: {exc!r}", exc_info=exc)
    await sink.send_error(error.message, recoverable=error.recoverable, code=error.code, ref=ref)
