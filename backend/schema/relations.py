"""
LDVELH - Relations Schema
Models for relations between entities.
Simplified: level + context instead of typed sub-models.
"""

from pydantic import BaseModel, Field, field_validator

from .core import (
    Cycle,
    EntityRef,
    RelationType,
    ShortText,
    normalize_relation_type,
)


# =============================================================================
# RELATION DATA
# =============================================================================


class RelationData(BaseModel):
    """A relation between two entities, stored in the relations table"""

    source_ref: EntityRef
    target_ref: EntityRef
    relation_type: RelationType
    # Details
    level: int | None = Field(
        default=None, ge=0, le=10, description="Relationship strength (social relations)"
    )
    context: ShortText | None = None  # How they met, shared history
    known_by_protagonist: bool = True
    # Versioning
    start_cycle: Cycle | None = None
    end_cycle: Cycle | None = None
    end_reason: ShortText | None = None

    @field_validator("relation_type", mode="before")
    @classmethod
    def _normalize_relation_type(cls, v):
        return normalize_relation_type(v)
