"""
LDVELH - LLM Output Normalizer
Normalise les sorties LLM avant validation Pydantic.
Corrige les synonymes, anglicismes et erreurs courantes.
"""

from typing import Any
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# SYNONYMES POUR LES VALEURS D'ENUM
# =============================================================================

RELATION_TYPE_SYNONYMS = {
    # Erreurs courantes
    "headquarters_of": "located_in",
    "based_at": "located_in",
    "based_in": "located_in",
    "hq_of": "located_in",
    "home_of": "located_in",
    # Anglais → valeur canonique
    "knows": "knows",
    "friend_of": "friend_of",
    "friends_with": "friend_of",
    "friendly_with": "friend_of",
    "enemy_of": "enemy_of",
    "enemies_with": "enemy_of",
    "hostile_to": "enemy_of",
    "family_of": "family_of",
    "related_to": "family_of",
    "family_member": "family_of",
    "romantic": "romantic",
    "dating": "romantic",
    "in_relationship": "romantic",
    "romantically_involved": "romantic",
    "partner_of": "romantic",
    "employed_by": "employed_by",
    "works_for": "employed_by",
    "employee_of": "employed_by",
    "hired_by": "employed_by",
    "colleague_of": "colleague_of",
    "coworker": "colleague_of",
    "works_with": "colleague_of",
    "manages": "manages",
    "manager_of": "manages",
    "supervises": "manages",
    "boss_of": "manages",
    "frequents": "frequents",
    "visits_often": "frequents",
    "regular_at": "frequents",
    "lives_at": "lives_at",
    "resides_at": "lives_at",
    "residence": "lives_at",
    "home": "lives_at",
    "located_in": "located_in",
    "inside": "located_in",
    "part_of": "located_in",
    "contained_in": "located_in",
    "within": "located_in",
    "works_at": "works_at",
    "workplace": "works_at",
    "employed_at": "works_at",
    "owns": "owns",
    "possesses": "owns",
    "has": "owns",
    "owner_of": "owns",
    "owes_to": "owes_to",
    "indebted_to": "owes_to",
    "owes": "owes_to",
}

CERTAINTY_SYNONYMS = {
    # Erreurs courantes
    "likely": "probable",
    "probably": "probable",
    "maybe": "uncertain",
    "possibly": "uncertain",
    "confirmed": "certain",
    "definitely": "certain",
    "unknown": "uncertain",
    "unsure": "uncertain",
    "heard": "rumor",
    "supposedly": "rumor",
    "allegedly": "rumor",
    # Valeurs canoniques
    "certain": "certain",
    "probable": "probable",
    "rumor": "rumor",
    "uncertain": "uncertain",
}

ENTITY_TYPE_SYNONYMS = {
    # Anglais
    "character": "character",
    "npc": "character",
    "person": "character",
    "personnage": "character",
    "pnj": "character",
    "location": "location",
    "place": "location",
    "lieu": "location",
    "area": "location",
    "room": "location",
    "object": "object",
    "item": "object",
    "objet": "object",
    "thing": "object",
    "organization": "organization",
    "organisation": "organization",
    "org": "organization",
    "company": "organization",
    "faction": "organization",
    "group": "organization",
    "protagonist": "protagonist",
    "player": "protagonist",
    "hero": "protagonist",
    "main_character": "protagonist",
    "ai": "ai",
    "ia": "ai",
    "artificial_intelligence": "ai",
    "assistant": "ai",
    "companion_ai": "ai",
}

FACT_TYPE_SYNONYMS = {
    "action": "action",
    "act": "action",
    "deed": "action",
    "dialogue": "dialogue",
    "dialog": "dialogue",
    "conversation": "dialogue",
    "speech": "dialogue",
    "talk": "dialogue",
    "discovery": "discovery",
    "found": "discovery",
    "learned": "discovery",
    "revelation": "discovery",
    "incident": "incident",
    "event": "incident",
    "occurrence": "incident",
    "happening": "incident",
    "encounter": "encounter",
    "meeting": "encounter",
    "met": "encounter",
    "ran_into": "encounter",
}

