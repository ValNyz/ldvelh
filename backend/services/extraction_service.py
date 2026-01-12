"""
LDVELH - Extraction Service
Extraction des données narratives en arrière-plan
Utilise kg/reader.py et kg/populator.py pour l'accès BDD
"""

import time
import logging
from uuid import UUID
import asyncpg
import asyncio
from dataclasses import dataclass, field

from kg.reader import KnowledgeGraphReader
from kg.specialized_populator import ExtractionPopulator
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

    def log_details(self) -> None:
        """Log les détails de l'extraction"""
        if self.segment_summary:
            logger.info(f"  📝 Résumé: {self.segment_summary[:100]}...")

        if self.gauge_changes:
            for g in self.gauge_changes:
                gauge = g.get("gauge", "?")
                delta = g.get("delta", 0)
                sign = "+" if delta > 0 else ""
                logger.info(f"  📊 Jauge: {gauge} {sign}{delta}")

        if self.credit_transactions:
            for tx in self.credit_transactions:
                amount = tx.get("amount", 0)
                sign = "+" if amount > 0 else ""
                logger.info(f"  💰 Crédits: {sign}{amount}")

        if self.inventory_changes:
            for inv in self.inventory_changes:
                action = inv.get("action", "?")
                obj = inv.get("object_ref") or inv.get("object_hint", "?")[:40]
                logger.info(f"  🎒 Inventaire: {action} → {obj}")

        if self.entities_created:
            for e in self.entities_created:
                etype = e.get("entity_type", "?")
                name = e.get("name", "?")
                logger.info(f"  ✨ Entité créée: [{etype}] {name}")

        if self.objects_created:
            for o in self.objects_created:
                name = o.get("name", "?")
                cat = o.get("category", "?")
                logger.info(f"  📦 Objet créé: {name} ({cat})")

        if self.relations_created:
            for r in self.relations_created:
                rel = r.get("relation", {})
                src = rel.get("source_ref", "?")
                tgt = rel.get("target_ref", "?")
                rtype = rel.get("relation_type", "?")
                logger.info(f"  🔗 Relation: {src} --[{rtype}]--> {tgt}")

        if self.facts:
            for f in self.facts:
                ftype = f.get("fact_type", "?")
                importance = f.get("importance", "?")
                logger.info(f"  📌 Fait [{ftype}] (imp={importance})")

        if self.commitments_created:
            for c in self.commitments_created:
                ctype = c.get("commitment_type", "?")
                logger.info(f"  🎯 Engagement [{ctype}]")

        if self.events_scheduled:
            for ev in self.events_scheduled:
                title = ev.get("title", "?")
                cycle = ev.get("planned_cycle", "?")
                logger.info(f"  📅 Événement: {title} (cycle {cycle})")


