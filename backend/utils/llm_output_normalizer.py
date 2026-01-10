"""
LDVELH - LLM Output Normalizer
Normalise les sorties LLM avant validation Pydantic.
Corrige les synonymes, anglicismes et erreurs courantes.
"""

from typing import Any
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# LIMITES DES CHAMPS (depuis les schémas Pydantic)
# =============================================================================

FIELD_MAX_LENGTHS = {
    "suggested_action": 150,
    "entityref": 100,
    "scene_mood": 50,
    "narrator_notes": 300,
    # WorldGeneration
    "tone_notes": 300,
    # WorldData
    "world.description": 500,
    "world.atmosphere": 50,
    "world.name": 100,
    "world.station_type": 50,
    # ProtagonistData
    "protagonist.departure_story": 400,
    "protagonist.backstory": 600,
    "protagonist.personality_traits": 100,  # par item
    "protagonist.skills": 100,  # par item
    # PersonalAIData
    "personal_ai.quirk": 200,
    "personal_ai.personality": 200,
    "personal_ai.speech_pattern": 150,
    # CharacterData
    "character.pronouns": 20,
    "character.species": 50,
    "character.gender": 30,
    "character.physical_description": 300,
    "character.personality": 300,
    "character.backstory": 500,
    "character.secret": 300,
    # LocationData
    "location.description": 400,
    "location.atmosphere": 150,
    # OrganizationData
    "organization.description": 400,
    # ObjectData
    "object.description": 200,
    # NarrativeArcData
    "arc.description": 300,
    "arc.hook": 200,
    # ArrivalEventData
    "arrival_event.initial_mood": 80,
    "arrival_event.immediate_need": 200,
    "arrival_event.optional_incident": 300,
}

LIST_MAX_LENGTHS = {
    "characters": 8,
    "locations": 10,
    "organizations": 5,
    "inventory": 15,
    "narrative_arcs": 10,
    "initial_relations": 30,  # Généreux pour éviter de perdre des relations importantes
    "immediate_sensory_details": 6,
    "suggested_action": 5,
}


# =============================================================================
# FONCTIONS DE TRONCATURE
# =============================================================================


def truncate_string(value: str, max_length: int, field_name: str = "") -> str:
    """Tronque une string si nécessaire."""
    if not isinstance(value, str):
        return value
    if len(value) <= max_length:
        return value

    truncated = value[: max_length - 3].rsplit(" ", 1)[0] + "..."
    logger.warning(
        f"[Normalizer] Troncature {field_name}: {len(value)} → {len(truncated)} chars"
    )
    return truncated


def truncate_list(items: list, max_length: int, field_name: str = "") -> list:
    """Tronque une liste si nécessaire."""
    if not isinstance(items, list):
        return items
    if len(items) <= max_length:
        return items

    logger.warning(
        f"[Normalizer] Troncature {field_name}: {len(items)} → {max_length} items"
    )
    return items[:max_length]


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
    "reports_to": "employed_by",
    "member_of": "employed_by",
    "employed_by": "employed_by",
    "works_for": "employed_by",
    "employee_of": "employed_by",
    "hired_by": "employed_by",
    "partner_with": "colleague_of",
    "works_alongside": "colleague_of",
    "collaborates_with": "colleague_of",  # Collabore avec → collègue
    "colleague_of": "colleague_of",
    "coworker": "colleague_of",
    "works_with": "colleague_of",
    "leads": "manages",  # Dirige → manages
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
    "assigned_to": "works_at",  # Assigné à un lieu/poste
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
    "environment": "existential",
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
    "time_of_day": "hour",
    "moment": "hour",
    "time": "hour",
    "hour": "hour",
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


def normalize_value(value: Any, synonyms: dict[str, str], field_name: str = "") -> Any:
    """Normalise une valeur enum avec fallback."""
    if value is None:
        return None
    key = str(value).lower().strip().replace(" ", "_").replace("-", "_")
    result = synonyms.get(key)

    if result is None:
        # Fallback: prendre la première valeur valide
        valid_values = list(set(synonyms.values()))
        result = valid_values[0] if valid_values else value
        logger.warning(
            f"[Normalizer] Valeur inconnue {field_name}='{value}' → fallback '{result}'"
        )
    elif key != result:
        logger.info(f"[Normalizer] {field_name}: '{value}' → '{result}'")

    return result


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

        # Tronquer les champs texte
    if "description" in result:
        result["description"] = truncate_string(
            result["description"],
            FIELD_MAX_LENGTHS["arc.description"],
            "arc.description",
        )
    if "hook" in result:
        result["hook"] = truncate_string(
            result["hook"], FIELD_MAX_LENGTHS["arc.hook"], "arc.hook"
        )

    return result