FACT_DOMAIN_SYNONYMS = {
    "personal": "personal",
    "private": "personal",
    "self": "personal",
    "professional": "professional",
    "work": "professional",
    "job": "professional",
    "career": "professional",
    "romantic": "romantic",
    "love": "romantic",
    "relationship": "romantic",
    "dating": "romantic",
    "social": "social",
    "friendship": "social",
    "community": "social",
    "exploration": "exploration",
    "discovery": "exploration",
    "adventure": "exploration",
    "financial": "financial",
    "money": "financial",
    "economic": "financial",
    "transaction": "financial",
    "other": "other",
    "misc": "other",
    "general": "other",
}

COMMITMENT_TYPE_SYNONYMS = {
    "foreshadowing": "foreshadowing",
    "hint": "foreshadowing",
    "clue": "foreshadowing",
    "teaser": "foreshadowing",
    "secret": "secret",
    "hidden": "secret",
    "concealed": "secret",
    "setup": "setup",
    "preparation": "setup",
    "groundwork": "setup",
    "chekhov_gun": "chekhov_gun",
    "chekhov": "chekhov_gun",
    "planted_element": "chekhov_gun",
    "arc": "arc",
    "storyline": "arc",
    "narrative_arc": "arc",
    "story_arc": "arc",
    "quest": "arc",
}

ARC_DOMAIN_SYNONYMS = {
    "professional": "professional",
    "work": "professional",
    "career": "professional",
    "job": "professional",
    "personal": "personal",
    "self": "personal",
    "growth": "personal",
    "romantic": "romantic",
    "love": "romantic",
    "romance": "romantic",
    "social": "social",
    "friendship": "social",
    "friends": "social",
    "community": "social",
    "family": "family",
    "familial": "family",
    "relatives": "family",
    "financial": "financial",
    "money": "financial",
    "wealth": "financial",
    "health": "health",
    "medical": "health",
    "wellness": "health",
    "existential": "existential",
    "philosophical": "existential",
    "meaning": "existential",
    "purpose": "existential",
}

MOMENT_SYNONYMS = {
    "night": "night",
    "midnight": "night",
    "nighttime": "night",
    "dawn": "dawn",
    "sunrise": "dawn",
    "daybreak": "dawn",
    "early_morning": "dawn",
    "morning": "morning",
    "am": "morning",
    "forenoon": "morning",
    "midday": "midday",
    "noon": "midday",
    "lunchtime": "midday",
    "afternoon": "afternoon",
    "pm": "afternoon",
    "evening": "evening",
    "dusk": "evening",
    "sunset": "evening",
    "nightfall": "evening",
    "late_night": "late_night",
    "late": "late_night",
}

DEPARTURE_REASON_SYNONYMS = {
    "flight": "flight",
    "escape": "flight",
    "fleeing": "flight",
    "running_away": "flight",
    "breakup": "breakup",
    "break_up": "breakup",
    "divorce": "breakup",
    "separation": "breakup",
    "opportunity": "opportunity",
    "job_offer": "opportunity",
    "career": "opportunity",
    "promotion": "opportunity",
    "fresh_start": "fresh_start",
    "new_beginning": "fresh_start",
    "restart": "fresh_start",
    "new_life": "fresh_start",
    "standard": "standard",
    "normal": "standard",
    "regular": "standard",
    "relocation": "standard",
    "broke": "broke",
    "bankrupt": "broke",
    "poverty": "broke",
    "debt": "broke",
    "other": "other",
    "unknown": "other",
    "misc": "other",
}

