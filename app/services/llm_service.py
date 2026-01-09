"""
LDVELH - LLM Service
Gestion des appels à Claude
"""

import json
from collections.abc import Awaitable, Callable

import anthropic
from schema.world_generation import WorldGeneration

from api.streaming import SSEWriter, build_display_text, extract_narrative_from_partial
from config import get_settings


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
        on_complete: Callable[[dict | None, str | None, str], Awaitable[None]] | None = None,
    ) -> None:
        """
        Stream une réponse narrative depuis Claude.

        Args:
            system_prompt: Prompt système
            user_message: Message utilisateur (contexte)
            sse_writer: Writer SSE pour le streaming
            is_init_mode: True si mode World Builder (pas de streaming narratif)
            on_complete: Callback appelé à la fin avec (parsed, display_text, raw_json)
        """
        settings = self.settings
        max_tokens = settings.max_tokens_init if is_init_mode else settings.max_tokens_light

        full_json = ""
        last_sent_display = ""
        last_progress_length = 0

        try:
            async with self.client.messages.stream(
                model=settings.model_main,
                max_tokens=max_tokens,
                temperature=settings.temperature,
                system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                async for event in stream:
                    if hasattr(event, "delta") and hasattr(event.delta, "text"):
                        full_json += event.delta.text

                        if is_init_mode:
                            # Mode init: envoie le JSON brut périodiquement
                            if len(full_json) - last_progress_length > 500:
                                await sse_writer.send_progress(full_json)
                                last_progress_length = len(full_json)
                        else:
                            # Mode light: extrait et envoie le narratif
                            displayable = extract_narrative_from_partial(full_json)
                            if displayable and displayable != last_sent_display:
                                await sse_writer.send_chunk(displayable)
                                last_sent_display = displayable

            # Envoyer le reste en mode init
            if is_init_mode and len(full_json) > last_progress_length:
                await sse_writer.send_progress(full_json)

            # Parser le JSON final
            parsed = self._parse_json_response(full_json, is_init_mode)

            # Construire le texte d'affichage
            display_text = None
            if not is_init_mode and parsed:
                display_text = build_display_text(parsed)
            elif not is_init_mode:
                # Fallback: utiliser ce qu'on a extrait
                display_text = extract_narrative_from_partial(full_json) or "Erreur de génération."

            # Callback
            if on_complete:
                await on_complete(parsed, display_text, full_json)

        except anthropic.APIError as e:
            print(f"[LLM] Erreur API: {e}")
            await sse_writer.send_error(f"Erreur API Claude: {e.message}", recoverable=True)
            raise
        except Exception as e:
            print(f"[LLM] Erreur: {e}")
            await sse_writer.send_error(str(e), recoverable=True)
            raise

    # =========================================================================
    # EXTRACTION (Non-streaming)
    # =========================================================================

    async def extract_narrative(
        self,
        system_prompt: str,
        user_message: str,
    ) -> dict | None:
        """
        Extrait les données d'un texte narratif.
        Appel non-streaming pour l'extraction en background.
        """
        try:
            response = await self.client.messages.create(
                model=self.settings.model_extraction,
                max_tokens=self.settings.max_tokens_extraction,
                temperature=0.3,  # Moins créatif pour l'extraction
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            content = response.content[0].text
            return self._parse_json_response(content, is_init=False)

        except Exception as e:
            print(f"[LLM] Erreur extraction: {e}")
            return None

    # =========================================================================
    # RÉSUMÉ (Non-streaming)
    # =========================================================================

    async def summarize_message(self, narrative_text: str, max_length: int = 150) -> str:
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
            # Fallback: premiers mots du texte
            return narrative_text[:max_length].rsplit(" ", 1)[0] + "..."

    # =========================================================================
    # GÉNÉRATION MONDE (Non-streaming, pour tests)
    # =========================================================================

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
            parsed = self._parse_json_response(content, is_init=True)

            if parsed:
                return WorldGeneration.model_validate(parsed)
            return None

        except Exception as e:
            print(f"[LLM] Erreur génération monde: {e}")
            return None

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _parse_json_response(self, content: str, is_init: bool = False) -> dict | None:
        """Parse une réponse JSON de Claude"""
        # Nettoyer le contenu
        content = content.strip()

        # Retirer les backticks markdown si présents
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]

        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[LLM] Erreur parsing JSON: {e}")
            print(f"[LLM] Contenu (500 premiers chars): {content[:500]}")

            # Tenter de réparer le JSON tronqué
            return self._try_repair_json(content)

    def _try_repair_json(self, content: str) -> dict | None:
        """Tente de réparer un JSON tronqué"""
        # Essayer d'ajouter les fermetures manquantes
        brackets = []
        in_string = False
        escape = False

        for char in content:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char in "{[":
                brackets.append("}" if char == "{" else "]")
            elif char in "}]":
                if brackets and brackets[-1] == char:
                    brackets.pop()

        # Fermer les brackets ouverts
        repaired = content + "".join(reversed(brackets))

        try:
            return json.loads(repaired)
        except:
            return None


# Singleton
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Récupère l'instance du service LLM"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
