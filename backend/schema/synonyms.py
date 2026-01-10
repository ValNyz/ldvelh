"""
LDVELH - Enum Synonyms
Dictionnaires de synonymes pour normalisation des valeurs LLM vers enums valides.
+ Normalisation des clés JSON.
"""

# =============================================================================
# RELATION TYPE
# =============================================================================

RELATION_TYPE_SYNONYMS = {
    # Erreurs courantes
    "headquarters_of": "located_in",
    "based_at": "located_in",
    "based_in": "located_in",
    "hq_of": "located_in",
    "home_of": "located_in",
    # Social
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
    # Professional
    "reports_to": "employed_by",
    "member_of": "employed_by",
    "employed_by": "employed_by",
    "works_for": "employed_by",
    "employee_of": "employed_by",
    "hired_by": "employed_by",
    "partner_with": "colleague_of",
    "works_alongside": "colleague_of",
    "collaborates_with": "colleague_of",
    "colleague_of": "colleague_of",
    "coworker": "colleague_of",
    "works_with": "colleague_of",
    "leads": "manages",
    "manages": "manages",
    "manager_of": "manages",
    "supervises": "manages",
    "boss_of": "manages",
    # Spatial
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
    "assigned_to": "works_at",
    # Ownership
    "owns": "owns",
    "possesses": "owns",
    "has": "owns",
    "owner_of": "owns",
    "owes_to": "owes_to",
    "indebted_to": "owes_to",
    "owes": "owes_to",
}

# =============================================================================
# CERTAINTY LEVEL
# =============================================================================

CERTAINTY_SYNONYMS = {
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
    # Canonical
    "certain": "certain",
    "probable": "probable",
    "rumor": "rumor",
    "uncertain": "uncertain",
}

# =============================================================================
# ENTITY TYPE
# =============================================================================

ENTITY_TYPE_SYNONYMS = {
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

# =============================================================================
# FACT TYPE
# =============================================================================

FACT_TYPE_SYNONYMS = {
    "action": "action",
    "act": "action",
    "deed": "action",
    "npc_action": "npc_action",
    "statement": "statement",
    "declaration": "statement",
    "revelation": "revelation",
    "reveal": "revelation",
    "promise": "promise",
    "commitment": "promise",
    "request": "request",
    "ask": "request",
    "refusal": "refusal",
    "refuse": "refusal",
    "decline": "refusal",
    "question": "question",
    "inquiry": "question",
    "observation": "observation",
    "notice": "observation",
    "atmosphere": "atmosphere",
    "ambiance": "atmosphere",
    "mood": "atmosphere",
    "state_change": "state_change",
    "change": "state_change",
    "acquisition": "acquisition",
    "gain": "acquisition",
    "obtain": "acquisition",
    "loss": "loss",
    "lose": "loss",
    "encounter": "encounter",
    "meeting": "encounter",
    "met": "encounter",
    "ran_into": "encounter",
    "interaction": "interaction",
    "exchange": "interaction",
    "conflict": "conflict",
    "confrontation": "conflict",
    "tension": "conflict",
    "flashback": "flashback",
    "memory": "flashback",
    "foreshadow": "foreshadow",
    "hint": "foreshadow",
    "decision": "decision",
    "choice": "decision",
    "realization": "realization",
    "epiphany": "realization",
}

# =============================================================================
# PARTICIPANT ROLE
# =============================================================================

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
# COMMITMENT TYPE
# =============================================================================

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

# =============================================================================
# ARC DOMAIN
# =============================================================================

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
    # Fallback for unknown domains
    "technical": "professional",
}

# =============================================================================
# MOMENT (Time of day)
# =============================================================================

MOMENT_SYNONYMS = {
    "night": "night",
    "midnight": "night",
    "nighttime": "night",
    "dawn": "morning",
    "sunrise": "morning",
    "daybreak": "morning",
    "early_morning": "morning",
    "morning": "morning",
    "am": "morning",
    "forenoon": "morning",
    "midday": "noon",
    "noon": "noon",
    "lunchtime": "noon",
    "afternoon": "afternoon",
    "pm": "afternoon",
    "evening": "evening",
    "dusk": "evening",
    "sunset": "evening",
    "nightfall": "evening",
    "late_night": "night",
    "late": "night",
}

# =============================================================================
# DEPARTURE REASON
# =============================================================================

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

# =============================================================================
# ORGANIZATION SIZE
# =============================================================================

ORG_SIZE_SYNONYMS = {
    # Too small → small
    "tiny": "small",
    "micro": "small",
    "mini": "small",
    "very_small": "small",
    "startup": "small",
    # Canonical
    "small": "small",
    "medium": "medium",
    "large": "large",
    "station_wide": "station-wide",
    "station-wide": "station-wide",
    # Variations
    "big": "large",
    "huge": "large",
    "massive": "station-wide",
    "global": "station-wide",
    "universal": "station-wide",
}

# =============================================================================
# KEY SYNONYMS (JSON field names)
# =============================================================================

KEY_SYNONYMS = {
    # Relations
    "relation_type": "relation_type",
    "type_relation": "relation_type",
    "relationship": "relation_type",
    "rel_type": "relation_type",
    # Certainty
    "certainty": "certainty",
    "certitude": "certainty",
    "confidence": "certainty",
    "level": "certainty",
    # Entities
    "entity_type": "entity_type",
    "type_entite": "entity_type",
    "ent_type": "entity_type",
    # References
    "source_ref": "source_ref",
    "source": "source_ref",
    "from": "source_ref",
    "from_ref": "source_ref",
    "target_ref": "target_ref",
    "target": "target_ref",
    "to": "target_ref",
    "to_ref": "target_ref",
    # Locations
    "arrival_location_ref": "arrival_location_ref",
    "arrival_location": "arrival_location_ref",
    "location": "arrival_location_ref",
    "location_ref": "location_ref",
    "lieu": "location_ref",
    "place_ref": "location_ref",
    # Time
    "arrival_date": "arrival_date",
    "date": "arrival_date",
    "starting_date": "arrival_date",
    "time_of_day": "time",
    "moment": "time",
    "time": "time",
    "hour": "time",
    # Characters
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
# KEY NORMALIZATION FUNCTIONS
# =============================================================================


def normalize_key(key: str) -> str:
    """Normalize a JSON field name."""
    return KEY_SYNONYMS.get(key.lower().strip(), key)


def normalize_dict_keys(data: dict) -> dict:
    """Normalize all keys in a dictionary."""
    if not isinstance(data, dict):
        return data
    return {normalize_key(k): v for k, v in data.items()}
