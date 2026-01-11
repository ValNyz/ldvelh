"""
LDVELH - World Generation Schema
Modèle spécifique pour la génération initiale du monde
Avec validation SOFT des références (filtrage au lieu d'erreur)
Architecture EAV : données dans attributes
"""

import logging
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any

from .core import (
    AttributeKey,
    EntityRef,
    Mood,
    Name,
    ShortText,
    Tag,
    TemporalValidationMixin,
    Text,
    AttributeWithVisibility,
    normalize_attribute_key,
)
from .entities import (
    CharacterData,
    LocationData,
    ObjectData,
    OrganizationData,
    PersonalAIData,
    ProtagonistData,
    WorldData,
)
from .relations import RelationData
from .narrative import NarrativeArcData

logger = logging.getLogger(__name__)


WORLD_GENERATION_SOFT_MINIMUMS: dict[str, tuple[int, str]] = {
    "characters": (3, "3+ characters recommended for social dynamics"),
    "locations": (
        4,
        "4+ locations recommended (residence + workplace + social + arrival)",
    ),
    "organizations": (1, "At least 1 organization expected"),
    "inventory": (3, "3+ starting items recommended"),
    "narrative_arcs": (3, "3+ arcs recommended for richer storytelling"),
    "initial_relations": (5, "5+ relations expected for world coherence"),
}


# =============================================================================
# HELPER FUNCTIONS FOR EAV ACCESS
# =============================================================================


def get_entity_attribute(entity, key: str | AttributeKey, default=None):
    """
    Get an attribute value from an entity's attributes list.
    Works with both AttributeKey enum and string keys.
    """
    if not hasattr(entity, "attributes"):
        return default

    # Normalize key to string for comparison
    key_str = key.value if isinstance(key, AttributeKey) else key

    for attr in entity.attributes:
        attr_key = attr.key.value if hasattr(attr.key, "value") else str(attr.key)
        if attr_key == key_str:
            return attr.value
    return default


def get_entity_attribute_int(entity, key: str | AttributeKey, default: int = 0) -> int:
    """Get an attribute as integer."""
    value = get_entity_attribute(entity, key)
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def get_entity_attribute_float(
    entity, key: str | AttributeKey, default: float = 0.0
) -> float:
    """Get an attribute as float."""
    value = get_entity_attribute(entity, key)
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def set_entity_attribute(
    entity: BaseModel,
    key: str | AttributeKey,
    value: Any,
    known: bool | None = None,
) -> None:
    """Set or update an attribute value in an EAV entity."""
    # Normaliser la clé si c'est un string
    if isinstance(key, str):
        key = normalize_attribute_key(key)

    # Chercher et mettre à jour l'attribut existant
    for attr in entity.attributes:
        if attr.key == key:
            attr.value = str(value)
            if known is not None:
                attr.known_by_protagonist = known
            return

    # Attribut non trouvé → l'ajouter
    entity.attributes.append(
        AttributeWithVisibility(
            key=key,
            value=str(value),
            known_by_protagonist=known if known is not None else False,
        )
    )


# =============================================================================
# ARRIVAL EVENT
# =============================================================================


class ArrivalEventData(BaseModel):
    """Instructions for generating the first narrative moment"""

    arrival_method: Name  # 100 chars
    arrival_location_ref: EntityRef
    arrival_date: Tag  # 50 chars - ex: 'Lundi 14 Mars 2847'
    time: str  # "14h30"
    immediate_sensory_details: list[str] = Field(..., min_length=3, max_length=6)
    first_npc_encountered: EntityRef | None = None
    initial_mood: Mood  # 80 chars
    immediate_need: ShortText  # 200 chars
    optional_incident: Text | None = None  # 300 chars


# =============================================================================
# COMPLETE WORLD GENERATION OUTPUT
# =============================================================================


