"""
LDVELH - Extraction Service
Extraction des données narratives en arrière-plan
"""

from uuid import UUID

import asyncpg
from kg.specialized_populator import ExtractionPopulator
from prompts.extractor_prompt import (
    EXTRACTOR_SYSTEM_PROMPT,
    build_extractor_prompt,
    get_minimal_extraction,
    should_run_extraction,
)
from schema import NarrationHints, NarrativeExtraction
from services.llm_service import get_llm_service


class ExtractionService:
    """Service d'extraction des données narratives"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.llm = get_llm_service()

    async def extract_and_populate(
        self,
        game_id: UUID,
        narrative_text: str,
        hints: NarrationHints,
        cycle: int,
        location: str,
        npcs_present: list[str],
    ) -> dict:
        """
        Extrait les données du narratif et peuple le KG.
        Appelé en arrière-plan après la réponse au client.
        """
        # Vérifier si l'extraction est nécessaire
        if not should_run_extraction(hints):
            # Extraction minimale
            extraction_data = get_minimal_extraction(
                cycle, location, npcs_present, summary=narrative_text[:200] + "..."
            )
            return {"skipped": True, "reason": "no_hints"}

        try:
            # Récupérer les entités connues
            async with self.pool.acquire() as conn:
                known_entities = await conn.fetch(
                    """SELECT name FROM entities 
                       WHERE game_id = $1 AND removed_cycle IS NULL""",
                    game_id,
                )
                known_names = [r["name"] for r in known_entities]

            # Construire le prompt d'extraction
            user_prompt = build_extractor_prompt(
                narrative_text=narrative_text,
                hints=hints,
                current_cycle=cycle,
                current_location=location,
                npcs_present=npcs_present,
                known_entities=known_names,
            )

            # Appeler le LLM d'extraction
            extraction_data = await self.llm.extract_narrative(
                system_prompt=EXTRACTOR_SYSTEM_PROMPT,
                user_message=user_prompt,
            )

            if not extraction_data:
                return {"error": "extraction_failed"}

            # Valider avec Pydantic
            try:
                extraction = NarrativeExtraction.model_validate(extraction_data)
            except Exception as e:
                print(f"[EXTRACTION] Validation error: {e}")
                # Continuer avec les données brutes si possible
                extraction = None

            # Peupler le KG
            async with self.pool.acquire() as conn:
                populator = ExtractionPopulator(self.pool, game_id)
                await populator.load_registry(conn)

                if extraction:
                    stats = await populator.process_extraction(extraction)
                else:
                    # Traitement minimal avec les données brutes
                    stats = await self._process_raw_extraction(
                        populator, conn, extraction_data, cycle
                    )

            return {"success": True, "stats": stats}

        except Exception as e:
            print(f"[EXTRACTION] Error: {e}")
            return {"error": str(e)}

    async def _process_raw_extraction(
        self, populator: ExtractionPopulator, conn, data: dict, cycle: int
    ) -> dict:
        """Traite une extraction brute (non validée)"""
        stats = {
            "facts_created": 0,
            "entities_created": 0,
            "relations_created": 0,
            "errors": [],
        }

        # Traiter les faits
        for fact_data in data.get("facts", []):
            try:
                from schema import FactData

                fact = FactData.model_validate(fact_data)
                await populator.create_fact(conn, fact)
                stats["facts_created"] += 1
            except Exception as e:
                stats["errors"].append(f"fact: {e}")

        # Traiter le résumé
        if data.get("segment_summary"):
            await populator.save_cycle_summary(
                conn,
                cycle,
                summary=data["segment_summary"],
                key_events={"npcs": data.get("key_npcs_present", [])},
            )

        return stats


async def run_extraction_background(
    pool: asyncpg.Pool,
    game_id: UUID,
    narrative_text: str,
    hints: NarrationHints,
    cycle: int,
    location: str,
    npcs_present: list[str],
) -> None:
    """
    Lance l'extraction en arrière-plan.
    Fonction utilitaire pour être appelée avec asyncio.create_task()
    """
    try:
        service = ExtractionService(pool)
        result = await service.extract_and_populate(
            game_id=game_id,
            narrative_text=narrative_text,
            hints=hints,
            cycle=cycle,
            location=location,
            npcs_present=npcs_present,
        )
        print(f"[EXTRACTION] Background result: {result}")
    except Exception as e:
        print(f"[EXTRACTION] Background error: {e}")


async def run_summary_background(
    pool: asyncpg.Pool,
    game_id: UUID,
    message_id: UUID,
    narrative_text: str,
) -> None:
    """
    Génère et sauvegarde le résumé d'un message en arrière-plan.
    """
    try:
        llm = get_llm_service()
        summary = await llm.summarize_message(narrative_text)

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE chat_messages SET summary = $1 WHERE id = $2",
                summary,
                message_id,
            )

        print(f"[SUMMARY] Saved for message {message_id}: {summary[:50]}...")
    except Exception as e:
        print(f"[SUMMARY] Background error: {e}")
