"""
LDVELH - Entity Schema Models (EAV Architecture)
Simplified models - all type-specific data goes through attributes
"""

import logging
from pydantic import BaseModel, Field, field_validator

from .core import (
    AttributeKey,
    AttributeWithVisibility,
    Cycle,
    DepartureReason,
    EntityRef,
    Label,
    Name,
    Skill,
    Tag,
)

logger = logging.getLogger(__name__)


# =============================================================================
# BASE ENTITY DATA (all types use this pattern)
# =============================================================================


class EntityData(BaseModel):
    """
    Base class for entity data.
    All type-specific information is stored as attributes.
    """

    name: Name  # 100 chars
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

    name: Name  # 100 chars
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    sectors: list[str] = Field(..., min_length=2, max_length=10)
    founding_cycle: Cycle = Field(
        default=-5000,
        le=-100,
        description="When station was founded. -5000 = ~13 years ago",
    )

    # Convenience properties
    @property
    def station_type(self) -> str | None:
        return self._get_attr("location_type")

    @property
    def population(self) -> int | None:
        val = self._get_attr("population")
        return int(val) if val else None

    @property
    def atmosphere(self) -> str | None:
        return self._get_attr("atmosphere")

    @property
    def description(self) -> str | None:
        return self._get_attr("description")

    def _get_attr(self, key: str) -> str | None:
        for attr in self.attributes:
            if attr.key.value == key:
                return attr.value
        return None


# =============================================================================
# PROTAGONIST
# =============================================================================


class ProtagonistData(BaseModel):
    """The player character - uses attributes for all state"""

    name: Tag = "Valentin"  # 50 chars
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list, min_length=2, max_length=6)

    # Required attributes that must be provided
    @field_validator("attributes")
    @classmethod
    def validate_required_attrs(cls, v: list) -> list:
        """Ensure critical attributes are present"""
        keys = {attr.key for attr in v}
        required = {
            AttributeKey.CREDITS,
            AttributeKey.ENERGY,
            AttributeKey.MORALE,
            AttributeKey.HEALTH,
        }
        missing = required - keys
        if missing:
            logger.warning(
                f"[Protagonist] Missing required attributes: {[k.value for k in missing]}"
            )
        return v

    # Convenience factory
    @classmethod
    def create(
        cls,
        name: str = "Valentin",
        origin_location: str = "",
        departure_reason: DepartureReason = DepartureReason.FRESH_START,
        departure_story: str = "",
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
            AttributeWithVisibility(
                key=AttributeKey.CREDITS,
                value=str(initial_credits),
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.ENERGY,
                value=str(initial_energy),
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.MORALE,
                value=str(initial_morale),
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.HEALTH,
                value=str(initial_health),
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.ORIGIN,
                value=origin_location,
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.DEPARTURE_REASON,
                value=departure_reason.value,
                known_by_protagonist=True,
            ),
        ]
        if hobbies:
            import json

            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.HOBBIES,
                    value=json.dumps(hobbies),
                    known_by_protagonist=True,
                )
            )
        if backstory:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.DESCRIPTION,
                    value=backstory,
                    known_by_protagonist=True,
                )
            )

        return cls(name=name, attributes=attrs, skills=skills or [])


# =============================================================================
# PERSONAL AI
# =============================================================================


class PersonalAIData(BaseModel):
    """The protagonist's AI companion"""

    name: Label  # 30 chars
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    creator_ref: EntityRef | None = None  # FK reference

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
        import json

        attrs = []
        if voice_description:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.VOICE,
                    value=voice_description,
                    known_by_protagonist=True,
                )
            )
        if quirk:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.QUIRK, value=quirk, known_by_protagonist=True
                )
            )
        if personality_traits:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.DESCRIPTION,
                    value=json.dumps(personality_traits),
                    known_by_protagonist=True,
                )
            )

        return cls(name=name, attributes=attrs, creator_ref=creator_ref)


# =============================================================================
# CHARACTER (NPC)
# =============================================================================


class CharacterData(BaseModel):
    """
    An NPC in the world.
    All character-specific data stored as attributes.
    """

    name: Name  # 100 chars
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)

    # FK references (resolved by populator)
    workplace_ref: EntityRef | None = None
    residence_ref: EntityRef | None = None

    @classmethod
    def create(
        cls,
        name: str,
        species: str = "human",
        gender: str = "non-spécifié",
        pronouns: str = "iel",
        age: int | None = None,
        physical_description: str = "",
        personality_traits: list[str] | None = None,
        occupation: str = "",
        origin_location: str | None = None,
        station_arrival_cycle: int = -100,
        mood: str | None = None,
        arcs: list[dict] | None = None,
        workplace_ref: str | None = None,
        residence_ref: str | None = None,
        known_by_protagonist: bool = True,
    ) -> "CharacterData":
        """Factory with convenient parameter names"""
        import json
        from .core import get_attribute_visibility, AttributeVisibility

        attrs = []

        def add_attr(key: AttributeKey, value: str, force_known: bool | None = None):
            if force_known is not None:
                known = force_known
            else:
                vis = get_attribute_visibility(key)
                known = vis == AttributeVisibility.ALWAYS or (
                    vis == AttributeVisibility.CONDITIONAL and known_by_protagonist
                )
            attrs.append(
                AttributeWithVisibility(
                    key=key, value=value, known_by_protagonist=known
                )
            )

        # Observable attributes (ALWAYS visible)
        add_attr(AttributeKey.DESCRIPTION, physical_description, True)
        if mood:
            add_attr(AttributeKey.MOOD, mood, True)

        # Conditionally visible
        if species:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.DESCRIPTION,
                    value=f"species:{species}",
                    details={"species": species},
                    known_by_protagonist=known_by_protagonist,
                )
            )
        # Store species/gender/pronouns in details of description or separate
        # Actually, let's add dedicated handling

        # Build attributes properly
        attrs = [
            AttributeWithVisibility(
                key=AttributeKey.DESCRIPTION,
                value=physical_description,
                known_by_protagonist=True,
            ),
        ]

        if personality_traits:
            # Traits stored as JSON, visible if meeting the character
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.QUIRK,
                    value=json.dumps(personality_traits),
                    known_by_protagonist=known_by_protagonist,
                )
            )

        if mood:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.MOOD, value=mood, known_by_protagonist=True
                )
            )

        if age:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.AGE,
                    value=str(age),
                    known_by_protagonist=known_by_protagonist,
                )
            )

        if origin_location:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.ORIGIN,
                    value=origin_location,
                    known_by_protagonist=False,  # Usually not known
                )
            )

        if arcs:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.ARCS,
                    value=json.dumps(arcs),
                    known_by_protagonist=False,  # Meta-narrative
                )
            )

        # Store structured character data in details
        base_details = {
            "species": species,
            "gender": gender,
            "pronouns": pronouns,
            "occupation": occupation,
            "arrival_cycle": station_arrival_cycle,
        }
        attrs[0].details = base_details

        return cls(
            name=name,
            attributes=attrs,
            workplace_ref=workplace_ref,
            residence_ref=residence_ref,
        )


