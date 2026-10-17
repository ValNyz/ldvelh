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
    EXTRACTING = "extracting"
    DONE = "done"
    SAVED = "saved"
    ERROR = "error"
    WARNING = "warning"
    STATE = "state"
    ROLL_RESULT = "roll_result"
    ROLL_PENDING = "roll_pending"
    STATUS = "status"


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
    _task: asyncio.Task | None = None
    _done_queued: bool = False
    disconnected: bool = field(default=False, init=False)

    def __post_init__(self):
        logger.info(f"[SSE:{self._stream_id}] Stream créé")

    def attach(self, task: asyncio.Task) -> None:
        """Producer task to cancel if the client closes the stream early."""
        self._task = task

    async def send(self, event_type: SSEEvent, data: dict[str, Any]) -> None:
        """Envoie un événement dans la queue"""
        if self.disconnected:
            return  # Client gone: drop silently, the producer is being cancelled.
        if self._closed:
            logger.warning(
                f"[SSE:{self._stream_id}] Tentative d'envoi sur stream fermé"
            )
            return

        self._event_count += 1
        payload = {"type": event_type.value, **data}
        await self._queue.put(payload)
        if event_type is SSEEvent.DONE:
            self._done_queued = True  # The turn is committed: never cancel it from here on.

        # Log pour événements importants
        if event_type in (SSEEvent.DONE, SSEEvent.ERROR, SSEEvent.EXTRACTING):
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

    async def send_extracting(self, display_text: str | None) -> None:
        """
        Signale que le narratif est terminé et l'extraction en cours.
        Le client peut afficher le texte final et permettre la saisie.
        """
        await self.send(SSEEvent.EXTRACTING, {"displayText": display_text})

    async def send_done(
        self, display_text: str | None, state: dict | None = None
    ) -> None:
        """Envoie l'événement de fin avec le résultat"""
        await self.send(SSEEvent.DONE, {"displayText": display_text, "state": state})

    async def send_saved(self) -> None:
        """Confirme la sauvegarde"""
        await self.send(SSEEvent.SAVED, {})

    async def send_error(
        self,
        error: str,
        details: Any = None,
        recoverable: bool = False,
        code: str | None = None,
        ref: str | None = None,
    ) -> None:
        """Send an error; code and ref are only included when set."""
        logger.error(f"[SSE:{self._stream_id}] Erreur: {error}")
        data = {"error": error, "details": details, "recoverable": recoverable}
        if code is not None:
            data["code"] = code
        if ref is not None:
            data["ref"] = ref
        await self.send(SSEEvent.ERROR, data)

    async def send_warning(self, message: str, details: Any = None) -> None:
        """Envoie un avertissement"""
        logger.warning(f"[SSE:{self._stream_id}] Warning: {message}")
        await self.send(SSEEvent.WARNING, {"message": message, "details": details})

    async def send_roll_result(self, roll_data: dict) -> None:
        """Send a dice roll result to the frontend for display."""
        await self.send(SSEEvent.ROLL_RESULT, {"roll": roll_data})

    async def send_roll_pending(self, pending_data: dict) -> None:
        """Send a pending roll for Fate Core aspect invocation.

        Frontend should show the invocation modal and POST /chat
        with roll_id + invoked_aspects to resume.
        """
        await self.send(SSEEvent.ROLL_PENDING, pending_data)

    async def send_status(self, step: str, label: str | None = None) -> None:
        """Send a status update to the frontend (e.g., Director running)."""
        await self.send(SSEEvent.STATUS, {"step": step, "label": label or step})

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
        """Itère sur les événements pour le streaming.

        If the generator stops before the end-of-stream signal (client closed the
        connection), the attached producer task is cancelled.
        """
        logger.debug(f"[SSE:{self._stream_id}] Début de l'itération")
        finished = False
        cause = "client disconnected"
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=60.0,  # Timeout de 60s
                    )

                    if payload is None:  # Signal de fin
                        logger.debug(f"[SSE:{self._stream_id}] Signal de fin reçu")
                        finished = True
                        break

                    yield f"data: {json.dumps(payload)}\n\n"

                except TimeoutError:
                    # Envoie un keepalive
                    logger.debug(f"[SSE:{self._stream_id}] Keepalive envoyé")
                    yield ": keepalive\n\n"
                except Exception as e:
                    logger.error(f"[SSE:{self._stream_id}] Erreur iteration: {e}")
                    cause = f"server-side stream error ({type(e).__name__})"
                    break
        finally:
            if not finished:
                self._on_disconnect(cause)

    def _on_disconnect(self, cause: str) -> None:
        """Stream ended early: drop further events and cancel the turn unless DONE was queued."""
        self.disconnected = True
        if self._task is None or self._task.done():
            return
        if self._done_queued:
            logger.info(f"[SSE:{self._stream_id}] Stream ended ({cause}) after DONE, turn kept")
            return
        logger.warning(f"[SSE:{self._stream_id}] Stream ended ({cause}), cancelling the turn")
        self._task.cancel()


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
