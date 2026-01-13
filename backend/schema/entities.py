"""
LDVELH - Entity Schema Models (EAV Architecture)
Uses typed attribute classes for entity-specific normalization
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .core import (
    ATTRIBUTE_NORMALIZERS,
    AttributeKey,
    AttributeWithVisibility,
    Cycle,
    DepartureReason,
    EntityRef,
    EntityType,
    Label,
    Name,
    Skill,
    Tag,
    normalize_attribute_key,
)

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER: Convert raw dict/list to typed attributes
# =============================================================================


def _parse_attributes(
    raw_attrs: list[dict] | list[AttributeWithVisibility],
    entity_type: EntityType,
) -> list[AttributeWithVisibility]:
    """
    Parse raw attribute dicts into AttributeWithVisibility objects
    with entity-specific key normalization.
    """

    normalizer = ATTRIBUTE_NORMALIZERS.get(entity_type, normalize_attribute_key)
    result = []

    for item in raw_attrs:
        if isinstance(item, AttributeWithVisibility):
            result.append(item)
        elif isinstance(item, dict):
            try:
                key = normalizer(item.get("key", ""))
                result.append(
                    AttributeWithVisibility(
                        key=key,
                        value=str(item.get("value", "")),
                        details=item.get("details"),
                        known_by_protagonist=item.get(
                            "known", item.get("known_by_protagonist", False)
                        ),
                    )
                )
            except ValueError as e:
                logger.warning(f"[_parse_attributes] Skipping invalid attribute: {e}")

    return result


# =============================================================================
# BASE ENTITY DATA
# =============================================================================


class EntityData(BaseModel):
    """Base class for entity data with attributes."""

    name: Name
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)

    def get_attribute(self, key: AttributeKey) -> str | None:
        """Get an attribute value by key"""
        for attr in self.attributes:
            if attr.key == key:
                return attr.value
        return None

    def set_attribute(self, key: AttributeKey, value: str, known: bool = True) -> None:
        """Set or update an attribute"""
        for attr in self.attributes:
            if attr.key == key:
                attr.value = value
                attr.known_by_protagonist = known
                return
        self.attributes.append(
            AttributeWithVisibility(key=key, value=value, known_by_protagonist=known)
        )


# =============================================================================
# WORLD / STATION
# =============================================================================


class WorldData(BaseModel):
    """The space station/habitat - top-level location"""

    name: Name
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    sectors: list[str] = Field(..., min_length=2, max_length=10)
    founding_cycle: Cycle = Field(default=-5000, le=-100)

    @field_validator("attributes", mode="before")
    @classmethod
    def _parse_attrs(cls, v: Any) -> list[AttributeWithVisibility]:
        if isinstance(v, list):
            return _parse_attributes(v, EntityType.LOCATION)
        return v


# =============================================================================
# PROTAGONIST
# =============================================================================


class ProtagonistData(BaseModel):
    """The player character"""

    name: Tag = "Valentin"
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list, min_length=2, max_length=6)

    @field_validator("attributes", mode="before")
    @classmethod
    def _parse_attrs(cls, v: Any) -> list[AttributeWithVisibility]:
        if isinstance(v, list):
            return _parse_attributes(v, EntityType.PROTAGONIST)
        return v

    @classmethod
    def create(
        cls,
        name: str = "Valentin",
        origin_location: str = "",
        departure_reason: DepartureReason = DepartureReason.FRESH_START,
        backstory: str = "",
        hobbies: list[str] | None = None,
        skills: list[Skill] | None = None,
        initial_credits: int = 1400,
        initial_energy: float = 3.0,
        initial_morale: float = 3.0,
        initial_health: float = 4.0,
    ) -> "ProtagonistData":
        """Factory with convenient parameter names"""
        attrs = [
            {"key": "credits", "value": str(initial_credits), "known": True},
            {"key": "energy", "value": str(initial_energy), "known": True},
            {"key": "morale", "value": str(initial_morale), "known": True},
            {"key": "health", "value": str(initial_health), "known": True},
            {"key": "origin", "value": origin_location, "known": True},
            {"key": "departure_reason", "value": departure_reason.value, "known": True},
        ]
        if hobbies:
            attrs.append(
                {"key": "hobbies", "value": json.dumps(hobbies), "known": True}
            )
        if backstory:
            attrs.append({"key": "backstory", "value": backstory, "known": True})

        return cls(name=name, attributes=attrs, skills=skills or [])


# =============================================================================
# PERSONAL AI
# =============================================================================


class PersonalAIData(BaseModel):
    """The protagonist's AI companion"""

    name: Label
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    creator_ref: EntityRef | None = None

    @field_validator("attributes", mode="before")
    @classmethod
    def _parse_attrs(cls, v: Any) -> list[AttributeWithVisibility]:
        if isinstance(v, list):
            return _parse_attributes(v, EntityType.AI)
        return v

    @classmethod
    def create(
        cls,
        name: str,
        voice_description: str = "",
        personality_traits: list[str] | None = None,
        substrate: str = "personal_device",
        quirk: str = "",
        creator_ref: str | None = None,
    ) -> "PersonalAIData":
        """Factory with convenient parameter names"""
        attrs = []
        if voice_description:
            attrs.append({"key": "voice", "value": voice_description, "known": True})
        if quirk:
            attrs.append({"key": "quirk", "value": quirk, "known": True})
        if personality_traits:
            attrs.append(
                {
                    "key": "traits",
                    "value": json.dumps(personality_traits),
                    "known": False,
                }
            )
        attrs.append({"key": "substrate", "value": substrate, "known": True})

        return cls(name=name, attributes=attrs, creator_ref=creator_ref)