def normalize_location(loc: dict) -> dict:
    """Normalise un lieu."""
    if not isinstance(loc, dict):
        return loc

    result = dict(loc)

    if "description" in result:
        result["description"] = truncate_string(
            result["description"],
            FIELD_MAX_LENGTHS["location.description"],
            "location.description",
        )
    if "atmosphere" in result:
        result["atmosphere"] = truncate_string(
            result["atmosphere"],
            FIELD_MAX_LENGTHS["location.atmosphere"],
            "location.atmosphere",
        )

    return result


def normalize_arrival_event(event: dict) -> dict:
    """Normalise un événement d'arrivée."""
    if not isinstance(event, dict):
        return event

    result = dict(event)

    # Tronquer
    if "initial_mood" in result:
        result["initial_mood"] = truncate_string(
            result["initial_mood"],
            FIELD_MAX_LENGTHS["arrival_event.initial_mood"],
            "arrival_event.initial_mood",
        )
    if "immediate_need" in result:
        result["immediate_need"] = truncate_string(
            result["immediate_need"],
            FIELD_MAX_LENGTHS["arrival_event.immediate_need"],
            "arrival_event.immediate_need",
        )
    if "optional_incident" in result:
        result["optional_incident"] = truncate_string(
            result["optional_incident"],
            FIELD_MAX_LENGTHS["arrival_event.optional_incident"],
            "arrival_event.optional_incident",
        )
    if "immediate_sensory_details" in result:
        result["immediate_sensory_details"] = truncate_list(
            result["immediate_sensory_details"],
            LIST_MAX_LENGTHS["immediate_sensory_details"],
            "arrival_event.immediate_sensory_details",
        )

    return result


def normalize_character(character: dict) -> dict:
    """Normalise un personnage avec ses arcs."""
    if not isinstance(character, dict):
        return character

    result = dict(character)

    # Tronquer pronouns (max 20 chars)
    if "pronouns" in result and isinstance(result["pronouns"], str):
        if len(result["pronouns"]) > FIELD_MAX_LENGTHS["character.pronouns"]:
            # Garder juste le pronom principal
            pronouns = result["pronouns"].split(" ")[0].strip()
            if len(pronouns) > FIELD_MAX_LENGTHS["character.pronouns"]:
                pronouns = pronouns[: FIELD_MAX_LENGTHS["character.pronouns"]]
            logger.warning(
                f"[Normalizer] Troncature pronouns: '{result['pronouns']}' → '{pronouns}'"
            )
            result["pronouns"] = pronouns

    # Tronquer gender (max 30 chars)
    if "gender" in result and isinstance(result["gender"], str):
        if len(result["gender"]) > FIELD_MAX_LENGTHS["character.gender"]:
            # Garder juste le pronom principal
            gender = result["gender"].split(" ")[0].strip()
            if len(gender) > FIELD_MAX_LENGTHS["character.gender"]:
                gender = gender[: FIELD_MAX_LENGTHS["character.gender"]]
            logger.warning(
                f"[Normalizer] Troncature gender: '{result['gender']}' → '{gender}'"
            )
            result["gender"] = gender

    # Tronquer species (max 50 chars)
    if "species" in result and isinstance(result["species"], str):
        if len(result["species"]) > FIELD_MAX_LENGTHS["character.species"]:
            # Garder juste le pronom principal
            species = result["species"].split(" ")[0].strip()
            if len(species) > FIELD_MAX_LENGTHS["character.species"]:
                species = species[: FIELD_MAX_LENGTHS["character.species"]]
            logger.warning(
                f"[Normalizer] Troncature species: '{result['species']}' → '{species}'"
            )
            result["species"] = species

    # Normaliser les arcs du personnage
    if "arcs" in result and isinstance(result["arcs"], list):
        result["arcs"] = [normalize_arc(arc) for arc in result["arcs"]]

    # Tronquer les champs texte
    if "physical_description" in result:
        result["physical_description"] = truncate_string(
            result["physical_description"],
            FIELD_MAX_LENGTHS["character.physical_description"],
            "character.physical_description",
        )
    if "personality" in result:
        result["personality"] = truncate_string(
            result["personality"],
            FIELD_MAX_LENGTHS["character.personality"],
            "character.personality",
        )
    if "backstory" in result:
        result["backstory"] = truncate_string(
            result["backstory"],
            FIELD_MAX_LENGTHS["character.backstory"],
            "character.backstory",
        )
    if "secret" in result:
        result["secret"] = truncate_string(
            result["secret"], FIELD_MAX_LENGTHS["character.secret"], "character.secret"
        )

    return result