PARTICIPANT_ROLE_SYNONYMS = {
    "actor": "actor",
    "doer": "actor",
    "agent": "actor",
    "subject": "actor",
    "witness": "witness",
    "observer": "witness",
    "watcher": "witness",
    "bystander": "witness",
    "target": "target",
    "recipient": "target",
    "object": "target",
    "victim": "target",
    "mentioned": "mentioned",
    "referenced": "mentioned",
    "talked_about": "mentioned",
}


# =============================================================================
# SYNONYMES POUR LES CLÉS (noms de champs)
# =============================================================================

KEY_SYNONYMS = {
    # Relations
    "relation_type": "relation_type",
    "type_relation": "relation_type",
    "relationship": "relation_type",
    "rel_type": "relation_type",
    # Certitude
    "certainty": "certainty",
    "certitude": "certainty",
    "confidence": "certainty",
    "level": "certainty",
    # Entités
    "entity_type": "entity_type",
    "type_entite": "entity_type",
    "ent_type": "entity_type",
    # Références
    "source_ref": "source_ref",
    "source": "source_ref",
    "from": "source_ref",
    "from_ref": "source_ref",
    "target_ref": "target_ref",
    "target": "target_ref",
    "to": "target_ref",
    "to_ref": "target_ref",
    # Lieux
    "arrival_location_ref": "arrival_location_ref",
    "arrival_location": "arrival_location_ref",
    "location": "arrival_location_ref",
    "location_ref": "location_ref",
    "lieu": "location_ref",
    "place_ref": "location_ref",
    # Temps
    "arrival_date": "arrival_date",
    "date": "arrival_date",
    "starting_date": "arrival_date",
    "time_of_day": "time_of_day",
    "moment": "time_of_day",
    "time": "time_of_day",
    # Personnages
    "station_arrival_cycle": "station_arrival_cycle",
    "arrival_cycle": "station_arrival_cycle",
    "arrived_cycle": "station_arrival_cycle",
    # Arcs
    "arc_type": "arc_type",
    "type_arc": "arc_type",
    "commitment_type": "arc_type",
    "arc_domain": "domain",
    "domain": "domain",
    "domaine": "domain",
}


# =============================================================================
# FONCTIONS DE NORMALISATION
# =============================================================================


def normalize_value(value: Any, synonyms: dict[str, str]) -> Any:
    """Normalise une valeur selon la table de synonymes."""
    if value is None:
        return None
    key = str(value).lower().strip().replace(" ", "_").replace("-", "_")
    return synonyms.get(key, value)


def normalize_key(key: str) -> str:
    """Normalise une clé de champ."""
    key_lower = key.lower().strip()
    return KEY_SYNONYMS.get(key_lower, key)


def normalize_dict_keys(data: dict) -> dict:
    """Normalise toutes les clés d'un dictionnaire."""
    if not isinstance(data, dict):
        return data
    return {normalize_key(k): v for k, v in data.items()}


def normalize_relation(relation: dict) -> dict:
    """Normalise une relation complète."""
    if not isinstance(relation, dict):
        return relation

    result = dict(relation)

    # Normaliser relation_type
    if "relation_type" in result:
        old_val = result["relation_type"]
        new_val = normalize_value(old_val, RELATION_TYPE_SYNONYMS)
        if old_val != new_val:
            logger.info(f"[Normalizer] relation_type: '{old_val}' → '{new_val}'")
        result["relation_type"] = new_val

    # Normaliser certainty
    if "certainty" in result:
        old_val = result["certainty"]
        new_val = normalize_value(old_val, CERTAINTY_SYNONYMS)
        if old_val != new_val:
            logger.info(f"[Normalizer] certainty: '{old_val}' → '{new_val}'")
        result["certainty"] = new_val

    return result


def normalize_entity(entity: dict) -> dict:
    """Normalise une entité."""
    if not isinstance(entity, dict):
        return entity

    result = dict(entity)

    # Normaliser entity_type / type
    for key in ["entity_type", "type"]:
        if key in result:
            old_val = result[key]
            new_val = normalize_value(old_val, ENTITY_TYPE_SYNONYMS)
            if old_val != new_val:
                logger.info(f"[Normalizer] {key}: '{old_val}' → '{new_val}'")
            result[key] = new_val

    return result


