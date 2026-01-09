"""
LDVELH - Relations Schema
Modèles pour les relations entre entités
"""

from pydantic import BaseModel, Field

from .core import CertaintyLevel, Cycle, EntityRef, RelationType

# =============================================================================
# TYPED RELATION DATA
# =============================================================================


class RelationSocialData(BaseModel):
    """Data specific to social relations (knows, friend_of, enemy_of, family_of, romantic)"""

    level: int | None = Field(default=None, ge=0, le=10, description="Relationship strength")
    context: str | None = Field(default=None, max_length=200, description="How they met, shared history")
    romantic_stage: int | None = Field(
        default=None,
        ge=0,
        le=6,
        description="0=strangers, 1=acquaintance, 2=interest, 3=dating, 4=committed, 5=deep bond, 6=life partners",
    )
    family_bond: str | None = Field(
        default=None,
        max_length=30,
        description="parent, child, sibling, spouse, cousin, uncle, aunt, grandparent, etc.",
    )


class RelationProfessionalData(BaseModel):
    """Data specific to professional relations (employed_by, colleague_of, manages)"""

    position: str | None = Field(default=None, max_length=100)
    position_start_cycle: Cycle | None = Field(default=None, description="When this position started")
    part_time: bool = Field(default=False)


class RelationSpatialData(BaseModel):
    """Data specific to spatial relations (frequents, lives_at, located_in, works_at)"""

    regularity: str | None = Field(
        default=None, max_length=30, description="daily, often, sometimes, rarely, weekly, monthly"
    )
    time_of_day: str | None = Field(
        default=None, max_length=50, description="morning, evening, night, weekend, weekdays, etc."
    )


class RelationOwnershipData(BaseModel):
    """Data specific to ownership relations (owns, owes_to)"""

    quantity: int = Field(default=1, ge=0)
    origin: str | None = Field(
        default=None, max_length=30, description="purchase, gift, theft, found, crafted, inheritance, loan"
    )
    amount: int | None = Field(default=None, ge=0, description="Purchase price or debt amount in credits")
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
    source_info: str | None = Field(default=None, max_length=255, description="How this info was learned")

    # Type-specific data (use the appropriate one based on relation_type)
    social: RelationSocialData | None = None
    professional: RelationProfessionalData | None = None
    spatial: RelationSpatialData | None = None
    ownership: RelationOwnershipData | None = None

    # Convenience properties for backwards compatibility and direct access
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
# RELATION GROUPINGS
# =============================================================================

SOCIAL_RELATIONS = frozenset(
    [RelationType.KNOWS, RelationType.FRIEND_OF, RelationType.ENEMY_OF, RelationType.FAMILY_OF, RelationType.ROMANTIC]
)

PROFESSIONAL_RELATIONS = frozenset([RelationType.EMPLOYED_BY, RelationType.COLLEAGUE_OF, RelationType.MANAGES])

SPATIAL_RELATIONS = frozenset(
    [RelationType.FREQUENTS, RelationType.LIVES_AT, RelationType.LOCATED_IN, RelationType.WORKS_AT]
)

OWNERSHIP_RELATIONS = frozenset([RelationType.OWNS, RelationType.OWES_TO])


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


def create_relation(source: str, target: str, rel_type: RelationType, **kwargs) -> RelationData:
    """
    Factory function to create RelationData with appropriate typed data.
    Automatically routes kwargs to the correct sub-model.

    Usage:
        create_relation("Valentin", "Justine", RelationType.KNOWS, level=3, context="Voisins")
        create_relation("Valentin", "Symbiose", RelationType.EMPLOYED_BY, position="Architecte IA")
        create_relation("Valentin", "Apt 4-12", RelationType.LIVES_AT, regularity="daily")
        create_relation("Valentin", "Livre", RelationType.OWNS, quantity=1, origin="purchase", amount=200)
    """
    base = {
        "source_ref": source,
        "target_ref": target,
        "relation_type": rel_type,
        "certainty": kwargs.pop("certainty", CertaintyLevel.CERTAIN),
        "is_true": kwargs.pop("is_true", True),
        "source_info": kwargs.pop("source_info", None),
    }

    if rel_type in SOCIAL_RELATIONS:
        social_fields = {"level", "context", "romantic_stage", "family_bond"}
        social_data = {k: v for k, v in kwargs.items() if k in social_fields}
        if social_data:
            base["social"] = RelationSocialData(**social_data)

    elif rel_type in PROFESSIONAL_RELATIONS:
        prof_fields = {"position", "position_start_cycle", "part_time"}
        prof_data = {k: v for k, v in kwargs.items() if k in prof_fields}
        if prof_data:
            base["professional"] = RelationProfessionalData(**prof_data)

    elif rel_type in SPATIAL_RELATIONS:
        spatial_fields = {"regularity", "time_of_day"}
        spatial_data = {k: v for k, v in kwargs.items() if k in spatial_fields}
        if spatial_data:
            base["spatial"] = RelationSpatialData(**spatial_data)

    elif rel_type in OWNERSHIP_RELATIONS:
        own_fields = {"quantity", "origin", "amount", "acquisition_cycle"}
        own_data = {k: v for k, v in kwargs.items() if k in own_fields}
        if own_data:
            base["ownership"] = RelationOwnershipData(**own_data)

    return RelationData(**base)