# =============================================================================
# CHARACTER (NPC)
# =============================================================================


class CharacterData(BaseModel):
    """An NPC in the world."""

    name: Name
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    workplace_ref: EntityRef | None = None
    residence_ref: EntityRef | None = None
    known_by_protagonist: bool = False
    unknown_name: str | None = None

    @field_validator("attributes", mode="before")
    @classmethod
    def _parse_attrs(cls, v: Any) -> list[AttributeWithVisibility]:
        if isinstance(v, list):
            return _parse_attributes(v, EntityType.CHARACTER)
        return v

    @classmethod
    def create(
        cls,
        name: str,
        species: str = "human",
        gender: str = "non-spécifié",
        pronouns: str = "iel",
        age: int | None = None,
        description: str = "",
        traits: list[str] | None = None,
        occupation: str = "",
        origin: str | None = None,
        arrival_cycle: int = -100,
        mood: str | None = None,
        motivation: str | None = None,
        arcs: list[dict] | None = None,
        workplace_ref: str | None = None,
        residence_ref: str | None = None,
        known_by_protagonist: bool = False,
        romantic_potential: bool = False,
        is_mandatory: bool = False,
    ) -> "CharacterData":
        """Factory with convenient parameter names"""
        attrs = [
            {"key": "species", "value": species, "known": True},
            {"key": "gender", "value": gender, "known": True},
            {"key": "pronouns", "value": pronouns, "known": True},
            {"key": "description", "value": description, "known": True},
        ]

        if age:
            attrs.append(
                {"key": "age", "value": str(age), "known": known_by_protagonist}
            )
        if traits:
            attrs.append(
                {
                    "key": "traits",
                    "value": json.dumps(traits),
                    "known": known_by_protagonist,
                }
            )
        if occupation:
            attrs.append(
                {
                    "key": "occupation",
                    "value": occupation,
                    "known": known_by_protagonist,
                }
            )
        if mood:
            attrs.append({"key": "mood", "value": mood, "known": True})
        if origin:
            attrs.append({"key": "origin", "value": origin, "known": False})
        if arrival_cycle:
            attrs.append(
                {"key": "arrival_cycle", "value": str(arrival_cycle), "known": False}
            )
        if motivation:
            attrs.append({"key": "motivation", "value": motivation, "known": False})
        if arcs:
            attrs.append({"key": "arcs", "value": json.dumps(arcs), "known": False})

        # Meta attributes (never visible to protagonist)
        attrs.append(
            {
                "key": "romantic_potential",
                "value": str(romantic_potential).lower(),
                "known": False,
            }
        )
        attrs.append(
            {"key": "is_mandatory", "value": str(is_mandatory).lower(), "known": False}
        )

        return cls(
            name=name,
            attributes=attrs,
            workplace_ref=workplace_ref,
            residence_ref=residence_ref,
            known_by_protagonist=known_by_protagonist,
        )


# =============================================================================
# LOCATION
# =============================================================================


class LocationData(BaseModel):
    """A place in the station"""

    name: Name
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    parent_location_ref: EntityRef | None = None

    @field_validator("attributes", mode="before")
    @classmethod
    def _parse_attrs(cls, v: Any) -> list[AttributeWithVisibility]:
        if isinstance(v, list):
            return _parse_attributes(v, EntityType.LOCATION)
        return v

    @classmethod
    def create(
        cls,
        name: str,
        location_type: str = "",
        sector: str | None = None,
        description: str = "",
        atmosphere: str = "",
        parent_location_ref: str | None = None,
        accessible: bool = True,
        notable_features: list[str] | None = None,
        typical_crowd: str | None = None,
        operating_hours: str | None = None,
        price_range: str | None = None,
    ) -> "LocationData":
        """Factory with convenient parameter names"""
        attrs = [
            {"key": "description", "value": description, "known": True},
            {"key": "atmosphere", "value": atmosphere, "known": True},
            {"key": "location_type", "value": location_type, "known": True},
            {"key": "accessible", "value": str(accessible).lower(), "known": True},
        ]

        if sector:
            attrs.append({"key": "sector", "value": sector, "known": True})
        if notable_features:
            attrs.append(
                {
                    "key": "notable_features",
                    "value": json.dumps(notable_features),
                    "known": True,
                }
            )
        if typical_crowd:
            attrs.append(
                {"key": "typical_crowd", "value": typical_crowd, "known": True}
            )
        if operating_hours:
            attrs.append(
                {"key": "operating_hours", "value": operating_hours, "known": True}
            )
        if price_range:
            attrs.append({"key": "price_range", "value": price_range, "known": True})

        return cls(name=name, attributes=attrs, parent_location_ref=parent_location_ref)