def normalize_fact(fact: dict) -> dict:
    """Normalise un fait."""
    if not isinstance(fact, dict):
        return fact

    result = dict(fact)

    if "fact_type" in result or "type" in result:
        key = "fact_type" if "fact_type" in result else "type"
        old_val = result[key]
        new_val = normalize_value(old_val, FACT_TYPE_SYNONYMS)
        if old_val != new_val:
            logger.info(f"[Normalizer] fact type: '{old_val}' → '{new_val}'")
        result[key] = new_val

    if "domain" in result:
        old_val = result["domain"]
        new_val = normalize_value(old_val, FACT_DOMAIN_SYNONYMS)
        if old_val != new_val:
            logger.info(f"[Normalizer] fact domain: '{old_val}' → '{new_val}'")
        result["domain"] = new_val

    # Normaliser les rôles des participants
    if "participants" in result and isinstance(result["participants"], list):
        for participant in result["participants"]:
            if isinstance(participant, dict) and "role" in participant:
                old_val = participant["role"]
                new_val = normalize_value(old_val, PARTICIPANT_ROLE_SYNONYMS)
                if old_val != new_val:
                    logger.info(
                        f"[Normalizer] participant role: '{old_val}' → '{new_val}'"
                    )
                participant["role"] = new_val

    return result


def normalize_arc(arc: dict) -> dict:
    """Normalise un arc narratif."""
    if not isinstance(arc, dict):
        return arc

    result = dict(arc)

    if "arc_type" in result or "type" in result:
        key = "arc_type" if "arc_type" in result else "type"
        old_val = result[key]
        new_val = normalize_value(old_val, COMMITMENT_TYPE_SYNONYMS)
        if old_val != new_val:
            logger.info(f"[Normalizer] arc type: '{old_val}' → '{new_val}'")
        result[key] = new_val

    if "domain" in result:
        old_val = result["domain"]
        new_val = normalize_value(old_val, ARC_DOMAIN_SYNONYMS)
        if old_val != new_val:
            logger.info(f"[Normalizer] arc domain: '{old_val}' → '{new_val}'")
        result["domain"] = new_val

    return result


def normalize_arrival_event(event: dict) -> dict:
    """Normalise un événement d'arrivée."""
    if not isinstance(event, dict):
        return event

    result = dict(event)

    if "time_of_day" in result:
        old_val = result["time_of_day"]
        new_val = normalize_value(old_val, MOMENT_SYNONYMS)
        if old_val != new_val:
            logger.info(f"[Normalizer] time_of_day: '{old_val}' → '{new_val}'")
        result["time_of_day"] = new_val

    return result


def normalize_character(character: dict) -> dict:
    """Normalise un personnage avec ses arcs."""
    if not isinstance(character, dict):
        return character

    result = dict(character)

    # Normaliser les arcs du personnage
    if "arcs" in result and isinstance(result["arcs"], list):
        result["arcs"] = [normalize_arc(arc) for arc in result["arcs"]]

    return result


# =============================================================================
# NORMALISATION GLOBALE - WORLD GENERATION
# =============================================================================