class ParallelExtractionService:
    """Service d'extraction parallèle des données narratives"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.llm = get_llm_service()

    def _get_reader(self, game_id: UUID) -> KnowledgeGraphReader:
        """Crée un reader pour une partie"""
        return KnowledgeGraphReader(self.pool, game_id)

    # =========================================================================
    # EXTRACTEURS INDIVIDUELS (LLM - inchangés)
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
    # CHARGEMENT CONTEXTE (via reader)
    # =========================================================================

    async def _load_known_entities(
        self, conn, game_id: UUID
    ) -> tuple[list[str], list[str]]:
        """
        Charge les entités et objets connus.
        Retourne (known_entities, known_objects)
        """
        reader = self._get_reader(game_id)
        entities = await reader.get_entities(conn)

        known_entities = [e["name"] for e in entities]
        known_objects = [e["name"] for e in entities if e["type"] == "object"]

        return known_entities, known_objects

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
        - Phase 2: Objets, Faits, Relations, Engagements (parallèle)

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

        # Récupérer les entités et objets connus via reader
        async with self.pool.acquire() as conn:
            known_entities, known_objects = await self._load_known_entities(
                conn, game_id
            )

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
        t0 = time.perf_counter()
        phase1_results = await asyncio.gather(
            *phase1_tasks.values(),
            return_exceptions=True,
        )
        t1 = time.perf_counter()
        logger.debug(f"[EXTRACTION] Phase 1 terminée en {t1 - t0:.2f}s")

        # Merger les résultats de phase 1
        for key, res in zip(phase1_tasks.keys(), phase1_results):
            if isinstance(res, Exception):
                logger.error(f"[EXTRACTION] Erreur {key}: {res}")
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
        phase2_names = {}

        # Objets (si hints d'acquisition)
        if object_hints:
            phase2_tasks["objects"] = asyncio.create_task(
                self.extract_objects(narrative_text, object_hints)
            )
            phase2_names["objects"] = f"Objets ({len(object_hints)})"

        # Faits (toujours)
        phase2_tasks["facts"] = asyncio.create_task(
            self.extract_facts(narrative_text, cycle, location, all_known)
        )
        phase2_names["facts"] = "Faits"

        # Relations (si hint)
        if hints.relationships_changed:
            phase2_tasks["relations"] = asyncio.create_task(
                self.extract_relations(narrative_text, cycle, all_known)
            )
            phase2_names["relations"] = "Relations"

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
            phase2_names["commitments"] = "Engagements"

        logger.info(f"[EXTRACTION] Phase 2: {list(phase2_names.values())}")

        # Attendre phase 2
        if phase2_tasks:
            t0 = time.perf_counter()
            phase2_results = await asyncio.gather(
                *phase2_tasks.values(),
                return_exceptions=True,
            )

            t1 = time.perf_counter()
            logger.debug(f"[EXTRACTION] Phase 2 terminée en {t1 - t0:.2f}s")

            for key, res in zip(phase2_tasks.keys(), phase2_results):
                if isinstance(res, Exception):
                    logger.error(f"[EXTRACTION] Erreur {key}: {res}")
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

            # Log détaillé
            logger.debug(f"[EXTRACTION] Détails cycle {cycle}:")
            extraction_result.log_details()

            # Normaliser et valider
            extraction_data = extraction_result.to_dict()

            # Ajouter cycle et location au niveau racine
            extraction_data["cycle"] = cycle
            extraction_data["current_location_ref"] = location
            extraction_data["key_npcs_present"] = npcs_present

            # Ajouter cycle à chaque fait (le LLM ne le génère pas)
            for fact in extraction_data.get("facts", []):
                if "cycle" not in fact:
                    fact["cycle"] = cycle

            # Ajouter cycle à chaque relation_created
            for rel in extraction_data.get("relations_created", []):
                if "cycle" not in rel:
                    rel["cycle"] = cycle

            try:
                extraction = NarrativeExtraction.model_validate(extraction_data)
            except Exception as e:
                logger.warning(f"[EXTRACTION] Validation error: {e}")
                extraction = None

            # Peupler le KG via ExtractionPopulator
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
            logger.error(f"[EXTRACTION] Error: {e}")
            import traceback

            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def _process_raw_extraction(
        self, populator: ExtractionPopulator, conn, data: dict, cycle: int
    ) -> dict:
        """Traite une extraction brute (non validée par Pydantic)"""
        stats = {
            "facts_created": 0,
            "entities_created": 0,
            "objects_created": 0,
            "relations_created": 0,
            "gauges_changed": 0,
            "credits_changed": 0,
            "errors": [],
        }

        # Traiter les faits
        for fact_data in data.get("facts", []):
            try:
                from schema import FactData

                if "cycle" not in fact_data:
                    fact_data["cycle"] = cycle

                fact = FactData.model_validate(fact_data)
                result = await populator.create_fact(conn, fact)
                if result:
                    stats["facts_created"] += 1
            except Exception as e:
                stats["errors"].append(f"fact: {e}")

        # Traiter les changements de jauges
        for gauge_data in data.get("gauge_changes", []):
            try:
                gauge = gauge_data.get("gauge")
                delta = gauge_data.get("delta", 0)
                if gauge and delta:
                    success, _, _ = await populator.update_gauge(
                        conn, gauge, delta, cycle
                    )
                    if success:
                        stats["gauges_changed"] += 1
            except Exception as e:
                stats["errors"].append(f"gauge: {e}")

        # Traiter les transactions de crédits
        for tx_data in data.get("credit_transactions", []):
            try:
                amount = tx_data.get("amount", 0)
                description = tx_data.get("description", "")
                if amount:
                    success, _, error = await populator.credit_transaction(
                        conn, amount, cycle, description
                    )
                    if success:
                        stats["credits_changed"] += 1
                    elif error:
                        stats["errors"].append(f"credits: {error}")
            except Exception as e:
                stats["errors"].append(f"credits: {e}")

        # Traiter les entités créées
        for entity_data in data.get("entities_created", []):
            try:
                from schema import EntityCreation

                entity = EntityCreation.model_validate(entity_data)
                await populator._process_entity_creation(conn, entity, cycle)
                stats["entities_created"] += 1
            except Exception as e:
                stats["errors"].append(f"entity: {e}")

        # Traiter les objets créés
        for obj_data in data.get("objects_created", []):
            try:
                from schema import ObjectCreation

                obj = ObjectCreation.model_validate(obj_data)
                await populator._process_object_creation(conn, obj, cycle)
                stats["objects_created"] += 1
            except Exception as e:
                stats["errors"].append(f"object: {e}")

        # Traiter les relations créées
        for rel_data in data.get("relations_created", []):
            try:
                from schema import RelationData

                relation_dict = rel_data.get("relation", rel_data)
                rel_cycle = rel_data.get("cycle", cycle)

                relation = RelationData.model_validate(relation_dict)
                result = await populator.create_relation(conn, relation, rel_cycle)
                if result:
                    stats["relations_created"] += 1
            except Exception as e:
                stats["errors"].append(f"relation: {e}")

        # Sauvegarder le résumé du cycle
        if data.get("segment_summary"):
            await populator.save_cycle_summary(
                conn,
                cycle,
                summary=data["segment_summary"],
                key_events={"npcs_present": data.get("key_npcs_present", [])},
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