# =============================================================================
# OBJECT
# =============================================================================


class ObjectData(BaseModel):
    """An item that can be owned"""

    name: Name
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    quantity: int = Field(default=1, ge=1)

    @field_validator("attributes", mode="before")
    @classmethod
    def _parse_attrs(cls, v: Any) -> list[AttributeWithVisibility]:
        if isinstance(v, list):
            return _parse_attributes(v, EntityType.OBJECT)
        return v

    @classmethod
    def create(
        cls,
        name: str,
        category: str = "misc",
        description: str = "",
        transportable: bool = True,
        stackable: bool = False,
        quantity: int = 1,
        base_value: int = 0,
        condition: str | None = None,
        emotional_significance: str | None = None,
    ) -> "ObjectData":
        """Factory with convenient parameter names"""
        attrs = [
            {"key": "category", "value": category, "known": True},
            {"key": "description", "value": description, "known": True},
            {
                "key": "transportable",
                "value": str(transportable).lower(),
                "known": True,
            },
            {"key": "stackable", "value": str(stackable).lower(), "known": True},
            {"key": "base_value", "value": str(base_value), "known": True},
        ]

        if condition:
            attrs.append({"key": "condition", "value": condition, "known": True})
        if emotional_significance:
            attrs.append(
                {
                    "key": "emotional_significance",
                    "value": emotional_significance,
                    "known": True,
                }
            )

        return cls(name=name, attributes=attrs, quantity=quantity)


# =============================================================================
# ORGANIZATION
# =============================================================================


class OrganizationData(BaseModel):
    """A company, faction, or group"""

    name: Name
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    headquarters_ref: EntityRef | None = None

    @field_validator("attributes", mode="before")
    @classmethod
    def _parse_attrs(cls, v: Any) -> list[AttributeWithVisibility]:
        if isinstance(v, list):
            return _parse_attributes(v, EntityType.ORGANIZATION)
        return v

    @classmethod
    def create(
        cls,
        name: str,
        org_type: str = "",
        domain: str = "",
        size: str = "medium",
        description: str = "",
        reputation: str = "",
        headquarters_ref: str | None = None,
        founding_cycle: int | None = None,
        public_facade: str | None = None,
        true_purpose: str | None = None,
        influence_level: str | None = None,
        is_employer: bool = False,
    ) -> "OrganizationData":
        """Factory with convenient parameter names"""
        attrs = [
            {"key": "org_type", "value": org_type, "known": True},
            {"key": "domain", "value": domain, "known": True},
            {"key": "size", "value": size, "known": True},
            {"key": "description", "value": description, "known": True},
            {"key": "reputation", "value": reputation, "known": True},
        ]

        if founding_cycle:
            attrs.append(
                {"key": "founding_cycle", "value": str(founding_cycle), "known": True}
            )
        if public_facade:
            attrs.append(
                {"key": "public_facade", "value": public_facade, "known": True}
            )
        if true_purpose:
            attrs.append({"key": "true_purpose", "value": true_purpose, "known": False})
        if influence_level:
            attrs.append(
                {"key": "influence_level", "value": influence_level, "known": True}
            )

        # Meta
        attrs.append(
            {"key": "is_employer", "value": str(is_employer).lower(), "known": False}
        )

        return cls(name=name, attributes=attrs, headquarters_ref=headquarters_ref)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def attrs_to_dict(attributes: list[AttributeWithVisibility]) -> dict:
    """Convert attribute list to dict for easy access"""
    return {attr.key.value: attr.value for attr in attributes}


def attrs_from_dict(
    data: dict, entity_type: EntityType, known_by_protagonist: bool = True
) -> list[AttributeWithVisibility]:
    """Convert dict to attribute list with entity-specific normalization"""
    return _parse_attributes(
        [
            {"key": k, "value": v, "known": known_by_protagonist}
            for k, v in data.items()
        ],
        entity_type,
    )