def normalize_world_generation(data: dict) -> dict:
    """
    Normalise une sortie WorldGeneration complète.
    À appeler AVANT WorldGeneration.model_validate(data).
    """
    if not isinstance(data, dict):
        return data

    result = dict(data)
    corrections = []

    # Normaliser protagonist
    if "protagonist" in result and isinstance(result["protagonist"], dict):
        if "departure_reason" in result["protagonist"]:
            old = result["protagonist"]["departure_reason"]
            new = normalize_value(old, DEPARTURE_REASON_SYNONYMS)
            if old != new:
                corrections.append(f"protagonist.departure_reason: '{old}' → '{new}'")
            result["protagonist"]["departure_reason"] = new

    # Normaliser characters
    if "characters" in result and isinstance(result["characters"], list):
        result["characters"] = [normalize_character(c) for c in result["characters"]]

    # Normaliser narrative_arcs
    if "narrative_arcs" in result and isinstance(result["narrative_arcs"], list):
        result["narrative_arcs"] = [
            normalize_arc(arc) for arc in result["narrative_arcs"]
        ]

    # Normaliser initial_relations
    if "initial_relations" in result and isinstance(result["initial_relations"], list):
        result["initial_relations"] = [
            normalize_relation(rel) for rel in result["initial_relations"]
        ]

    # Normaliser arrival_event
    if "arrival_event" in result:
        result["arrival_event"] = normalize_arrival_event(result["arrival_event"])

    if corrections:
        logger.info(f"[Normalizer] WorldGeneration corrections: {len(corrections)}")
        for c in corrections:
            logger.debug(f"  - {c}")

    return result


# =============================================================================
# NORMALISATION GLOBALE - NARRATION OUTPUT
# =============================================================================


def normalize_narration_output(data: dict) -> dict:
    """
    Normalise une sortie NarrationOutput.
    À appeler AVANT NarrationOutput.model_validate(data).
    """
    if not isinstance(data, dict):
        return data

    result = dict(data)

    # Normaliser hints si présent
    if "hints" in result and isinstance(result["hints"], dict):
        # Les hints n'ont pas d'enums à normaliser actuellement
        pass

    return result


# =============================================================================
# NORMALISATION GLOBALE - NARRATIVE EXTRACTION
# =============================================================================


def normalize_narrative_extraction(data: dict) -> dict:
    """
    Normalise une sortie NarrativeExtraction.
    À appeler AVANT NarrativeExtraction.model_validate(data).
    """
    if not isinstance(data, dict):
        return data

    result = dict(data)

    # Normaliser facts
    if "facts" in result and isinstance(result["facts"], list):
        result["facts"] = [normalize_fact(f) for f in result["facts"]]

    # Normaliser entities_created
    if "entities_created" in result and isinstance(result["entities_created"], list):
        result["entities_created"] = [
            normalize_entity(e) for e in result["entities_created"]
        ]

    # Normaliser relations_created
    if "relations_created" in result and isinstance(result["relations_created"], list):
        for item in result["relations_created"]:
            if isinstance(item, dict) and "relation" in item:
                item["relation"] = normalize_relation(item["relation"])

    # Normaliser relations_updated
    if "relations_updated" in result and isinstance(result["relations_updated"], list):
        result["relations_updated"] = [
            normalize_relation(r) for r in result["relations_updated"]
        ]

    # Normaliser relations_ended
    if "relations_ended" in result and isinstance(result["relations_ended"], list):
        for rel in result["relations_ended"]:
            if isinstance(rel, dict) and "relation_type" in rel:
                old = rel["relation_type"]
                rel["relation_type"] = normalize_value(old, RELATION_TYPE_SYNONYMS)

    # Normaliser commitments_created
    if "commitments_created" in result and isinstance(
        result["commitments_created"], list
    ):
        for commit in result["commitments_created"]:
            if isinstance(commit, dict) and "commitment_type" in commit:
                old = commit["commitment_type"]
                commit["commitment_type"] = normalize_value(
                    old, COMMITMENT_TYPE_SYNONYMS
                )

    # Normaliser beliefs_updated
    if "beliefs_updated" in result and isinstance(result["beliefs_updated"], list):
        for belief in result["beliefs_updated"]:
            if isinstance(belief, dict) and "certainty" in belief:
                old = belief["certainty"]
                belief["certainty"] = normalize_value(old, CERTAINTY_SYNONYMS)

    return result
