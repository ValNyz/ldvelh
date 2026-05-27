"""
LDVELH - World Generation Schema
Models for initial world generation output.
Soft validation of references (filter instead of error).
"""

import logging

from pydantic import BaseModel, Field, field_validator, model_validator

from .core import (
    EntityRef,
    Mood,
    Name,
    ShortText,
    Tag,
    TemporalValidationMixin,
    Text,
)
from .entities import (
    CharacterData,
    CompanionData,
    LocationData,
    ObjectData,
    OrganizationData,
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
# ARRIVAL EVENT
# =============================================================================


class ArrivalEventData(BaseModel):
    """Instructions for generating the first narrative moment"""

    arrival_method: Name  # 100 chars
    arrival_location_ref: EntityRef
    arrival_date: Tag  # 50 chars - e.g. 'Lundi 14 Mars 2847'
    time: str  # "14h30"
    immediate_sensory_details: list[str] = Field(..., min_length=3, max_length=6)
    first_npc_encountered: EntityRef | None = None
    initial_mood: Mood  # 80 chars
    immediate_need: ShortText  # 200 chars
    optional_incident: Text | None = None  # 300 chars

    @field_validator("first_npc_encountered", mode="before")
    @classmethod
    def _normalize_npc(cls, v):
        """LLMs sometimes generate a dict instead of a string for this field."""
        if isinstance(v, dict):
            return v.get("name") or v.get("current_name")
        return v

    def build_arrival_summary(self) -> str:
        """Build a narrative summary of the arrival in French."""
        parts = []

        if self.arrival_method:
            method_clean = self.arrival_method.strip().rstrip(".")
            parts.append(f"Arrivée via {method_clean}")
        else:
            parts.append("Arrivée sur la station")

        if self.initial_mood:
            mood_clean = self.initial_mood.strip().rstrip(".")
            parts.append(mood_clean.capitalize())

        if self.optional_incident:
            incident_summary = self._summarize_incident()
            if incident_summary:
                parts.append(incident_summary)
        elif self.immediate_need:
            need = self.immediate_need.strip().rstrip(".")
            if len(need) < 60:
                parts.append(f"Priorité : {need.lower()}")

        summary = ". ".join(parts)
        if not summary.endswith("."):
            summary += "."

        if len(summary) > 300:
            summary = summary[:297].rsplit(" ", 1)[0] + "..."

        return summary

    def _summarize_incident(self) -> str | None:
        """Summarize an incident in a short sentence."""
        if not self.optional_incident:
            return None

        incident = self.optional_incident.strip()

        if len(incident) < 80:
            return incident.rstrip(".")

        first_sentence = incident.split(".")[0].strip()
        if len(first_sentence) < 100:
            return first_sentence

        truncated = incident[:80].rsplit(" ", 1)[0]
        return truncated + "..."


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
    # Core elements
    world: WorldData
    protagonist: ProtagonistData
    companion: CompanionData

    # Entities
    characters: list[CharacterData] = Field(..., max_length=8)
    locations: list[LocationData] = Field(..., max_length=10)
    organizations: list[OrganizationData] = Field(..., max_length=5)
    inventory: list[ObjectData] = Field(..., max_length=15)

    # Narrative
    narrative_arcs: list[NarrativeArcData] = Field(..., min_length=1, max_length=10)

    # Relations
    initial_relations: list[RelationData] = Field(..., min_length=1)

    # First moment
    arrival_event: ArrivalEventData

    # =========================================================================
    # VALIDATORS
    # =========================================================================

    @model_validator(mode="after")
    def validate_soft_minimums(self) -> "WorldGeneration":
        """Check all list minimums — soft validation (warning, no error)"""
        for field_name, (minimum, message) in WORLD_GENERATION_SOFT_MINIMUMS.items():
            value = getattr(self, field_name, [])
            if len(value) < minimum:
                logger.warning(
                    f"[Validation] {field_name}: {len(value)}/{minimum} - {message}"
                )
        return self

    @model_validator(mode="before")
    @classmethod
    def normalize_and_ensure_defaults(cls, data: dict) -> dict:
        """Normalize LLM output structure and create defaults for missing fields."""
        if not isinstance(data, dict):
            return data

        # --- Flatten world-nested structure (weaker models like Mistral) ---
        # Some LLMs nest characters/locations/etc. inside "world" instead of
        # top-level. Detect and hoist them up.
        HOISTABLE = {
            "characters", "locations", "organizations", "inventory",
            "narrative_arcs", "initial_relations", "protagonist",
            "companion", "personal_assistant", "personal_ai", "arrival_event",
            "generation_seed_words", "irritants",
            # Common LLM variants
            "global_narrative_arcs", "arcs", "relations",
        }
        world = data.get("world")
        if isinstance(world, dict):
            hoisted = []
            for key in list(world.keys()):
                if key in HOISTABLE and key not in data:
                    data[key] = world.pop(key)
                    hoisted.append(key)
            if hoisted:
                logger.info(
                    f"[Validation] Hoisted {len(hoisted)} fields from 'world': "
                    f"{', '.join(hoisted)}"
                )

        # --- Handle field name variants from weaker LLMs ---
        RENAMES = {
            "global_narrative_arcs": "narrative_arcs",
            "arcs": "narrative_arcs",
            "relations": "initial_relations",
        }
        for old_key, new_key in RENAMES.items():
            if old_key in data and new_key not in data:
                data[new_key] = data.pop(old_key)
                logger.info(f"[Validation] Renamed '{old_key}' -> '{new_key}'")

        # --- Extract protagonist from characters list if missing ---
        if "protagonist" not in data and "characters" in data:
            characters = data.get("characters", [])
            if isinstance(characters, list):
                for i, char in enumerate(characters):
                    if isinstance(char, dict) and char.get("station_arrival_cycle") == 0:
                        data["protagonist"] = characters.pop(i)
                        logger.info(
                            "[Validation] Extracted protagonist from characters list"
                        )
                        break

        # --- Handle personal_ai / personal_assistant -> companion rename ---
        if "companion" not in data or data["companion"] is None:
            for old_key in ("personal_assistant", "personal_ai"):
                if old_key in data and data[old_key] is not None:
                    data["companion"] = data.pop(old_key)
                    logger.info(f"[Validation] Renamed '{old_key}' -> 'companion'")
                    break

        # --- Create default companion if missing ---
        if "companion" not in data or data["companion"] is None:
            logger.warning("[Validation] companion missing — creating default")
            data["companion"] = {
                "name": "Assistant",
                "voice": "neutre, efficace",
                "traits": ["pragmatique", "discret"],
                "substrate": "terminal personnel",
            }

        # --- Normalize location field names: type -> location_type ---
        # LLMs often abbreviate `location_type` to `type` on each location entry,
        # which then trips the residence/arrival detector (it scans by location_type).
        if isinstance(data.get("locations"), list):
            renamed = 0
            for loc in data["locations"]:
                if isinstance(loc, dict) and "type" in loc and "location_type" not in loc:
                    loc["location_type"] = loc.pop("type")
                    renamed += 1
            if renamed:
                logger.info(
                    f"[Validation] Renamed {renamed} location 'type' -> 'location_type'"
                )

        # --- Normalize inventory shape: dict {credits, items} -> flat list ---
        # LLMs naturally bundle credits + items into one inventory object.
        # Hoist items to top-level inventory and move credits to protagonist.
        inv = data.get("inventory")
        if isinstance(inv, dict) and ("items" in inv or "credits" in inv):
            credits = inv.get("credits")
            items = inv.get("items", [])
            if credits is not None:
                proto = data.setdefault("protagonist", {})
                if isinstance(proto, dict) and "credits" not in proto:
                    proto["credits"] = credits
            data["inventory"] = items if isinstance(items, list) else []
            logger.info(
                "[Validation] Normalized inventory dict -> list "
                f"(moved {'credits' if credits is not None else 'no credits'} "
                "to protagonist)"
            )

        # --- Normalize inventory item field: type -> category ---
        if isinstance(data.get("inventory"), list):
            renamed = 0
            for item in data["inventory"]:
                if isinstance(item, dict) and "type" in item and "category" not in item:
                    item["category"] = item.pop("type")
                    renamed += 1
            if renamed:
                logger.info(
                    f"[Validation] Renamed {renamed} inventory item 'type' -> 'category'"
                )

        # --- Create default inventory if missing ---
        if "inventory" not in data or not data["inventory"]:
            logger.warning("[Validation] inventory missing — creating default")
            data["inventory"] = [
                {
                    "name": "Terminal personnel",
                    "category": "tech",
                    "description": "Appareil standard",
                    "transportable": True,
                    "stackable": False,
                    "base_value": 200,
                    "quantity": 1,
                }
            ]

        # --- Normalize relation field names: source/target/type -> *_ref/relation_type ---
        # LLMs use the casual graph-data names; the schema uses *_ref suffixes
        # for entity-name references plus the explicit `relation_type`.
        relations = data.get("initial_relations")
        if isinstance(relations, list):
            REL_RENAMES = {
                "source": "source_ref",
                "target": "target_ref",
                "type": "relation_type",
            }
            renamed_count = 0
            for rel in relations:
                if not isinstance(rel, dict):
                    continue
                for old, new in REL_RENAMES.items():
                    if old in rel and new not in rel:
                        rel[new] = rel.pop(old)
                        renamed_count += 1
            if renamed_count:
                logger.info(
                    f"[Validation] Renamed {renamed_count} relation fields "
                    "(source/target/type -> *_ref/relation_type)"
                )

        # --- Create default initial_relations if missing ---
        if "initial_relations" not in data or not data["initial_relations"]:
            logger.warning("[Validation] initial_relations missing — creating default")
            data["initial_relations"] = cls._build_default_relations(data)

        # --- Create / repair arrival_event ---
        # If missing, build the full default. If present but incomplete (LLM often
        # writes just `description`), keep whatever schema-valid fields the LLM
        # provided and fill the missing required ones from defaults.
        ARRIVAL_REQUIRED = {
            "arrival_method", "arrival_location_ref", "arrival_date", "time",
            "immediate_sensory_details", "initial_mood", "immediate_need",
        }
        ae = data.get("arrival_event")
        if not isinstance(ae, dict) or not ae:
            logger.warning("[Validation] arrival_event missing — creating default")
            data["arrival_event"] = cls._create_default_arrival_event(data)
        elif not ARRIVAL_REQUIRED.issubset(ae.keys()):
            missing = sorted(ARRIVAL_REQUIRED - ae.keys())
            logger.warning(
                f"[Validation] arrival_event missing fields {missing} — "
                "filling from defaults"
            )
            default = cls._create_default_arrival_event(data)
            for key, value in default.items():
                ae.setdefault(key, value)

        return data

    @staticmethod
    def _build_default_relations(data: dict) -> list[dict]:
        """Build minimal relations from protagonist refs and character refs."""
        relations = []
        proto = data.get("protagonist", {})
        proto_name = proto.get("name", "Protagoniste") if isinstance(proto, dict) else "Protagoniste"

        # Protagonist -> residence
        if isinstance(proto, dict) and proto.get("residence_ref"):
            relations.append({
                "source_ref": proto_name,
                "target_ref": proto["residence_ref"],
                "relation_type": "lives_at",
                "known_by_protagonist": True,
            })

        # Protagonist -> employer
        if isinstance(proto, dict) and proto.get("employer_ref"):
            relations.append({
                "source_ref": proto_name,
                "target_ref": proto["employer_ref"],
                "relation_type": "employed_by",
                "known_by_protagonist": True,
            })

        # Characters -> workplaces and residences
        for char in data.get("characters", []):
            if not isinstance(char, dict):
                continue
            name = char.get("name", "")
            if char.get("workplace_ref"):
                relations.append({
                    "source_ref": name,
                    "target_ref": char["workplace_ref"],
                    "relation_type": "works_at",
                    "known_by_protagonist": False,
                })
            if char.get("residence_ref"):
                relations.append({
                    "source_ref": name,
                    "target_ref": char["residence_ref"],
                    "relation_type": "lives_at",
                    "known_by_protagonist": False,
                })

        # Location parent refs
        for loc in data.get("locations", []):
            if isinstance(loc, dict) and loc.get("parent_location_ref"):
                relations.append({
                    "source_ref": loc["name"],
                    "target_ref": loc["parent_location_ref"],
                    "relation_type": "located_in",
                    "known_by_protagonist": False,
                })

        # Organization headquarters
        for org in data.get("organizations", []):
            if isinstance(org, dict) and org.get("headquarters_ref"):
                relations.append({
                    "source_ref": org["name"],
                    "target_ref": org["headquarters_ref"],
                    "relation_type": "located_in",
                    "known_by_protagonist": False,
                })

        return relations

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
                    loc_type = (loc.get("location_type") or "").lower()
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
        """Ensure species diversity — soft validation"""
        species_list = [(c.species or "unknown").lower() for c in v]
        if species_list and species_list.count("human") == len(species_list):
            logger.warning(
                "[Validation] All characters are human - diversity encouraged"
            )
        return v

    @field_validator("locations")
    @classmethod
    def validate_essential_locations(cls, v: list[LocationData]) -> list[LocationData]:
        """Ensure we have arrival point and residence — soft validation"""
        types = [(loc.location_type or "").lower() for loc in v]

        residence_types = {
            "apartment",
            "quarters",
            "residence",
            "housing",
            "room",
            "studio",
        }
        arrival_types = {
            "dock", "terminal", "port", "arrival", "gate", "bay", "quai",
            "spaceport", "space_port", "landing", "landing_pad", "hangar",
        }

        has_residence = any(
            any(keyword in t for keyword in residence_types) for t in types
        )
        has_arrival = any(
            any(keyword in t for keyword in arrival_types) for t in types
        )

        if not has_residence:
            logger.warning("[Validation] No residence location found for Valentin")
        if not has_arrival:
            logger.warning("[Validation] No arrival location (dock, terminal) found")
        return v

    @model_validator(mode="after")
    def validate_temporal_coherence_soft(self) -> "WorldGeneration":
        """Validate all temporal relationships — soft mode"""
        founding = self.world.founding_cycle

        for org in self.organizations:
            if org.founding_cycle is not None and founding is not None:
                if org.founding_cycle < founding:
                    logger.warning(
                        f"[Temporal] Organization '{org.name}': founding_cycle ({org.founding_cycle}) "
                        f"before world founding ({founding}) — correcting"
                    )
                    org.founding_cycle = founding
        return self

    @model_validator(mode="after")
    def validate_references_soft(self) -> "WorldGeneration":
        """
        Validate all entity references — soft mode.
        Optional refs: set to None if invalid.
        List refs: filter invalid entries.
        """
        max_passes = 5
        pass_num = 0

        while pass_num < max_passes:
            pass_num += 1
            changed = False
            known_names = self._build_name_registry()

            # Auto-create stub locations for missing optional location refs.
            # Rationale: the location extractor can enrich these later when the narrator
            # describes them. Preserving the relation is more valuable than dropping it.
            def _stub_if_missing(owner: str, ref_name: str, ref_value: str | None) -> bool:
                if not ref_value or ref_value.lower() in known_names:
                    return False
                logger.info(
                    f"[SoftRef] Pass {pass_num}: {owner} "
                    f"- creating stub location for {ref_name} '{ref_value}'"
                )
                self.locations.append(LocationData(name=ref_value))
                return True

            for char in self.characters:
                changed |= _stub_if_missing(
                    f"Character '{char.name}'", "workplace_ref", char.workplace_ref
                )
                changed |= _stub_if_missing(
                    f"Character '{char.name}'", "residence_ref", char.residence_ref
                )

            for loc in self.locations:
                changed |= _stub_if_missing(
                    f"Location '{loc.name}'", "parent_location_ref", loc.parent_location_ref
                )

            for org in self.organizations:
                changed |= _stub_if_missing(
                    f"Organization '{org.name}'", "headquarters_ref", org.headquarters_ref
                )

            # Relations: filter those with invalid required refs
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

            # Narrative arcs: filter invalid refs from involved_entities
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

            # Deduplicate arcs by title (case-insensitive)
            seen_titles: set[str] = set()
            deduped_arcs = []
            for arc in self.narrative_arcs:
                key = arc.title.lower().strip()
                if key in seen_titles:
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: Duplicate arc '{arc.title}' — removing"
                    )
                    changed = True
                else:
                    seen_titles.add(key)
                    deduped_arcs.append(arc)
            self.narrative_arcs = deduped_arcs

            # Fix arrival_event refs
            if self.arrival_event.arrival_location_ref.lower() not in known_names:
                fallback = self._find_arrival_location_fallback()
                if fallback:
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: arrival_location_ref "
                        f"'{self.arrival_event.arrival_location_ref}' not found "
                        f"— fallback to '{fallback}'"
                    )
                    self.arrival_event.arrival_location_ref = fallback
                    changed = True

            if self.arrival_event.first_npc_encountered:
                if self.arrival_event.first_npc_encountered.lower() not in known_names:
                    logger.warning(
                        f"[SoftRef] Pass {pass_num}: first_npc_encountered "
                        f"'{self.arrival_event.first_npc_encountered}' not found "
                        f"— setting to None"
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
        known = {self.protagonist.name.lower(), self.companion.name.lower()}
        known.add(self.world.name.lower())
        known.update(c.name.lower() for c in self.characters)
        known.update(loc.name.lower() for loc in self.locations)
        known.update(org.name.lower() for org in self.organizations)
        known.update(item.name.lower() for item in self.inventory)
        return known

    def _find_arrival_location_fallback(self) -> str | None:
        """Find a suitable arrival location from existing locations"""
        arrival_types = {
            "dock", "terminal", "port", "arrival", "gate", "bay", "quai",
            "spaceport", "space_port", "landing", "landing_pad", "hangar",
        }
        for loc in self.locations:
            if loc.location_type and loc.location_type.lower() in arrival_types:
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
        """Check inventory matches departure reason — soft validation"""
        reason = self.protagonist.departure_reason
        reason_key = reason.value if hasattr(reason, "value") else str(reason)

        credits = self.protagonist.credits

        expected_ranges = {
            "flight": (100, 600),
            "breakup": (600, 1800),
            "opportunity": (1800, 5000),
            "fresh_start": (800, 2500),
            "standard": (1200, 2200),
            "broke": (0, 300),
            "other": (0, 10000),
        }

        min_c, max_c = expected_ranges.get(reason_key, (0, 10000))
        if not (min_c <= credits <= max_c):
            logger.warning(
                f"[Validation] Credits ({credits}) unusual for departure_reason "
                f"'{reason_key}' (expected {min_c}-{max_c})"
            )

        return self
