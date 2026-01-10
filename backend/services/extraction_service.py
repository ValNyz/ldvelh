"""
LDVELH - Extraction Service
Extraction des données narratives en arrière-plan
"""

import logging
import time
from uuid import UUID

import asyncpg
from kg.specialized_populator import ExtractionPopulator
from utils import normalize_narrative_extraction
from prompts.extractor_prompt import (
    EXTRACTOR_SYSTEM_PROMPT,
    build_extractor_prompt,
    get_minimal_extraction,
    should_run_extraction,
)
from schema import NarrationHints, NarrativeExtraction
from services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


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
        total_start = time.perf_counter()
        game_id_short = str(game_id)[:8]

        logger.info(
            f"[EXTRACT:{game_id_short}] Démarrage cycle={cycle} location={location}"
        )
        logger.debug(f"[EXTRACT:{game_id_short}] Hints: {hints}")

        # Vérifier si l'extraction est nécessaire
        if not should_run_extraction(hints):
            elapsed = (time.perf_counter() - total_start) * 1000
            logger.info(f"[EXTRACT:{game_id_short}] SKIP (no hints) - {elapsed:.0f}ms")
            extraction_data = get_minimal_extraction(
                cycle, location, npcs_present, summary=narrative_text[:200] + "..."
            )
            return {"skipped": True, "reason": "no_hints", "latency_ms": elapsed}

        try:
            # Récupérer les entités connues
            step_start = time.perf_counter()
            async with self.pool.acquire() as conn:
                known_entities = await conn.fetch(
                    """SELECT name FROM entities 
                       WHERE game_id = $1 AND removed_cycle IS NULL""",
                    game_id,
                )
                known_names = [r["name"] for r in known_entities]
            db_latency = (time.perf_counter() - step_start) * 1000
            logger.debug(
                f"[EXTRACT:{game_id_short}] DB fetch entities: {db_latency:.0f}ms ({len(known_names)} entities)"
            )

            # Construire le prompt d'extraction
            user_prompt = build_extractor_prompt(
                narrative_text=narrative_text,
                hints=hints,
                current_cycle=cycle,
                current_location=location,
                npcs_present=npcs_present,
                known_entities=known_names,
            )
            logger.debug(
                f"[EXTRACT:{game_id_short}] Prompt length: {len(user_prompt)} chars"
            )

            # Appeler le LLM d'extraction
            step_start = time.perf_counter()
            extraction_data = await self.llm.extract_narrative(
                system_prompt=EXTRACTOR_SYSTEM_PROMPT,
                user_message=user_prompt,
            )
            llm_latency = (time.perf_counter() - step_start) * 1000
            logger.info(f"[EXTRACT:{game_id_short}] LLM call: {llm_latency:.0f}ms")

            if not extraction_data:
                total_elapsed = (time.perf_counter() - total_start) * 1000
                logger.error(
                    f"[EXTRACT:{game_id_short}] FAILED (no data) - {total_elapsed:.0f}ms"
                )
                return {"error": "extraction_failed", "latency_ms": total_elapsed}

            # Normaliser AVANT validation Pydantic
            step_start = time.perf_counter()
            extraction_data = normalize_narrative_extraction(extraction_data)

            # Valider avec Pydantic
            extraction = None
            try:
                extraction = NarrativeExtraction.model_validate(extraction_data)
                validation_latency = (time.perf_counter() - step_start) * 1000
                logger.debug(
                    f"[EXTRACT:{game_id_short}] Validation: {validation_latency:.0f}ms"
                )
            except Exception as e:
                validation_latency = (time.perf_counter() - step_start) * 1000
                logger.warning(
                    f"[EXTRACT:{game_id_short}] Validation error ({validation_latency:.0f}ms): {e}"
                )

            # Peupler le KG
            step_start = time.perf_counter()
            async with self.pool.acquire() as conn:
                populator = ExtractionPopulator(self.pool, game_id)
                await populator.load_registry(conn)

                if extraction:
                    stats = await populator.process_extraction(extraction)
                else:
                    stats = await self._process_raw_extraction(
                        populator, conn, extraction_data, cycle
                    )
            kg_latency = (time.perf_counter() - step_start) * 1000

            total_elapsed = (time.perf_counter() - total_start) * 1000

            # Log final avec stats
            logger.info(
                f"[EXTRACT:{game_id_short}] SUCCESS - "
                f"Total: {total_elapsed:.0f}ms | "
                f"LLM: {llm_latency:.0f}ms | "
                f"KG: {kg_latency:.0f}ms | "
                f"Facts: {stats.get('facts_created', 0)} | "
                f"Entities: {stats.get('entities_created', 0)} | "
                f"Relations: {stats.get('relations_created', 0)}"
            )

            if stats.get("errors"):
                logger.warning(f"[EXTRACT:{game_id_short}] Errors: {stats['errors']}")

            return {
                "success": True,
                "stats": stats,
                "latency_ms": {
                    "total": total_elapsed,
                    "llm": llm_latency,
                    "kg": kg_latency,
                },
            }

        except Exception as e:
            total_elapsed = (time.perf_counter() - total_start) * 1000
            logger.error(
                f"[EXTRACT:{game_id_short}] ERROR ({total_elapsed:.0f}ms): {e}",
                exc_info=True,
            )
            return {"error": str(e), "latency_ms": total_elapsed}

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
    game_id_short = str(game_id)[:8]
    logger.info(f"[EXTRACT:{game_id_short}] Background task started")

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

        if result.get("success"):
            latency = result.get("latency_ms", {})
            logger.info(
                f"[EXTRACT:{game_id_short}] Background completed - "
                f"Total: {latency.get('total', 0):.0f}ms"
            )
        elif result.get("skipped"):
            logger.info(
                f"[EXTRACT:{game_id_short}] Background skipped: {result.get('reason')}"
            )
        else:
            logger.error(
                f"[EXTRACT:{game_id_short}] Background failed: {result.get('error')}"
            )

    except Exception as e:
        logger.error(
            f"[EXTRACT:{game_id_short}] Background exception: {e}", exc_info=True
        )


async def run_summary_background(
    pool: asyncpg.Pool,
    game_id: UUID,
    message_id: UUID,
    narrative_text: str,
) -> None:
    """
    Génère et sauvegarde le résumé d'un message en arrière-plan.
    """
    start = time.perf_counter()
    msg_id_short = str(message_id)[:8]

    try:
        llm = get_llm_service()
        summary = await llm.summarize_message(narrative_text)
        llm_latency = (time.perf_counter() - start) * 1000

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE chat_messages SET summary = $1 WHERE id = $2",
                summary,
                message_id,
            )

        total_latency = (time.perf_counter() - start) * 1000
        logger.info(
            f"[SUMMARY:{msg_id_short}] Saved - "
            f"LLM: {llm_latency:.0f}ms | Total: {total_latency:.0f}ms | "
            f"Preview: {summary[:50]}..."
        )
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error(f"[SUMMARY:{msg_id_short}] Error ({elapsed:.0f}ms): {e}")
