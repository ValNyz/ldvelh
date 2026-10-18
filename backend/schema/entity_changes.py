"""
LDVELH - Entity field changes (EntityUpdate.changes)

The LLM sends `changes` as a free dict of column -> value. Each column an update may
touch is typed here with the bound of its database column (same text types as the
creation models in entities.py), so an over-long or mistyped value never reaches SQL.
Fields are bounded one by one: an invalid field is dropped (and logged by name), the
valid fields of the same update are kept.
"""

import json
import logging
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ValidationError

from .core import Cycle, EntityType, Label, Mood, Name, ShortText, Tag, Text

logger = logging.getLogger(__name__)


def _str_list(v: Any) -> Any:
    """A JSON array string or a bare string becomes a list (as in entities.py)."""
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return [v]
        return parsed if isinstance(parsed, list) else [v]
    return v


StrList = Annotated[list[str], BeforeValidator(_str_list)]


class CharacterChanges(BaseModel):
    """Columns of `characters` an update may set."""

    known_by_protagonist: bool | None = None
    unknown_name: Name | None = None
    species: Tag | None = None
    gender: Label | None = None
    pronouns: Label | None = None
    age: Label | None = None
    description: Text | None = None
    traits: StrList | None = None
    mood: Mood | None = None
    occupation: Name | None = None
    origin: Name | None = None
    workplace_id: UUID | None = None
    residence_id: UUID | None = None
    romantic_potential: bool | None = None
    is_mandatory: bool | None = None
    ambient: ShortText | None = None


class LocationChanges(BaseModel):
    """Columns of `locations` an update may set."""

    location_type: Tag | None = None
    sector: Tag | None = None
    description: Text | None = None
    atmosphere: Mood | None = None
    accessible: bool | None = None
    notable_features: StrList | None = None
    typical_crowd: ShortText | None = None
    operating_hours: Tag | None = None
    price_range: Tag | None = None
    ambient: ShortText | None = None


class OrganizationChanges(BaseModel):
    """Columns of `organizations` an update may set."""

    org_type: Tag | None = None
    domain: Tag | None = None
    size: Tag | None = None
    description: Text | None = None
    reputation: ShortText | None = None
    headquarters_id: UUID | None = None
    founding_cycle: Cycle | None = None
    ambient: ShortText | None = None


CHANGES_MODELS: dict[EntityType, type[BaseModel]] = {
    EntityType.CHARACTER: CharacterChanges,
    EntityType.LOCATION: LocationChanges,
    EntityType.ORGANIZATION: OrganizationChanges,
}


def bound_changes(entity_type: EntityType | None, changes: dict) -> dict:
    """Keep the settable columns of `entity_type`, each bounded/coerced to its column type.

    Unknown columns and invalid values are dropped field by field; the reason is logged
    with the field name and error type only (no value: it is story text). An entity type
    without a changes model (or None, not resolved yet) returns `changes` unchanged.
    """
    model = CHANGES_MODELS.get(entity_type) if entity_type else None
    if model is None or not changes:
        return changes
    kept = {}
    for key, value in changes.items():
        if key not in model.model_fields:
            logger.debug(f"[Changes] {entity_type.value}.{key}: not an updatable column")
            continue
        try:
            kept[key] = getattr(model.model_validate({key: value}), key)
        except ValidationError as e:
            reasons = ", ".join(err["type"] for err in e.errors(include_input=False))
            logger.warning(f"[Changes] {entity_type.value}.{key} dropped: {reasons}")
    return kept