# =============================================================================
# CRÉATION D'ARRIVAL_EVENT PAR DÉFAUT
# =============================================================================


def create_default_arrival_event(data: dict) -> dict:
    """
    Crée un arrival_event par défaut basé sur les données disponibles.
    Utilisé quand le JSON est tronqué avant arrival_event.
    """
    # Trouver un lieu d'arrivée (dock, terminal, etc.)
    arrival_location = "Station"
    if "locations" in data and isinstance(data["locations"], list):
        for loc in data["locations"]:
            if isinstance(loc, dict):
                loc_type = loc.get("location_type", "").lower()
                if any(
                    t in loc_type
                    for t in [
                        "dock",
                        "terminal",
                        "port",
                        "arrival",
                        "gate",
                        "bay",
                        "quai",
                    ]
                ):
                    arrival_location = loc.get("name", arrival_location)
                    break
        # Fallback: premier lieu
        if arrival_location == "Station" and data["locations"]:
            arrival_location = data["locations"][0].get("name", "Station")

    # Trouver un PNJ potentiel
    first_npc = None
    if (
        "characters" in data
        and isinstance(data["characters"], list)
        and data["characters"]
    ):
        first_npc = data["characters"][0].get("name")

    logger.warning(
        f"[Normalizer] Création arrival_event par défaut (location: {arrival_location})"
    )

    return {
        "arrival_method": "navette de transport",
        "arrival_location_ref": arrival_location,
        "arrival_date": "Lundi 1er Janvier 2850",
        "time_of_day": "morning",
        "immediate_sensory_details": [
            "L'air recyclé de la station",
            "Le bourdonnement des systèmes",
            "La lumière artificielle",
        ],
        "first_npc_encountered": first_npc,
        "initial_mood": "Mélange d'appréhension et d'excitation",
        "immediate_need": "Trouver ses quartiers et s'orienter dans la station",
        "optional_incident": None,
    }


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

    # === Créer arrival_event si manquant ===
    if "arrival_event" not in result or result["arrival_event"] is None:
        result["arrival_event"] = create_default_arrival_event(result)

    # === Champs racine ===
    if "tone_notes" in result:
        result["tone_notes"] = truncate_string(
            result["tone_notes"], FIELD_MAX_LENGTHS["tone_notes"], "tone_notes"
        )

    # === World ===
    if "world" in result and isinstance(result["world"], dict):
        world = dict(result["world"])
        if "description" in world:
            world["description"] = truncate_string(
                world["description"],
                FIELD_MAX_LENGTHS["world.description"],
                "world.description",
            )
        if "atmosphere" in world:
            world["atmosphere"] = truncate_string(
                world["atmosphere"],
                FIELD_MAX_LENGTHS["world.atmosphere"],
                "world.atmosphere",
            )
        result["world"] = world
        if "station_type" in world:
            world["station_type"] = truncate_string(
                world["station_type"],
                FIELD_MAX_LENGTHS["world.station_type"],
                "world.station_type",
            )
        result["world"] = world

    # === Protagonist ===
    if "protagonist" in result and isinstance(result["protagonist"], dict):
        proto = dict(result["protagonist"])
        if "departure_story" in proto:
            proto["departure_story"] = truncate_string(
                proto["departure_story"],
                FIELD_MAX_LENGTHS["protagonist.departure_story"],
                "protagonist.departure_story",
            )
        if "backstory" in proto:
            proto["backstory"] = truncate_string(
                proto["backstory"],
                FIELD_MAX_LENGTHS["protagonist.backstory"],
                "protagonist.backstory",
            )
        if "departure_reason" in proto:
            proto["departure_reason"] = normalize_value(
                proto["departure_reason"],
                DEPARTURE_REASON_SYNONYMS,
                "protagonist.departure_reason",
            )
        result["protagonist"] = proto

        credits = proto.get("initial_credits", 1400)
        reason = proto.get("departure_reason", "standard")

        CREDIT_RANGES = {
            "flight": (100, 600),
            "breakup": (600, 1800),
            "opportunity": (1800, 5000),
            "fresh_start": (800, 2500),
            "standard": (1200, 2200),
            "broke": (0, 300),
            "other": (0, 10000),
        }

        min_c, max_c = CREDIT_RANGES.get(reason, (0, 10000))
        if credits < min_c:
            logger.warning(
                f"[Normalizer] Credits {credits} → {min_c} (min pour {reason})"
            )
            proto["initial_credits"] = min_c
        elif credits > max_c:
            logger.warning(
                f"[Normalizer] Credits {credits} → {max_c} (max pour {reason})"
            )
            proto["initial_credits"] = max_c

    # === Personal AI ===
    if "personal_ai" in result and isinstance(result["personal_ai"], dict):
        ai = dict(result["personal_ai"])
        if "quirk" in ai:
            ai["quirk"] = truncate_string(
                ai["quirk"], FIELD_MAX_LENGTHS["personal_ai.quirk"], "personal_ai.quirk"
            )
        if "personality" in ai:
            ai["personality"] = truncate_string(
                ai["personality"],
                FIELD_MAX_LENGTHS["personal_ai.personality"],
                "personal_ai.personality",
            )
        result["personal_ai"] = ai

    # === Characters ===
    if "characters" in result and isinstance(result["characters"], list):
        result["characters"] = truncate_list(
            result["characters"], LIST_MAX_LENGTHS["characters"], "characters"
        )
        result["characters"] = [normalize_character(c) for c in result["characters"]]

    # === Locations ===
    if "locations" in result and isinstance(result["locations"], list):
        result["locations"] = truncate_list(
            result["locations"], LIST_MAX_LENGTHS["locations"], "locations"
        )
        result["locations"] = [normalize_location(loc) for loc in result["locations"]]

    # === Organizations ===
    if "organizations" in result and isinstance(result["organizations"], list):
        result["organizations"] = truncate_list(
            result["organizations"], 5, "organizations"
        )

    # === Inventory ===
    if "inventory" in result and isinstance(result["inventory"], list):
        result["inventory"] = truncate_list(
            result["inventory"], LIST_MAX_LENGTHS["inventory"], "inventory"
        )

    # === Narrative Arcs ===
    if "narrative_arcs" in result and isinstance(result["narrative_arcs"], list):
        result["narrative_arcs"] = truncate_list(
            result["narrative_arcs"],
            LIST_MAX_LENGTHS["narrative_arcs"],
            "narrative_arcs",
        )
        result["narrative_arcs"] = [
            normalize_arc(arc) for arc in result["narrative_arcs"]
        ]

    # === Initial Relations ===
    if "initial_relations" in result and isinstance(result["initial_relations"], list):
        result["initial_relations"] = truncate_list(
            result["initial_relations"],
            LIST_MAX_LENGTHS["initial_relations"],
            "initial_relations",
        )
        result["initial_relations"] = [
            normalize_relation(rel) for rel in result["initial_relations"]
        ]

    # === Arrival Event ===
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
    """Normalise une sortie NarrationOutput."""
    if not isinstance(data, dict):
        return data

    result = dict(data)

    # Tronquer les champs texte
    if "scene_mood" in result:
        result["scene_mood"] = truncate_string(
            result["scene_mood"], FIELD_MAX_LENGTHS["scene_mood"], "scene_mood"
        )

    if "narrator_notes" in result:
        result["narrator_notes"] = truncate_string(
            result["narrator_notes"],
            FIELD_MAX_LENGTHS["narrator_notes"],
            "narrator_notes",
        )

    # if "narrative_text" in result:
    #     result["narrative_text"] = truncate_string(
    #         result["narrative_text"], 4000, "narrative_text"
    #     )
    #
    if "current_location" in result:
        result["current_location"] = truncate_string(
            result["current_location"],
            FIELD_MAX_LENGTHS["entityref"],
            "current_location",
        )

    # Tronquer les actions suggérées
    if "suggested_actions" in result and isinstance(result["suggested_actions"], list):
        result["suggested_actions"] = [
            truncate_string(
                a, FIELD_MAX_LENGTHS["suggested_action"], "suggested_action"
            )
            if isinstance(a, str)
            else a
            for a in result["suggested_actions"][:5]  # Max 5 actions
        ]

    # Tronquer les NPCs présents
    if "npcs_present" in result and isinstance(result["npcs_present"], list):
        result["npcs_present"] = result["npcs_present"][:10]  # Max 10 NPCs

    # Normaliser hints si présent
    if "hints" in result and isinstance(result["hints"], dict):
        hints = result["hints"]
        if "foreshadowing" in hints and isinstance(hints["foreshadowing"], list):
            hints["foreshadowing"] = [
                truncate_string(f, 150, "hint.foreshadowing")
                if isinstance(f, str)
                else f
                for f in hints["foreshadowing"][:5]
            ]
        if "world_detail" in hints and isinstance(hints["world_detail"], list):
            hints["world_detail"] = [
                truncate_string(w, 150, "hint.world_detail")
                if isinstance(w, str)
                else w
                for w in hints["world_detail"][:5]
            ]

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
