"""
LDVELH - Engine Schema Models
Defines engine types, world config, character data, and roll models.
"""

import logging
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from domain.game import ARBITER_DIFFICULTIES, DEFAULT_DIFFICULTY


# =============================================================================
# ENGINE TYPE
# =============================================================================


class EngineType(str, Enum):
    NONE = "none"
    NARRATIVE = "narrative"
    FATE_CORE = "fate_core"
    D6 = "d6"


logger = logging.getLogger(__name__)


def coerce_engine(value: "str | EngineType | None", game_id) -> EngineType:
    """Stored engine value -> EngineType; an unknown or empty one is treated as 'none'.

    The single graceful path for data read back from the DB (#91): a game saved with an
    engine we do not know still loads. The warning names the game only, never the stored value.
    """
    if not value:
        return EngineType.NONE
    try:
        return EngineType(value)
    except ValueError:
        logger.warning("Unknown engine on game %s, treated as 'none'", game_id)
        return EngineType.NONE


# =============================================================================
# WORLD CONFIG
# =============================================================================


class WorldConfig(BaseModel):
    """World configuration set during game creation wizard."""

    genre: str  # genre slug (presets: sci_fi, dark_fantasy, cosmic_horror, cyberpunk)
    difficulty: Literal[*ARBITER_DIFFICULTIES] = DEFAULT_DIFFICULTY
    hardcore: bool = False
    lore: str | None = None
    custom_rules: str | None = None


# =============================================================================
# FATE CORE CHARACTER
# =============================================================================


class FateAspect(BaseModel):
    """A single Fate Core aspect."""

    name: str
    type: str = "other"  # high_concept, trouble, other


class FateStunt(BaseModel):
    """A single Fate Core stunt."""

    name: str
    description: str


class FateConsequences(BaseModel):
    """Fate Core consequence slots."""

    mild: str | None = None
    moderate: str | None = None
    severe: str | None = None
    extreme: str | None = None


class FateCharacterData(BaseModel):
    """Fate Core protagonist character data."""

    aspects: list[FateAspect] = Field(default_factory=list)
    stunts: list[FateStunt] = Field(default_factory=list)
    stress_physical: list[bool] = Field(
        default_factory=lambda: [False, False, False, False]
    )
    stress_mental: list[bool] = Field(
        default_factory=lambda: [False, False, False, False]
    )
    consequences: FateConsequences = Field(default_factory=FateConsequences)
    fate_points: int = 3
    refresh: int = 3


class FateSkill(BaseModel):
    """A single Fate Core skill."""

    name: str
    level: int = 0  # 0=Mediocre to 8=Legendary
    custom: bool = False


# =============================================================================
# D6 SYSTEM CHARACTER
# =============================================================================


class D6WoundLevel(BaseModel):
    """D6 System wound tracking."""

    stunned: bool = False
    wounded: bool = False
    severely_wounded: bool = False
    incapacitated: bool = False
    mortally_wounded: bool = False


class D6CharacterData(BaseModel):
    """D6 System protagonist character data."""

    attributes: dict[str, str] = Field(
        default_factory=dict
    )  # {"Dexterite": "3D+2", "Force": "2D"}
    wounds: D6WoundLevel = Field(default_factory=D6WoundLevel)
    force_points: int = 3


class D6Skill(BaseModel):
    """A single D6 System skill."""

    attribute: str  # parent attribute
    name: str
    dice_value: str  # "3D+2"
    custom: bool = False


# =============================================================================
# NARRATIVE ENGINE CHARACTER
# =============================================================================


class NarrativeTrait(BaseModel):
    """A single narrative trait."""

    name: str
    description: str | None = None
    active: bool = True
    replaced_by: str | None = None
    created_cycle: int = 1


class NarrativeCharacterData(BaseModel):
    """Narrative engine protagonist data (traits stored in traits_narrative table)."""

    pass  # Traits live in the dedicated table


# =============================================================================
# NPC ENGINE DATA (lighter than protagonist — JSONB skills)
# =============================================================================


class NPCFateData(BaseModel):
    """Fate Core stats for an NPC."""

    aspects: list[FateAspect] = Field(default_factory=list)
    skills: dict[str, int] = Field(default_factory=dict)  # {"Combat": 3, "Athlétisme": 2}
    stunts: list[FateStunt] = Field(default_factory=list)
    stress_physical: list[bool] = Field(default_factory=lambda: [False, False])
    stress_mental: list[bool] = Field(default_factory=lambda: [False, False])
    consequences: dict[str, str | None] = Field(default_factory=dict)
    fate_points: int = 1


class NPCD6Data(BaseModel):
    """D6 System stats for an NPC."""

    attributes: dict[str, str] = Field(default_factory=dict)  # {"Dexterite": "3D"}
    skills: dict[str, str] = Field(default_factory=dict)  # {"Esquive": "4D"}
    wounds: D6WoundLevel = Field(default_factory=D6WoundLevel)
    force_points: int = 0


class NPCNarrativeData(BaseModel):
    """Narrative engine traits for an NPC."""

    traits: list[NarrativeTrait] = Field(default_factory=list)


# =============================================================================
# MECHANICAL DECISION (from mechanical LLM)
# =============================================================================


class MechanicalDecision(BaseModel):
    """Output of the mechanical LLM: whether a test is needed and parameters."""

    requires_test: bool
    skill: str | None = None
    # Fate: ladder level; D6: dice code such as "3D+1". The engine replaces it with
    # the character sheet value when the skill is known (#13).
    skill_value: int | str | None = None
    difficulty: int | None = None
    difficulty_label: str | None = None
    opposition: dict | None = None  # {npc_name, skill, skill_value}
    reason: str | None = None


# =============================================================================
# ROLL RESULT (from engine dice rolling)
# =============================================================================


class RollResult(BaseModel):
    """Result of a dice roll from the engine."""

    dice: list[int]  # raw dice values
    total: int
    skill_total: int  # total + skill bonus
    opposition_total: int | None = None
    outcome: str  # success, failure, tie, success_with_style
    shifts: int | None = None  # Fate Core: margin of success/failure
    complication: bool = False  # D6: wild die complication
    details: dict = Field(default_factory=dict)


# =============================================================================
# MECHANICAL RESULT (wraps decision + roll for pipeline)
# =============================================================================


class MechanicalResult(BaseModel):
    """Combined result of the mechanical step: decision + optional roll."""

    decision: MechanicalDecision
    roll: RollResult | None = None
    cost: dict | None = None  # LLM cost tracking

    @property
    def outcome(self) -> str | None:
        return self.roll.outcome if self.roll else None

    def to_db(self) -> dict:
        """Serialize for mechanic_rolls table insertion."""
        if not self.roll:
            return {}
        return {
            "engine": "",  # filled by caller
            "skill_used": self.decision.skill,
            "roll_details": self.roll.model_dump(),
            "outcome": self.roll.outcome,
            "complication": self.roll.complication,
        }
