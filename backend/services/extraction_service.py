"""
LDVELH - Extraction Service
Extraction des données narratives en arrière-plan
"""

import logging
from uuid import UUID
import asyncpg
import asyncio
from dataclasses import dataclass, field

from kg.specialized_populator import ExtractionPopulator
from utils import normalize_narrative_extraction
from prompts.extractor_prompts import (
    SUMMARY_SYSTEM,
    build_summary_prompt,
    PROTAGONIST_STATE_SYSTEM,
    build_protagonist_state_prompt,
    ENTITIES_SYSTEM,
    build_entities_prompt,
    OBJECTS_SYSTEM,
    build_objects_prompt,
    FACTS_SYSTEM,
    build_facts_prompt,
    RELATIONS_SYSTEM,
    build_relations_prompt,
    BELIEFS_SYSTEM,
    build_beliefs_prompt,
    COMMITMENTS_SYSTEM,
    build_commitments_prompt,
    should_run_extraction,
    extract_object_hints,
)
from schema import NarrationHints, NarrativeExtraction
from services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Résultat agrégé de toutes les extractions"""

    segment_summary: str = ""
    facts: list = field(default_factory=list)
    entities_created: list = field(default_factory=list)
    entities_updated: list = field(default_factory=list)
    objects_created: list = field(default_factory=list)
    relations_created: list = field(default_factory=list)
    relations_updated: list = field(default_factory=list)
    gauge_changes: list = field(default_factory=list)
    credit_transactions: list = field(default_factory=list)
    inventory_changes: list = field(default_factory=list)
    beliefs_updated: list = field(default_factory=list)
    commitments_created: list = field(default_factory=list)
    commitments_resolved: list = field(default_factory=list)
    events_scheduled: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "segment_summary": self.segment_summary,
            "facts": self.facts,
            "entities_created": self.entities_created,
            "entities_updated": self.entities_updated,
            "objects_created": self.objects_created,
            "relations_created": self.relations_created,
            "relations_updated": self.relations_updated,
            "gauge_changes": self.gauge_changes,
            "credit_transactions": self.credit_transactions,
            "inventory_changes": self.inventory_changes,
            "beliefs_updated": self.beliefs_updated,
            "commitments_created": self.commitments_created,
            "commitments_resolved": self.commitments_resolved,
            "events_scheduled": self.events_scheduled,
        }

    def merge(self, partial: dict) -> None:
        """Fusionne un résultat partiel"""
        for key, value in partial.items():
            if hasattr(self, key):
                if isinstance(value, list):
                    getattr(self, key).extend(value)
                elif isinstance(value, str) and value:
                    setattr(self, key, value)


class ParallelExtractionService:
    """Service d'extraction parallèle des données narratives"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.llm = get_llm_service()

    # =========================================================================
    # EXTRACTEURS INDIVIDUELS
    # =========================================================================

    async def extract_summary(self, narrative_text: str) -> dict:
        """Extracteur résumé (Haiku)"""
        result = await self.llm.extract_light(
            system_prompt=SUMMARY_SYSTEM,
            user_message=build_summary_prompt(narrative_text),
        )
        return result or {"segment_summary": ""}

    async def extract_protagonist_state(
        self, narrative_text: str, known_objects: list[str] | None = None
    ) -> dict:
        """Extracteur état protagoniste (Haiku)"""
        result = await self.llm.extract_light(
            system_prompt=PROTAGONIST_STATE_SYSTEM,
            user_message=build_protagonist_state_prompt(narrative_text, known_objects),
        )
        return result or {
            "gauge_changes": [],
            "credit_transactions": [],
            "inventory_changes": [],
        }

    async def extract_entities(
        self,
        narrative_text: str,
        new_entities_hints: list[str],
        known_entities: list[str],
    ) -> dict:
        """Extracteur entités (Sonnet)"""
        result = await self.llm.extract_heavy(
            system_prompt=ENTITIES_SYSTEM,
            user_message=build_entities_prompt(
                narrative_text, new_entities_hints, known_entities
            ),
        )
        return result or {"entities_created": [], "entities_updated": []}

    async def extract_objects(
        self,
        narrative_text: str,
        object_hints: list[str],
    ) -> dict:
        """Extracteur objets acquis (Sonnet)"""
        if not object_hints:
            return {"objects_created": []}

        result = await self.llm.extract_heavy(
            system_prompt=OBJECTS_SYSTEM,
            user_message=build_objects_prompt(narrative_text, object_hints),
        )
        return result or {"objects_created": []}

    async def extract_facts(
        self,
        narrative_text: str,
        cycle: int,
        location: str,
        known_entities: list[str],
    ) -> dict:
        """Extracteur faits (Haiku)"""
        result = await self.llm.extract_light(
            system_prompt=FACTS_SYSTEM,
            user_message=build_facts_prompt(
                narrative_text, cycle, location, known_entities
            ),
        )
        return result or {"facts": []}

    async def extract_relations(
        self,
        narrative_text: str,
        cycle: int,
        known_entities: list[str],
    ) -> dict:
        """Extracteur relations (Haiku)"""
        result = await self.llm.extract_light(
            system_prompt=RELATIONS_SYSTEM,
            user_message=build_relations_prompt(narrative_text, cycle, known_entities),
        )
        return result or {"relations_created": [], "relations_updated": []}

    async def extract_beliefs(
        self,
        narrative_text: str,
        known_entities: list[str],
    ) -> dict:
        """Extracteur croyances (Haiku)"""
        result = await self.llm.extract_light(
            system_prompt=BELIEFS_SYSTEM,
            user_message=build_beliefs_prompt(narrative_text, known_entities),
        )
        return result or {"beliefs_updated": []}

    async def extract_commitments(
        self,
        narrative_text: str,
        known_entities: list[str],
        commitment_hints: list[str] | None = None,
    ) -> dict:
        """Extracteur engagements & événements (Sonnet)"""
        result = await self.llm.extract_heavy(
            system_prompt=COMMITMENTS_SYSTEM,
            user_message=build_commitments_prompt(
                narrative_text, known_entities, commitment_hints
            ),
        )
        return result or {
            "commitments_created": [],
            "commitments_resolved": [],
            "events_scheduled": [],
        }

    # =========================================================================
    # ORCHESTRATION PARALLÈLE
    # =========================================================================

    async def extract_all(
        self,
        game_id: UUID,
        narrative_text: str,
        hints: NarrationHints,
        cycle: int,
        location: str,
        npcs_present: list[str],
        summary_task: asyncio.Task | None = None,
    ) -> ExtractionResult:
        """
        Lance toutes les extractions nécessaires en parallèle.

        Flow:
        - Phase 1: Résumé, État protagoniste, Entités (parallèle)
        - Phase 2: Objets, Faits, Relations, Croyances, Engagements (parallèle)

        Args:
            summary_task: Tâche de résumé déjà lancée (optionnel)
        """
        result = ExtractionResult()

        # Si pas besoin d'extraction
        if not should_run_extraction(hints):
            if summary_task:
                summary_result = await summary_task
                result.merge(summary_result)
            return result

        # Récupérer les entités et objets connus
        async with self.pool.acquire() as conn:
            known_rows = await conn.fetch(
                """SELECT name, type FROM entities 
                   WHERE game_id = $1 AND removed_cycle IS NULL""",
                game_id,
            )
            known_entities = [r["name"] for r in known_rows]
            known_objects = [r["name"] for r in known_rows if r["type"] == "object"]

        # =====================================================================
        # PHASE 1: Extracteurs indépendants (parallèle)
        # =====================================================================
        phase1_tasks = {}

        # Résumé: utiliser la tâche existante ou en créer une
        if summary_task:
            phase1_tasks["summary"] = summary_task
        else:
            phase1_tasks["summary"] = asyncio.create_task(
                self.extract_summary(narrative_text)
            )

        # État protagoniste (si hint)
        if hints.protagonist_state_changed:
            phase1_tasks["protagonist"] = asyncio.create_task(
                self.extract_protagonist_state(narrative_text, known_objects)
            )

        # Entités (si hint)
        if hints.new_entities_mentioned:
            phase1_tasks["entities"] = asyncio.create_task(
                self.extract_entities(
                    narrative_text,
                    hints.new_entities_mentioned,
                    known_entities,
                )
            )

        # Attendre phase 1
        phase1_results = await asyncio.gather(
            *phase1_tasks.values(),
            return_exceptions=True,
        )

        # Merger les résultats de phase 1
        for key, res in zip(phase1_tasks.keys(), phase1_results):
            if isinstance(res, Exception):
                print(f"[EXTRACTION] Erreur {key}: {res}")
            elif res:
                result.merge(res)

        # Enrichir les entités connues avec les nouvelles
        new_entity_names = [e["name"] for e in result.entities_created]
        all_known = known_entities + new_entity_names

        # Extraire les hints d'objets à créer
        object_hints = extract_object_hints(result.inventory_changes)

        # =====================================================================
        # PHASE 2: Tous en parallèle (y compris Objets)
        # =====================================================================
        phase2_tasks = {}

        # Objets (si hints d'acquisition)
        if object_hints:
            phase2_tasks["objects"] = asyncio.create_task(
                self.extract_objects(narrative_text, object_hints)
            )

        # Faits (toujours)
        phase2_tasks["facts"] = asyncio.create_task(
            self.extract_facts(narrative_text, cycle, location, all_known)
        )

        # Relations (si hint)
        if hints.relationships_changed:
            phase2_tasks["relations"] = asyncio.create_task(
                self.extract_relations(narrative_text, cycle, all_known)
            )

        # Croyances (si hint)
        if hints.information_learned:
            phase2_tasks["beliefs"] = asyncio.create_task(
                self.extract_beliefs(narrative_text, all_known)
            )

        # Engagements (si hints)
        if (
            hints.new_commitment_created
            or hints.commitment_advanced
            or hints.commitment_resolved
            or hints.event_scheduled
        ):
            commitment_hints = (hints.commitment_advanced or []) + (
                hints.commitment_resolved or []
            )
            phase2_tasks["commitments"] = asyncio.create_task(
                self.extract_commitments(narrative_text, all_known, commitment_hints)
            )

        # Attendre phase 2
        if phase2_tasks:
            phase2_results = await asyncio.gather(
                *phase2_tasks.values(),
                return_exceptions=True,
            )

            for key, res in zip(phase2_tasks.keys(), phase2_results):
                if isinstance(res, Exception):
                    print(f"[EXTRACTION] Erreur {key}: {res}")
                elif res:
                    result.merge(res)

        return result

    # =========================================================================
    # POINT D'ENTRÉE PRINCIPAL
    # =========================================================================

    async def extract_and_populate(
        self,
        game_id: UUID,
        narrative_text: str,
        hints: NarrationHints,
        cycle: int,
        location: str,
        npcs_present: list[str],
        summary_task: asyncio.Task | None = None,
    ) -> dict:
        """
        Extrait les données et peuple le KG.
        Version principale à appeler depuis routes.py
        """
        try:
            # Lancer l'extraction parallèle
            extraction_result = await self.extract_all(
                game_id=game_id,
                narrative_text=narrative_text,
                hints=hints,
                cycle=cycle,
                location=location,
                npcs_present=npcs_present,
                summary_task=summary_task,
            )

            # Normaliser et valider
            extraction_data = normalize_narrative_extraction(
                extraction_result.to_dict()
            )

            # Ajouter cycle et location
            extraction_data["cycle"] = cycle
            extraction_data["current_location_ref"] = location

            try:
                extraction = NarrativeExtraction.model_validate(extraction_data)
            except Exception as e:
                print(f"[EXTRACTION] Validation error: {e}")
                extraction = None

            # Peupler le KG
            async with self.pool.acquire() as conn:
                populator = ExtractionPopulator(self.pool, game_id)
                await populator.load_registry(conn)

                if extraction:
                    stats = await populator.process_extraction(extraction)
                else:
                    stats = await self._process_raw_extraction(
                        populator, conn, extraction_data, cycle
                    )

            return {"success": True, "stats": stats}

        except Exception as e:
            print(f"[EXTRACTION] Error: {e}")
            import traceback

            traceback.print_exc()
            return {"error": str(e)}

    async def _process_raw_extraction(
        self, populator: ExtractionPopulator, conn, data: dict, cycle: int
    ) -> dict:
        """Traite une extraction brute (non validée)"""
        stats = {
            "facts_created": 0,
            "entities_created": 0,
            "objects_created": 0,
            "relations_created": 0,
            "errors": [],
        }

        for fact_data in data.get("facts", []):
            try:
                from schema import FactData

                fact = FactData.model_validate(fact_data)
                await populator.create_fact(conn, fact)
                stats["facts_created"] += 1
            except Exception as e:
                stats["errors"].append(f"fact: {e}")

        if data.get("segment_summary"):
            await populator.save_cycle_summary(
                conn,
                cycle,
                summary=data["segment_summary"],
                key_events={},
            )

        return stats


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================


def create_summary_task(
    pool: asyncpg.Pool,
    narrative_text: str,
) -> asyncio.Task:
    """
    Crée une tâche de résumé à lancer immédiatement.
    À appeler dès que narrative_text est disponible.
    """
    service = ParallelExtractionService(pool)
    return asyncio.create_task(service.extract_summary(narrative_text))


async def run_parallel_extraction(
    pool: asyncpg.Pool,
    game_id: UUID,
    narrative_text: str,
    hints: NarrationHints,
    cycle: int,
    location: str,
    npcs_present: list[str],
    summary_task: asyncio.Task | None = None,
) -> dict:
    """
    Lance l'extraction parallèle complète.
    Fonction utilitaire pour routes.py
    """
    service = ParallelExtractionService(pool)
    return await service.extract_and_populate(
        game_id=game_id,
        narrative_text=narrative_text,
        hints=hints,
        cycle=cycle,
        location=location,
        npcs_present=npcs_present,
        summary_task=summary_task,
    )
