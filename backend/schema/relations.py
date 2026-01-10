"""
LDVELH - Relations Schema
Modèles pour les relations entre entités
"""

from pydantic import BaseModel, Field, field_validator

from .core import (
    CertaintyLevel,
    Cycle,
    EntityRef,
    Label,
    Name,
    RelationCategory,
    RelationType,
    ShortText,
    Tag,
    normalize_certainty,
    normalize_relation_type,
)

# =============================================================================
# TYPED RELATION DATA
# =============================================================================


class RelationSocialData(BaseModel):
    """Data specific to social relations (knows, friend_of, enemy_of, family_of, romantic)"""

    level: int | None = Field(
        default=None, ge=0, le=10, description="Relationship strength"
    )
    context: ShortText | None = None  # 200 chars - How they met, shared history
    romantic_stage: int | None = Field(
        default=None,
        ge=0,
        le=6,
        description="0=strangers, 1=acquaintance, 2=interest, 3=dating, 4=committed, 5=deep bond, 6=life partners",
    )
    family_bond: Label | None = None  # 30 chars - parent, child, sibling, etc.


class RelationProfessionalData(BaseModel):
    """Data specific to professional relations (employed_by, colleague_of, manages)"""

    position: Name | None = None  # 100 chars
    position_start_cycle: Cycle | None = Field(
        default=None, description="When this position started"
    )
    part_time: bool = Field(default=False)


class RelationSpatialData(BaseModel):
    """Data specific to spatial relations (frequents, lives_at, located_in, works_at)"""

    regularity: Label | None = None  # 30 chars - daily, often, sometimes, rarely
    time_of_day: Tag | None = None  # 50 chars - morning, evening, night, weekend


class RelationOwnershipData(BaseModel):
    """Data specific to ownership relations (owns, owes_to)"""

    quantity: int = Field(default=1, ge=0)
    origin: Label | None = None  # 30 chars - purchase, gift, theft, found, crafted
    amount: int | None = Field(
        default=None, ge=0, description="Purchase price or debt amount in credits"
    )
    acquisition_cycle: Cycle | None = Field(default=None, description="When acquired")


# =============================================================================
# RELATION DATA
# =============================================================================


class RelationData(BaseModel):
    """Complete relation between two entities with type-specific data"""

    source_ref: EntityRef
    target_ref: EntityRef
    relation_type: RelationType
    certainty: CertaintyLevel = CertaintyLevel.CERTAIN
    is_true: bool = True
    source_info: ShortText | None = None  # 200 chars - How this info was learned

    # Type-specific data (use the appropriate one based on relation_type)
    social: RelationSocialData | None = None
    professional: RelationProfessionalData | None = None
    spatial: RelationSpatialData | None = None
    ownership: RelationOwnershipData | None = None

    # =========================================================================
    # NORMALIZERS
    # =========================================================================

    @field_validator("relation_type", mode="before")
    @classmethod
    def _normalize_relation_type(cls, v):
        return normalize_relation_type(v)

    @field_validator("certainty", mode="before")
    @classmethod
    def _normalize_certainty(cls, v):
        return normalize_certainty(v)

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def context(self) -> str | None:
        return self.social.context if self.social else None

    @property
    def level(self) -> int | None:
        return self.social.level if self.social else None

    @property
    def position(self) -> str | None:
        return self.professional.position if self.professional else None

    @property
    def regularity(self) -> str | None:
        return self.spatial.regularity if self.spatial else None

    @property
    def quantity(self) -> int | None:
        return self.ownership.quantity if self.ownership else None

    @property
    def amount(self) -> int | None:
        return self.ownership.amount if self.ownership else None


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

# Mapping category -> (field_name, model_class)
_CATEGORY_DATA_CONFIG: dict[RelationCategory, tuple[str, type[BaseModel]]] = {
    RelationCategory.SOCIAL: ("social", RelationSocialData),
    RelationCategory.PROFESSIONAL: ("professional", RelationProfessionalData),
    RelationCategory.SPATIAL: ("spatial", RelationSpatialData),
    RelationCategory.OWNERSHIP: ("ownership", RelationOwnershipData),
}


def create_relation(
    source: str, target: str, rel_type: RelationType, **kwargs
) -> RelationData:
    """
    Factory function to create RelationData with appropriate typed data.
    Automatically routes kwargs to the correct sub-model based on relation category.
    """
    base = {
        "source_ref": source,
        "target_ref": target,
        "relation_type": rel_type,
        "certainty": kwargs.pop("certainty", CertaintyLevel.CERTAIN),
        "is_true": kwargs.pop("is_true", True),
        "source_info": kwargs.pop("source_info", None),
    }

    field_name, model_class = _CATEGORY_DATA_CONFIG[rel_type.category]
    valid_fields = set(model_class.model_fields.keys())
    data = {k: v for k, v in kwargs.items() if k in valid_fields}

    if data:
        base[field_name] = model_class(**data)

    return RelationData(**base)