class WorldGeneration(BaseModel, TemporalValidationMixin):
    """Complete output from world generation LLM call"""

    # Meta
    generation_seed_words: list[str] = Field(
        ...,
        min_length=3,
        max_length=6,
        description="Thematic words guiding this generation",
    )
    tone_notes: Text  # 300 chars

    # Core elements
    world: WorldData
    protagonist: ProtagonistData
    personal_ai: PersonalAIData

    # Entities
    characters: list[CharacterData] = Field(..., max_length=8)
    locations: list[LocationData] = Field(..., max_length=10)
    organizations: list[OrganizationData] = Field(..., max_length=5)
    inventory: list[ObjectData] = Field(..., max_length=15)

    # Narrative
    narrative_arcs: list[NarrativeArcData] = Field(..., min_length=1, max_length=10)

    # Relations
    initial_relations: list[RelationData] = Field(..., min_length=5)

    # First moment
    arrival_event: ArrivalEventData

    # =========================================================================
    # VALIDATORS
    # =========================================================================

    @model_validator(mode="after")
    def validate_soft_minimums(self) -> "WorldGeneration":
        """Check all list minimums - soft validation (warning, no error)"""
        for field_name, (minimum, message) in WORLD_GENERATION_SOFT_MINIMUMS.items():
            value = getattr(self, field_name, [])
            if len(value) < minimum:
                logger.warning(
                    f"[Validation] {field_name}: {len(value)}/{minimum} - {message}"
                )
        return self

    @model_validator(mode="before")
    @classmethod
    def ensure_arrival_event(cls, data: dict) -> dict:
        """Create default arrival_event if missing (truncated JSON from LLM)"""
        if not isinstance(data, dict):
            return data

        if "arrival_event" not in data or data["arrival_event"] is None:
            logger.warning("[Validation] arrival_event missing → creating default")
            data["arrival_event"] = cls._create_default_arrival_event(data)

        return data

    @staticmethod
    def _create_default_arrival_event(data: dict) -> dict:
        """Create a default arrival_event based on available data."""
        arrival_location = "Station"
        if "locations" in data and isinstance(data["locations"], list):
            arrival_types = {
                "dock",
                "terminal",
                "port",
                "arrival",
                "gate",
                "bay",
                "quai",
            }
            for loc in data["locations"]:
                if isinstance(loc, dict):
                    # EAV: look for location_type in attributes
                    loc_type = ""
                    attrs = loc.get("attributes", [])
                    for attr in attrs:
                        if (
                            isinstance(attr, dict)
                            and attr.get("key") == "location_type"
                        ):
                            loc_type = attr.get("value", "").lower()
                            break
                    if any(t in loc_type for t in arrival_types):
                        arrival_location = loc.get("name", arrival_location)
                        break
            if arrival_location == "Station" and data["locations"]:
                first_loc = data["locations"][0]
                if isinstance(first_loc, dict):
                    arrival_location = first_loc.get("name", "Station")

        first_npc = None
        if (
            "characters" in data
            and isinstance(data["characters"], list)
            and data["characters"]
        ):
            first_char = data["characters"][0]
            if isinstance(first_char, dict):
                first_npc = first_char.get("name")

        return {
            "arrival_method": "navette de transport",
            "arrival_location_ref": arrival_location,
            "arrival_date": "Lundi 1er Janvier 2850",
            "time": "8h00",
            "immediate_sensory_details": [
                "L'air recyclé de la station",
                "Le bourdonnement des systèmes",
                "La lumière artificielle",
            ],
            "first_npc_encountered": first_npc,
            "initial_mood": "Mélange d'appréhension et d'excitation",
            "immediate_need": "Trouver ses quartiers et s'orienter",
            "optional_incident": None,
        }

    @field_validator("characters")
    @classmethod
    def validate_character_diversity(
        cls, v: list[CharacterData]
    ) -> list[CharacterData]:
        """Ensure species diversity - soft validation"""
        species_list = []
        for c in v:
            species = get_entity_attribute(c, "species")
            if species:
                species_list.append(species.lower())
            else:
                species_list.append("unknown")

        if species_list and species_list.count("human") == len(species_list):
            logger.warning(
                "[Validation] All characters are human - diversity encouraged"
            )
        return v

    @field_validator("locations")
    @classmethod
    def validate_essential_locations(cls, v: list[LocationData]) -> list[LocationData]:
        """Ensure we have arrival point and residence - soft validation"""
        types = []
        for loc in v:
            loc_type = get_entity_attribute(loc, "location_type")
            if loc_type:
                types.append(loc_type.lower())

        residence_types = {
            "apartment",
            "quarters",
            "residence",
            "housing",
            "room",
            "studio",
        }
        arrival_types = {"dock", "terminal", "port", "arrival", "gate", "bay", "quai"}

        has_residence = any(t in residence_types for t in types)
        has_arrival = any(t in arrival_types for t in types)

        if not has_residence:
            logger.warning("[Validation] No residence location found for Valentin")
        if not has_arrival:
            logger.warning("[Validation] No arrival location (dock, terminal) found")
        return v

    @model_validator(mode="after")
    def validate_temporal_coherence_soft(self) -> "WorldGeneration":
        """Validate all temporal relationships - SOFT MODE."""
        founding = self.world.founding_cycle

        for char in self.characters:
            arrival_cycle = get_entity_attribute_int(
                char, AttributeKey.ARRIVAL_CYCLE, None
            )
            if (
                arrival_cycle is not None
                and founding is not None
                and arrival_cycle < founding
            ):
                logger.warning(
                    f"[Temporal] Character '{char.name}': arrival_cycle ({arrival_cycle}) "
                    f"before founding_cycle ({founding}) - correcting"
                )
                set_entity_attribute(char, AttributeKey.ARRIVAL_CYCLE, founding)

        for org in self.organizations:
            org_founding = get_entity_attribute_int(
                org, AttributeKey.FOUNDING_CYCLE, None
            )
            if (
                org_founding is not None
                and founding is not None
                and org_founding < founding
            ):
                logger.warning(
                    f"[Temporal] Organization '{org.name}': founding_cycle ({org_founding}) "
                    f"before world founding ({founding}) - correcting"
                )
                set_entity_attribute(org, AttributeKey.FOUNDING_CYCLE, founding)
        return self

    @model_validator(mode="after")
    def validate_references_soft(self) -> "WorldGeneration":
        """
        Validate all entity references - SOFT MODE.
        - Optional refs: set to None if invalid
        - List refs: filter invalid entries
        - Only filter entity if required refs are invalid or list becomes empty
        """
        max_passes = 5
        pass_num = 0

        while pass_num < max_passes:
            pass_num += 1
            changed = False
            known_names = self._build_name_registry()

            # --- Characters: nullify invalid optional refs ---
            for char in self.characters:
                if char.workplace_ref and char.workplace_ref.lower() not in known_names:
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: Character '{char.name}' "
                        f"- nullifying invalid workplace_ref '{char.workplace_ref}'"
                    )
                    char.workplace_ref = None
                    changed = True
                if char.residence_ref and char.residence_ref.lower() not in known_names:
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: Character '{char.name}' "
                        f"- nullifying invalid residence_ref '{char.residence_ref}'"
                    )
                    char.residence_ref = None
                    changed = True

            # --- Locations: nullify invalid optional parent refs ---
            for loc in self.locations:
                if (
                    loc.parent_location_ref
                    and loc.parent_location_ref.lower() not in known_names
                ):
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: Location '{loc.name}' "
                        f"- nullifying invalid parent_ref '{loc.parent_location_ref}'"
                    )
                    loc.parent_location_ref = None
                    changed = True

            # --- Organizations: nullify invalid optional HQ refs ---
            for org in self.organizations:
                if (
                    org.headquarters_ref
                    and org.headquarters_ref.lower() not in known_names
                ):
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: Organization '{org.name}' "
                        f"- nullifying invalid HQ ref '{org.headquarters_ref}'"
                    )
                    org.headquarters_ref = None
                    changed = True

            # --- Relations: filter those with invalid required refs ---
            valid_rels = []
            for rel in self.initial_relations:
                source_valid = rel.source_ref.lower() in known_names
                target_valid = rel.target_ref.lower() in known_names

                if not source_valid or not target_valid:
                    invalid_refs = []
                    if not source_valid:
                        invalid_refs.append(f"source '{rel.source_ref}'")
                    if not target_valid:
                        invalid_refs.append(f"target '{rel.target_ref}'")
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: Filtering Relation {rel.relation_type.value} "
                        f"- invalid {', '.join(invalid_refs)}"
                    )
                    changed = True
                else:
                    valid_rels.append(rel)

            if len(valid_rels) != len(self.initial_relations):
                self.initial_relations = valid_rels

            # --- Narrative arcs: filter invalid refs from involved_entities ---
            valid_arcs = []
            for arc in self.narrative_arcs:
                valid_entities = [
                    e for e in arc.involved_entities if e.lower() in known_names
                ]
                invalid_entities = [
                    e for e in arc.involved_entities if e.lower() not in known_names
                ]

                if invalid_entities:
                    if valid_entities:
                        logger.warning(
                            f"[SoftRef] Pass {pass_num}: Arc '{arc.title}' "
                            f"- removing invalid entities: {invalid_entities}"
                        )
                        arc.involved_entities = valid_entities
                        valid_arcs.append(arc)
                        changed = True
                    else:
                        logger.warning(
                            f"[SoftRef] Pass {pass_num}: Filtering Arc '{arc.title}' "
                            f"- no valid entities remain"
                        )
                        changed = True
                else:
                    valid_arcs.append(arc)

            if len(valid_arcs) != len(self.narrative_arcs):
                self.narrative_arcs = valid_arcs

            # --- Fix arrival_event refs ---
            if self.arrival_event.arrival_location_ref.lower() not in known_names:
                fallback = self._find_arrival_location_fallback()
                if fallback:
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: arrival_location_ref "
                        f"'{self.arrival_event.arrival_location_ref}' not found "
                        f"→ fallback to '{fallback}'"
                    )
                    self.arrival_event.arrival_location_ref = fallback
                    changed = True

            if self.arrival_event.first_npc_encountered:
                if self.arrival_event.first_npc_encountered.lower() not in known_names:
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: first_npc_encountered "
                        f"'{self.arrival_event.first_npc_encountered}' not found "
                        f"→ setting to None"
                    )
                    self.arrival_event.first_npc_encountered = None
                    changed = True

            if not changed:
                if pass_num > 1:
                    logger.info(
                        f"[SoftRef] Validation stabilized after {pass_num} passes"
                    )
                break

        if pass_num >= max_passes:
            logger.warning(
                f"[SoftRef] Reached max passes ({max_passes}), may have remaining issues"
            )

        self._check_minimums_after_filtering()
        return self

    def _build_name_registry(self) -> set[str]:
        """Build a set of all known entity names (lowercase)"""
        known = {self.protagonist.name.lower(), self.personal_ai.name.lower()}
        known.add(self.world.name.lower())
        known.update(c.name.lower() for c in self.characters)
        known.update(loc.name.lower() for loc in self.locations)
        known.update(org.name.lower() for org in self.organizations)
        known.update(item.name.lower() for item in self.inventory)
        return known

    def _find_arrival_location_fallback(self) -> str | None:
        """Find a suitable arrival location from existing locations"""
        arrival_types = {"dock", "terminal", "port", "arrival", "gate", "bay", "quai"}
        for loc in self.locations:
            loc_type = get_entity_attribute(loc, "location_type")
            if loc_type and loc_type.lower() in arrival_types:
                return loc.name
        if self.locations:
            return self.locations[0].name
        return None

    def _check_minimums_after_filtering(self) -> None:
        """Log warning if minimums not met after filtering (don't raise)"""
        issues = []
        if len(self.characters) < 3:
            issues.append(f"characters: {len(self.characters)}/3")
        if len(self.locations) < 4:
            issues.append(f"locations: {len(self.locations)}/4")
        if len(self.organizations) < 1:
            issues.append(f"organizations: {len(self.organizations)}/1")
        if len(self.narrative_arcs) < 3:
            issues.append(f"narrative_arcs: {len(self.narrative_arcs)}/3")
        if len(self.initial_relations) < 5:
            issues.append(f"relations: {len(self.initial_relations)}/5")

        if issues:
            logger.warning(
                f"[SoftRef] After filtering, minimums not met: {', '.join(issues)} "
                f"- continuing anyway"
            )

    @model_validator(mode="after")
    def validate_inventory_for_departure(self) -> "WorldGeneration":
        """Check inventory matches departure reason - soft validation"""
        # Get departure_reason from protagonist attributes
        reason_str = get_entity_attribute(self.protagonist, "departure_reason")
        if not reason_str:
            reason_str = "other"

        # Get credits from protagonist attributes
        credits = get_entity_attribute_int(self.protagonist, "credits", 1400)

        expected_ranges = {
            "flight": (100, 600),
            "breakup": (600, 1800),
            "opportunity": (1800, 5000),
            "fresh_start": (800, 2500),
            "standard": (1200, 2200),
            "broke": (0, 300),
            "other": (0, 10000),
        }

        min_c, max_c = expected_ranges.get(reason_str, (0, 10000))
        if not (min_c <= credits <= max_c):
            logger.warning(
                f"[Validation] Credits ({credits}) unusual for departure_reason "
                f"'{reason_str}' (expected {min_c}-{max_c})"
            )

        return self