# =============================================================================
# LOCATION
# =============================================================================


class LocationData(BaseModel):
    """A place in the station"""

    name: Name  # 100 chars
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)

    # FK reference
    parent_location_ref: EntityRef | None = None

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
        import json

        attrs = [
            AttributeWithVisibility(
                key=AttributeKey.DESCRIPTION,
                value=description,
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.ATMOSPHERE, value=atmosphere, known_by_protagonist=True
            ),
        ]

        # Store structured location data in details of first attr
        attrs[0].details = {
            "location_type": location_type,
            "sector": sector,
            "accessible": accessible,
        }

        if notable_features:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.NOTABLE_FEATURES,
                    value=json.dumps(notable_features),
                    known_by_protagonist=True,
                )
            )

        if typical_crowd:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.TYPICAL_CROWD,
                    value=typical_crowd,
                    known_by_protagonist=True,
                )
            )

        if operating_hours:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.OPERATING_HOURS,
                    value=operating_hours,
                    known_by_protagonist=True,
                )
            )

        if price_range:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.PRICE_RANGE,
                    value=price_range,
                    known_by_protagonist=True,
                )
            )

        return cls(name=name, attributes=attrs, parent_location_ref=parent_location_ref)


# =============================================================================
# OBJECT
# =============================================================================


class ObjectData(BaseModel):
    """An item that can be owned"""

    name: Name  # 100 chars
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)
    quantity: int = Field(default=1, ge=1)

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
            AttributeWithVisibility(
                key=AttributeKey.DESCRIPTION,
                value=description,
                known_by_protagonist=True,
            ),
        ]

        # Store structured object data in details
        attrs[0].details = {
            "category": category,
            "transportable": transportable,
            "stackable": stackable,
            "base_value": base_value,
        }

        if condition:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.CONDITION,
                    value=condition,
                    known_by_protagonist=True,
                )
            )

        if emotional_significance:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.EMOTIONAL_SIGNIFICANCE,
                    value=emotional_significance,
                    known_by_protagonist=True,
                )
            )

        return cls(name=name, attributes=attrs, quantity=quantity)


# =============================================================================
# ORGANIZATION
# =============================================================================


class OrganizationData(BaseModel):
    """A company, faction, or group"""

    name: Name  # 100 chars
    attributes: list[AttributeWithVisibility] = Field(default_factory=list)

    # FK reference
    headquarters_ref: EntityRef | None = None

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
    ) -> "OrganizationData":
        """Factory with convenient parameter names"""
        attrs = [
            AttributeWithVisibility(
                key=AttributeKey.DESCRIPTION,
                value=description,
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.REPUTATION, value=reputation, known_by_protagonist=True
            ),
        ]

        # Store structured org data in details
        attrs[0].details = {
            "org_type": org_type,
            "domain": domain,
            "size": size,
            "founding_cycle": founding_cycle,
        }

        if public_facade:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.PUBLIC_FACADE,
                    value=public_facade,
                    known_by_protagonist=True,
                )
            )

        if true_purpose:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.TRUE_PURPOSE,
                    value=true_purpose,
                    known_by_protagonist=False,  # Secret
                )
            )

        if influence_level:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.INFLUENCE_LEVEL,
                    value=influence_level,
                    known_by_protagonist=True,
                )
            )

        return cls(name=name, attributes=attrs, headquarters_ref=headquarters_ref)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def attrs_to_dict(attributes: list[AttributeWithVisibility]) -> dict:
    """Convert attribute list to dict for easy access"""
    return {attr.key.value: attr.value for attr in attributes}


def attrs_from_dict(
    data: dict, known_by_protagonist: bool = True
) -> list[AttributeWithVisibility]:
    """Convert dict to attribute list"""
    from .synonyms import normalize_key
    import json

    attrs = []
    for key, value in data.items():
        try:
            normalized_key = normalize_key(key)
            str_value = (
                json.dumps(value) if isinstance(value, (list, dict)) else str(value)
            )
            attrs.append(
                AttributeWithVisibility(
                    key=normalized_key,
                    value=str_value,
                    known_by_protagonist=known_by_protagonist,
                )
            )
        except ValueError:
            logger.warning(f"[attrs_from_dict] Unknown attribute key: {key}")
    return attrs
