"""
LDVELH - SSE Streaming
Gestion du streaming Server-Sent Events
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


class SSEEvent(str, Enum):
    """Types d'événements SSE"""

    CHUNK = "chunk"
    PROGRESS = "progress"
    DONE = "done"
    SAVED = "saved"
    ERROR = "error"
    WARNING = "warning"
    STATE = "state"


@dataclass
class SSEWriter:
    """
    Gestionnaire d'écriture SSE avec queue async.
    Permet d'envoyer des événements depuis n'importe où.
    """

    _queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    _closed: bool = False
    _stream_id: str = field(default_factory=lambda: uuid4().hex[:8])
    _start_time: float = field(default_factory=time.perf_counter)
    _event_count: int = 0
    _bytes_sent: int = 0

    def __post_init__(self):
        logger.info(f"[SSE:{self._stream_id}] Stream créé")

    async def send(self, event_type: SSEEvent, data: dict[str, Any]) -> None:
        """Envoie un événement dans la queue"""
        if self._closed:
            logger.warning(
                f"[SSE:{self._stream_id}] Tentative d'envoi sur stream fermé"
            )
            return

        self._event_count += 1
        payload = {"type": event_type.value, **data}
        await self._queue.put(payload)

        # Log pour événements importants
        if event_type in (SSEEvent.DONE, SSEEvent.ERROR):
            elapsed = time.perf_counter() - self._start_time
            logger.info(
                f"[SSE:{self._stream_id}] {event_type.value.upper()} après {elapsed:.2f}s "
                f"({self._event_count} événements)"
            )

    async def send_chunk(self, content: str) -> None:
        """Envoie un chunk de texte narratif"""
        self._bytes_sent += len(content.encode("utf-8"))
        await self.send(SSEEvent.CHUNK, {"content": content})

    async def send_progress(self, raw_json: str) -> None:
        """Envoie la progression du JSON (mode init)"""
        self._bytes_sent += len(raw_json.encode("utf-8"))
        await self.send(SSEEvent.PROGRESS, {"rawJson": raw_json})

    async def send_done(
        self, display_text: str | None, state: dict | None = None
    ) -> None:
        """Envoie l'événement de fin avec le résultat"""
        await self.send(SSEEvent.DONE, {"displayText": display_text, "state": state})

    async def send_saved(self) -> None:
        """Confirme la sauvegarde"""
        await self.send(SSEEvent.SAVED, {})

    async def send_error(
        self, error: str, details: Any = None, recoverable: bool = False
    ) -> None:
        """Envoie une erreur"""
        logger.error(f"[SSE:{self._stream_id}] Erreur: {error}")
        await self.send(
            SSEEvent.ERROR,
            {"error": error, "details": details, "recoverable": recoverable},
        )

    async def send_warning(self, message: str, details: Any = None) -> None:
        """Envoie un avertissement"""
        logger.warning(f"[SSE:{self._stream_id}] Warning: {message}")
        await self.send(SSEEvent.WARNING, {"message": message, "details": details})

    async def close(self) -> None:
        """Ferme la queue"""
        if not self._closed:
            self._closed = True
            elapsed = time.perf_counter() - self._start_time
            logger.info(
                f"[SSE:{self._stream_id}] Stream fermé - "
                f"Durée: {elapsed:.2f}s | "
                f"Événements: {self._event_count} | "
                f"Données: {self._bytes_sent / 1024:.1f} KB"
            )
            await self._queue.put(None)  # Signal de fin

    async def iterate(self) -> AsyncGenerator[str, None]:
        """Itère sur les événements pour le streaming"""
        logger.debug(f"[SSE:{self._stream_id}] Début de l'itération")

        while True:
            try:
                payload = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=60.0,  # Timeout de 60s
                )

                if payload is None:  # Signal de fin
                    logger.debug(f"[SSE:{self._stream_id}] Signal de fin reçu")
                    break

                yield f"data: {json.dumps(payload)}\n\n"

            except TimeoutError:
                # Envoie un keepalive
                logger.debug(f"[SSE:{self._stream_id}] Keepalive envoyé")
                yield ": keepalive\n\n"
            except Exception as e:
                logger.error(f"[SSE:{self._stream_id}] Erreur iteration: {e}")
                break


def create_sse_response(writer: SSEWriter) -> StreamingResponse:
    """Crée une réponse SSE à partir d'un writer"""
    logger.debug(f"[SSE:{writer._stream_id}] Création de la réponse SSE")
    return StreamingResponse(
        writer.iterate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Désactive le buffering nginx
        },
    )


# =============================================================================
# DISPLAY BUILDER
# =============================================================================


def extract_narrative_from_partial(partial_json: str) -> str | None:
    """
    Extrait le texte narratif d'un JSON partiel en cours de streaming.
    Gère les cas où le JSON n'est pas encore complet.
    """
    # Cherche "narrative_text": "
    marker = '"narrative_text":'
    start = partial_json.find(marker)

    if start == -1:
        # Essayer avec narratif (ancien format)
        marker = '"narratif":'
        start = partial_json.find(marker)

    if start == -1:
        return None

    # Trouve le début de la string
    quote_start = partial_json.find('"', start + len(marker))
    if quote_start == -1:
        return None

    # Extrait jusqu'à la fin ou jusqu'au prochain guillemet non-échappé
    content = []
    i = quote_start + 1
    while i < len(partial_json):
        char = partial_json[i]

        if char == "\\" and i + 1 < len(partial_json):
            # Caractère échappé
            next_char = partial_json[i + 1]
            if next_char == "n":
                content.append("\n")
            elif next_char == '"':
                content.append('"')
            elif next_char == "\\":
                content.append("\\")
            else:
                content.append(next_char)
            i += 2
        elif char == '"':
            # Fin de la string
            break
        else:
            content.append(char)
            i += 1

    result = "".join(content).strip()
    return result if result else None


def build_display_text(parsed: dict) -> str:
    """
    Construit le texte d'affichage depuis une réponse parsée.
    Ajoute les choix suggérés.
    """
    text = parsed.get("narrative_text") or parsed.get("narratif") or ""

    # Ajouter les choix/suggestions
    choices = parsed.get("suggested_actions") or parsed.get("choix") or []
    if choices:
        text += "\n\n---\n\n**Actions possibles :**\n"
        for i, choice in enumerate(choices, 1):
            text += f"{i}. {choice}\n"

    return text.strip()
