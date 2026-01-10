"""
LDVELH - LLM Service
Gestion des appels à Claude
"""

from collections.abc import Awaitable, Callable

import anthropic
from schema.world_generation import WorldGeneration

from api.streaming import SSEWriter, build_display_text, extract_narrative_from_partial
from config import get_settings
from utils import parse_json_response


class LLMService:
    """Service pour les appels Claude"""

    def __init__(self):
        settings = get_settings()
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.settings = settings

    # =========================================================================
    # STREAMING NARRATEUR
    # =========================================================================

    async def stream_narration(
        self,
        system_prompt: str,
        user_message: str,
        sse_writer: SSEWriter,
        is_init_mode: bool = False,
        on_complete: Callable[[dict | None, str | None, str], Awaitable[None]]
        | None = None,
        on_narrative_ready: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """
        Stream une réponse narrative depuis Claude.

        Args:
            system_prompt: Prompt système
            user_message: Message utilisateur (contexte)
            sse_writer: Writer SSE pour le streaming
            is_init_mode: True si mode World Builder
            on_complete: Callback à la fin avec (parsed, display_text, raw_json)
            on_narrative_ready: Callback dès que le narrative_text est complet
        """
        settings = self.settings
        max_tokens = (
            settings.max_tokens_init if is_init_mode else settings.max_tokens_light
        )

        full_json = ""
        last_sent_length = 0
        last_progress_length = 0
        narrative_callback_fired = False

        try:
            async with self.client.messages.stream(
                model=settings.model_main,
                max_tokens=max_tokens,
                temperature=settings.temperature,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                async for event in stream:
                    if hasattr(event, "delta") and hasattr(event.delta, "text"):
                        full_json += event.delta.text

                        if is_init_mode:
                            if len(full_json) - last_progress_length > 500:
                                await sse_writer.send_progress(full_json)
                                last_progress_length = len(full_json)
                        else:
                            displayable = extract_narrative_from_partial(full_json)
                            if displayable and len(displayable) > last_sent_length:
                                delta = displayable[last_sent_length:]
                                await sse_writer.send_chunk(delta)
                                last_sent_length = len(displayable)

                                # Détecter la fin du narrative_text
                                # On cherche la fermeture du champ narrative_text
                                if (
                                    not narrative_callback_fired
                                    and on_narrative_ready
                                    and self._is_narrative_complete(full_json)
                                ):
                                    narrative_callback_fired = True
                                    await on_narrative_ready(displayable)

            if is_init_mode and len(full_json) > last_progress_length:
                await sse_writer.send_progress(full_json)

            parsed = parse_json_response(full_json)

            display_text = None
            if not is_init_mode and parsed:
                display_text = build_display_text(parsed)
            elif not is_init_mode:
                display_text = (
                    extract_narrative_from_partial(full_json) or "Erreur de génération."
                )

            if on_complete:
                await on_complete(parsed, display_text, full_json)

        except anthropic.APIError as e:
            print(f"[LLM] Erreur API: {e}")
            await sse_writer.send_error(
                f"Erreur API Claude: {e.message}", recoverable=True
            )
            raise
        except Exception as e:
            print(f"[LLM] Erreur: {e}")
            await sse_writer.send_error(str(e), recoverable=True)
            raise

    def _is_narrative_complete(self, partial_json: str) -> bool:
        """Détecte si le champ narrative_text est complet dans le JSON partiel"""
        # Cherche la fin du narrative_text (guillemet fermant suivi de virgule ou })
        import re

        # Pattern: "narrative_text": "..." suivi de , ou de fin d'objet
        pattern = r'"narrative_text"\s*:\s*"(?:[^"\\]|\\.)*"\s*[,}]'
        return bool(re.search(pattern, partial_json))

    # =========================================================================
    # EXTRACTION LÉGÈRE (Haiku)
    # =========================================================================

    async def extract_light(
        self,
        system_prompt: str,
        user_message: str,
    ) -> dict | None:
        """
        Extraction légère avec Haiku.
        Pour: résumé, état protagoniste, faits, relations, croyances.
        """
        try:
            response = await self.client.messages.create(
                model=self.settings.model_extraction_light,
                max_tokens=self.settings.max_tokens_extraction_light,
                temperature=self.settings.temperature_extraction,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            content = response.content[0].text
            return parse_json_response(content)

        except Exception as e:
            print(f"[LLM] Erreur extraction light: {e}")
            return None

    # =========================================================================
    # EXTRACTION LOURDE (Sonnet)
    # =========================================================================

    async def extract_heavy(
        self,
        system_prompt: str,
        user_message: str,
    ) -> dict | None:
        """
        Extraction lourde avec Sonnet.
        Pour: entités (avec arcs), engagements narratifs.
        """
        try:
            response = await self.client.messages.create(
                model=self.settings.model_extraction_heavy,
                max_tokens=self.settings.max_tokens_extraction_heavy,
                temperature=self.settings.temperature_extraction,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            content = response.content[0].text
            return parse_json_response(content)

        except Exception as e:
            print(f"[LLM] Erreur extraction heavy: {e}")
            return None

    # =========================================================================
    # LEGACY - Gardé pour compatibilité
    # =========================================================================

    async def extract_narrative(
        self,
        system_prompt: str,
        user_message: str,
    ) -> dict | None:
        """Legacy: utilise extract_heavy par défaut"""
        return await self.extract_heavy(system_prompt, user_message)

    async def summarize_message(
        self, narrative_text: str, max_length: int = 150
    ) -> str:
        """Génère un résumé court d'un message narratif"""
        try:
            response = await self.client.messages.create(
                model=self.settings.model_summary,
                max_tokens=self.settings.max_tokens_summary,
                temperature=0.3,
                messages=[
                    {
                        "role": "user",
                        "content": f"""Résume ce texte narratif en une phrase de {max_length} caractères maximum.
Garde l'essentiel: qui, quoi, où.

Texte:
{narrative_text[:2000]}

Résumé (une phrase):""",
                    }
                ],
            )

            return response.content[0].text.strip()[:max_length]

        except Exception as e:
            print(f"[LLM] Erreur résumé: {e}")
            return narrative_text[:max_length].rsplit(" ", 1)[0] + "..."

    async def generate_world(
        self,
        system_prompt: str,
        user_message: str,
    ) -> WorldGeneration | None:
        """Génère un monde complet (appel non-streaming)"""
        try:
            response = await self.client.messages.create(
                model=self.settings.model_main,
                max_tokens=self.settings.max_tokens_init,
                temperature=self.settings.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            content = response.content[0].text
            parsed = parse_json_response(content)

            if parsed:
                return WorldGeneration.model_validate(parsed)
            return None

        except Exception as e:
            print(f"[LLM] Erreur génération monde: {e}")
            return None


# Singleton
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Récupère l'instance du service LLM"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
