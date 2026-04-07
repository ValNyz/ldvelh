"""
Tests for the game engine system.
Covers: engine models, dice rolling, engine data, mechanical prompt.
"""

import json
import random

import pytest

from schema.engine import (
    D6CharacterData,
    D6Skill,
    D6WoundLevel,
    EngineType,
    FateAspect,
    FateCharacterData,
    FateConsequences,
    FateSkill,
    FateStunt,
    MechanicalDecision,
    MechanicalResult,
    NarrativeCharacterData,
    NarrativeTrait,
    NPCD6Data,
    NPCFateData,
    NPCNarrativeData,
    RollResult,
    WorldConfig,
)
from services.engine import get_engine
from services.engine.base import BaseEngine
from services.engine.d6 import D6Engine, parse_dice_code, roll_d6_pool
from services.engine.engine_data import (
    D6_ATTRIBUTES,
    D6_DIFFICULTY_SCALE,
    D6_WOUND_LEVELS,
    FATE_DIFFICULTY_LADDER,
    FATE_SKILLS_BASE,
    get_d6_skills,
    get_fate_skills,
)
from services.engine.fate_core import FATE_LADDER, FateCoreEngine
from services.engine.narrative import NarrativeEngine
from services.engine.none import NoneEngine


# =============================================================================
# ENGINE TYPE + FACTORY
# =============================================================================


class TestEngineType:
    def test_enum_values(self):
        assert EngineType.NONE == "none"
        assert EngineType.NARRATIVE == "narrative"
        assert EngineType.FATE_CORE == "fate_core"
        assert EngineType.D6 == "d6"

    def test_get_engine_returns_correct_type(self):
        assert isinstance(get_engine("none"), NoneEngine)
        assert isinstance(get_engine("narrative"), NarrativeEngine)
        assert isinstance(get_engine("fate_core"), FateCoreEngine)
        assert isinstance(get_engine("d6"), D6Engine)

    def test_get_engine_from_enum(self):
        assert isinstance(get_engine(EngineType.FATE_CORE), FateCoreEngine)

    def test_get_engine_singleton(self):
        e1 = get_engine("fate_core")
        e2 = get_engine("fate_core")
        assert e1 is e2

    def test_get_engine_invalid(self):
        with pytest.raises(ValueError):
            get_engine("unknown_engine")


# =============================================================================
# WORLD CONFIG
# =============================================================================


class TestWorldConfig:
    def test_defaults(self):
        wc = WorldConfig(genre="sci-fi")
        assert wc.difficulty == "moderate"
        assert wc.hardcore is False
        assert wc.lore is None
        assert wc.custom_rules is None

    def test_all_fields(self):
        wc = WorldConfig(
            genre="fantasy",
            difficulty="brutal",
            hardcore=True,
            lore="Ancient magical world",
            custom_rules="No firearms",
        )
        assert wc.genre == "fantasy"
        assert wc.hardcore is True


# =============================================================================
# FATE CORE MODELS
# =============================================================================


class TestFateModels:
    def test_aspect(self):
        a = FateAspect(name="Master Thief", type="high_concept")
        assert a.name == "Master Thief"
        assert a.type == "high_concept"

    def test_stunt(self):
        s = FateStunt(name="Quick Draw", description="+2 when drawing a weapon")
        assert s.description == "+2 when drawing a weapon"

    def test_consequences_default(self):
        c = FateConsequences()
        assert c.mild is None
        assert c.severe is None

    def test_character_data_defaults(self):
        fc = FateCharacterData()
        assert fc.fate_points == 3
        assert fc.refresh == 3
        assert len(fc.stress_physical) == 4
        assert all(not x for x in fc.stress_physical)

    def test_character_data_full(self):
        fc = FateCharacterData(
            aspects=[FateAspect(name="High Concept", type="high_concept")],
            stunts=[FateStunt(name="S1", description="D1")],
            fate_points=5,
        )
        assert len(fc.aspects) == 1
        assert fc.fate_points == 5

    def test_skill(self):
        s = FateSkill(name="Combat", level=4, custom=False)
        assert s.level == 4


class TestNPCFateData:
    def test_defaults(self):
        npc = NPCFateData()
        assert npc.fate_points == 1
        assert len(npc.stress_physical) == 2  # NPCs get 2 boxes
        assert npc.skills == {}

    def test_with_skills(self):
        npc = NPCFateData(skills={"Combat": 3, "Athlétisme": 2})
        assert npc.skills["Combat"] == 3


# =============================================================================
# D6 MODELS
# =============================================================================


class TestD6Models:
    def test_wound_level_defaults(self):
        w = D6WoundLevel()
        assert not w.stunned
        assert not w.mortally_wounded

    def test_character_data_defaults(self):
        dc = D6CharacterData()
        assert dc.force_points == 3
        assert dc.attributes == {}

    def test_skill(self):
        s = D6Skill(attribute="Dextérité", name="Esquive", dice_value="4D+1")
        assert s.dice_value == "4D+1"

    def test_npc_d6_data(self):
        npc = NPCD6Data(
            attributes={"Dexterite": "3D"},
            skills={"Blasters": "4D+1"},
        )
        assert npc.force_points == 0
        assert npc.skills["Blasters"] == "4D+1"


# =============================================================================
# NARRATIVE MODELS
# =============================================================================


class TestNarrativeModels:
    def test_trait(self):
        t = NarrativeTrait(name="Courageous", description="Never backs down")
        assert t.active is True
        assert t.created_cycle == 1

    def test_character_data(self):
        nc = NarrativeCharacterData()
        assert nc is not None  # Empty model, traits in DB

    def test_npc_narrative_data(self):
        npc = NPCNarrativeData(
            traits=[NarrativeTrait(name="Suspicious")]
        )
        assert len(npc.traits) == 1


# =============================================================================
# MECHANICAL DECISION + ROLL RESULT
# =============================================================================


class TestMechanicalModels:
    def test_decision_no_test(self):
        d = MechanicalDecision(requires_test=False, reason="Walking is routine")
        assert not d.requires_test
        assert d.skill is None

    def test_decision_with_test(self):
        d = MechanicalDecision(
            requires_test=True,
            skill="Athlétisme",
            skill_value=3,
            difficulty=2,
            difficulty_label="Correct",
            reason="Climbing the wall",
        )
        assert d.skill == "Athlétisme"

    def test_decision_with_opposition(self):
        d = MechanicalDecision(
            requires_test=True,
            skill="Combat",
            skill_value=4,
            opposition={"npc_name": "Guard", "skill": "Combat", "skill_value": 3},
            reason="Fighting the guard",
        )
        assert d.opposition["npc_name"] == "Guard"

    def test_roll_result(self):
        r = RollResult(
            dice=[-1, 0, 1, 1],
            total=1,
            skill_total=4,
            outcome="success",
            shifts=2,
        )
        assert r.outcome == "success"
        assert not r.complication

    def test_mechanical_result_no_roll(self):
        mr = MechanicalResult(
            decision=MechanicalDecision(requires_test=False),
        )
        assert mr.outcome is None
        assert mr.to_db() == {}

    def test_mechanical_result_with_roll(self):
        roll = RollResult(
            dice=[1, 0, -1, 1],
            total=1,
            skill_total=4,
            outcome="success",
            shifts=2,
        )
        mr = MechanicalResult(
            decision=MechanicalDecision(
                requires_test=True, skill="Combat", skill_value=3
            ),
            roll=roll,
        )
        assert mr.outcome == "success"
        db = mr.to_db()
        assert db["skill_used"] == "Combat"
        assert db["outcome"] == "success"


# =============================================================================
# FATE CORE DICE ROLLING
# =============================================================================


class TestFateCoreDice:
    def setup_method(self):
        self.engine = FateCoreEngine()

    def test_roll_dice_basic(self):
        """4dF should produce 4 dice, each -1, 0, or 1."""
        decision = MechanicalDecision(
            requires_test=True, skill="Athlétisme", skill_value=3, difficulty=2
        )
        roll = self.engine.roll_dice(decision)
        assert len(roll.dice) == 4
        assert all(d in (-1, 0, 1) for d in roll.dice)
        assert roll.total == sum(roll.dice)
        assert roll.skill_total == roll.total + 3

    def test_roll_outcomes(self):
        """Test all possible Fate outcomes using seed."""
        decision = MechanicalDecision(
            requires_test=True, skill="Combat", skill_value=2, difficulty=2
        )
        outcomes_seen = set()
        for _ in range(500):
            roll = self.engine.roll_dice(decision)
            outcomes_seen.add(roll.outcome)
            assert roll.shifts == roll.skill_total - 2
            if roll.shifts < 0:
                assert roll.outcome == "failure"
            elif roll.shifts == 0:
                assert roll.outcome == "tie"
            elif roll.shifts >= 3:
                assert roll.outcome == "success_with_style"
            else:
                assert roll.outcome == "success"

        # With enough rolls we should see all outcomes
        assert "failure" in outcomes_seen
        assert "success" in outcomes_seen

    def test_opposed_roll(self):
        decision = MechanicalDecision(
            requires_test=True,
            skill="Combat",
            skill_value=4,
            opposition={"npc_name": "Guard", "skill": "Combat", "skill_value": 3},
        )
        roll = self.engine.roll_dice(decision)
        assert roll.opposition_total is not None
        assert "opposition" in roll.details

    def test_narrator_addon(self):
        roll = RollResult(
            dice=[1, 0, -1, 1],
            total=1,
            skill_total=4,
            outcome="success",
            shifts=2,
            details={
                "skill_name": "Athlétisme",
                "skill_label": "Bon",
                "difficulty": 2,
                "difficulty_label": "Correct",
            },
        )
        addon = self.engine.build_narrator_addon(roll)
        assert "BINDING" in addon
        assert "REUSSITE" in addon
        assert "Athlétisme" in addon

    def test_narrator_addon_none(self):
        assert self.engine.build_narrator_addon(None) == ""

    def test_needs_mechanical_step(self):
        assert self.engine.needs_mechanical_step() is True

    def test_gauge_policy(self):
        assert self.engine.get_gauge_policy() == "engine"


# =============================================================================
# D6 DICE ROLLING
# =============================================================================


class TestD6Dice:
    def setup_method(self):
        self.engine = D6Engine()

    def test_parse_dice_code(self):
        assert parse_dice_code("3D+2") == (3, 2)
        assert parse_dice_code("2D") == (2, 0)
        assert parse_dice_code("4d+1") == (4, 1)
        assert parse_dice_code("invalid") == (1, 0)

    def test_roll_d6_pool_basic(self):
        """Roll should produce regular dice + wild die."""
        pool = roll_d6_pool(3, 1)
        # Regular dice: 2 normally, 1 if complication (removes highest)
        if pool["complication"]:
            assert len(pool["regular_dice"]) == 1
        else:
            assert len(pool["regular_dice"]) == 2
        assert len(pool["wild_die_rolls"]) >= 1
        assert isinstance(pool["total"], int)
        assert isinstance(pool["complication"], bool)

    def test_roll_d6_pool_single_die(self):
        """Single die = wild die only."""
        pool = roll_d6_pool(1, 0)
        assert len(pool["regular_dice"]) == 0
        assert len(pool["wild_die_rolls"]) >= 1

    def test_roll_d6_pool_complication(self):
        """Wild die=1 should cause complication."""
        random.seed(0)  # Find a seed that gives wild die = 1
        found_complication = False
        for _ in range(200):
            pool = roll_d6_pool(3, 0)
            if pool["complication"]:
                found_complication = True
                assert pool["wild_die_rolls"][0] == 1
                break
        # Complication happens ~1/6 of the time
        assert found_complication, "Should find at least one complication in 200 rolls"

    def test_roll_d6_pool_explosion(self):
        """Wild die=6 should explode."""
        found_explosion = False
        for _ in range(200):
            pool = roll_d6_pool(3, 0)
            if pool["wild_die_rolls"][0] == 6:
                found_explosion = True
                assert len(pool["wild_die_rolls"]) >= 2
                break
        assert found_explosion, "Should find at least one explosion in 200 rolls"

    def test_roll_dice_basic(self):
        decision = MechanicalDecision(
            requires_test=True, skill="Esquive", skill_value=3, difficulty=15
        )
        roll = self.engine.roll_dice(decision)
        assert len(roll.dice) >= 1
        assert roll.outcome in ("success", "failure")

    def test_roll_dice_opposed(self):
        decision = MechanicalDecision(
            requires_test=True,
            skill="Combat",
            skill_value=4,
            opposition={"npc_name": "Pirate", "skill": "Combat", "skill_value": "3D"},
        )
        roll = self.engine.roll_dice(decision)
        assert roll.opposition_total is not None

    def test_narrator_addon(self):
        roll = RollResult(
            dice=[3, 5, 4],
            total=12,
            skill_total=12,
            outcome="failure",
            shifts=-3,
            complication=False,
            details={
                "skill_name": "Esquive",
                "dice_code": "3D",
                "regular_dice": [3, 5],
                "wild_die_rolls": [4],
                "difficulty": 15,
            },
        )
        addon = self.engine.build_narrator_addon(roll)
        assert "BINDING" in addon
        assert "ECHEC" in addon

    def test_narrator_addon_complication(self):
        roll = RollResult(
            dice=[3, 5, 1],
            total=8,
            skill_total=8,
            outcome="failure",
            shifts=-7,
            complication=True,
            details={
                "skill_name": "Tir",
                "dice_code": "3D",
                "regular_dice": [3, 5],
                "wild_die_rolls": [1],
                "difficulty": 15,
            },
        )
        addon = self.engine.build_narrator_addon(roll)
        assert "COMPLICATION" in addon

    def test_needs_mechanical_step(self):
        assert self.engine.needs_mechanical_step() is True

    def test_gauge_policy(self):
        assert self.engine.get_gauge_policy() == "engine"


# =============================================================================
# NONE ENGINE
# =============================================================================


class TestNoneEngine:
    def setup_method(self):
        self.engine = NoneEngine()

    def test_needs_mechanical_step(self):
        assert self.engine.needs_mechanical_step() is False

    def test_gauge_policy(self):
        assert self.engine.get_gauge_policy() == "none"

    def test_roll_dice_raises(self):
        with pytest.raises(NotImplementedError):
            self.engine.roll_dice(
                MechanicalDecision(requires_test=True, skill="x", skill_value=1)
            )

    def test_narrator_addon_empty(self):
        assert self.engine.build_narrator_addon(None) == ""


# =============================================================================
# NARRATIVE ENGINE
# =============================================================================


class TestNarrativeEngine:
    def setup_method(self):
        self.engine = NarrativeEngine()

    def test_needs_mechanical_step(self):
        assert self.engine.needs_mechanical_step() is False

    def test_gauge_policy(self):
        assert self.engine.get_gauge_policy() == "none"

    def test_roll_dice_raises(self):
        with pytest.raises(NotImplementedError):
            self.engine.roll_dice(
                MechanicalDecision(requires_test=True, skill="x", skill_value=1)
            )


# =============================================================================
# ENGINE DATA
# =============================================================================


class TestEngineData:
    def test_fate_skills_base_not_empty(self):
        assert len(FATE_SKILLS_BASE) >= 18

    def test_fate_skills_genre(self):
        base = get_fate_skills()
        scifi = get_fate_skills("sci-fi")
        assert "Pilotage" in scifi
        assert "Pilotage" not in base
        # sci-fi removes Équitation
        assert "Équitation" not in scifi

    def test_fate_skills_unknown_genre(self):
        skills = get_fate_skills("alien_genre")
        assert skills == sorted(FATE_SKILLS_BASE)

    def test_d6_attributes(self):
        assert len(D6_ATTRIBUTES) == 6
        assert "Dextérité" in D6_ATTRIBUTES

    def test_d6_skills_base(self):
        skills = get_d6_skills()
        assert "Dextérité" in skills
        assert "Esquive" in skills["Dextérité"]

    def test_d6_skills_genre(self):
        fantasy = get_d6_skills("fantasy")
        assert "Arcanes" in fantasy["Connaissance"]
        # Fantasy removes Informatique from Technique
        assert "Informatique" not in fantasy["Technique"]

    def test_d6_difficulty_scale(self):
        assert D6_DIFFICULTY_SCALE["moderate"] == 15
        assert D6_DIFFICULTY_SCALE["heroic"] == 30

    def test_fate_difficulty_ladder(self):
        assert FATE_DIFFICULTY_LADDER[0] == "Médiocre"
        assert FATE_DIFFICULTY_LADDER[8] == "Légendaire"

    def test_d6_wound_levels(self):
        assert len(D6_WOUND_LEVELS) == 5
        assert "stunned" in D6_WOUND_LEVELS

    def test_fate_ladder_labels(self):
        from services.engine.fate_core import _ladder_label
        assert _ladder_label(0) == "Médiocre"
        assert _ladder_label(4) == "Excellent"
        assert _ladder_label(8) == "Légendaire"
        assert _ladder_label(-5) == "Terrible"
        assert _ladder_label(10) == "Légendaire"


# =============================================================================
# MECHANICAL PROMPTS
# =============================================================================


class TestMechanicalPrompt:
    def test_fate_prompt(self):
        from prompts.mechanical_prompt import get_mechanical_system_prompt
        prompt = get_mechanical_system_prompt("fate_core")
        assert "FATE CORE" in prompt
        assert "Mediocre" in prompt or "Médiocre" in prompt
        assert "requires_test" in prompt

    def test_d6_prompt(self):
        from prompts.mechanical_prompt import get_mechanical_system_prompt
        prompt = get_mechanical_system_prompt("d6")
        assert "D6" in prompt
        assert "15" in prompt  # moderate difficulty
        assert "requires_test" in prompt

    def test_invalid_engine_raises(self):
        from prompts.mechanical_prompt import get_mechanical_system_prompt
        with pytest.raises(ValueError):
            get_mechanical_system_prompt("none")

    def test_context_builder(self):
        from prompts.mechanical_prompt import build_mechanical_context
        ctx = build_mechanical_context(
            player_message="I attack the guard",
            engine_stats={
                "skills": [{"name": "Combat", "level": 3, "label": "Bon"}],
                "fate_points": 2,
            },
            world_difficulty="moderate",
            context_summary="Guard is blocking the door.",
        )
        assert "Combat" in ctx
        assert "I attack the guard" in ctx
        assert "moderate" in ctx
        assert "Fate Points: 2" in ctx

    def test_context_builder_dict_skills(self):
        """NPC-style flat dict skills."""
        from prompts.mechanical_prompt import build_mechanical_context
        ctx = build_mechanical_context(
            player_message="test",
            engine_stats={"skills": {"Combat": 3, "Tir": 2}},
            world_difficulty="hard",
            context_summary="",
        )
        assert "Combat: 3" in ctx
        assert "Tir: 2" in ctx


# =============================================================================
# ASPECT INVOCATION RECALCULATION
# =============================================================================


class TestAspectInvocation:
    """Test Fate Core aspect invocation logic (recalculating outcome after +2 per aspect)."""

    def _make_failed_roll(self, skill_total=2, difficulty=4) -> dict:
        """Create a failed Fate Core roll dict."""
        shifts = skill_total - difficulty
        return {
            "dice": [-1, 0, 0, 1],
            "total": 0,
            "skill_total": skill_total,
            "opposition_total": None,
            "outcome": "failure",
            "shifts": shifts,
            "complication": False,
            "details": {
                "skill_name": "Athlétisme",
                "skill_value": 2,
                "skill_label": "Correct",
                "difficulty": difficulty,
                "difficulty_label": "Excellent",
            },
        }

    def test_single_invocation_turns_failure_to_tie(self):
        """One aspect invocation (+2) turns failure (shifts=-2) into tie (shifts=0)."""
        roll = self._make_failed_roll(skill_total=2, difficulty=4)
        invoked = ["High Concept"]
        bonus = len(invoked) * 2

        new_skill_total = roll["skill_total"] + bonus
        new_shifts = new_skill_total - roll["details"]["difficulty"]

        assert new_shifts == 0
        assert new_skill_total == 4

    def test_two_invocations_turn_failure_to_success(self):
        """Two aspect invocations (+4) turn failure (shifts=-2) into success (shifts=+2)."""
        roll = self._make_failed_roll(skill_total=2, difficulty=4)
        invoked = ["High Concept", "Trouble"]
        bonus = len(invoked) * 2

        new_skill_total = roll["skill_total"] + bonus
        new_shifts = new_skill_total - roll["details"]["difficulty"]

        assert new_shifts == 2
        # Outcome recalculation
        if new_shifts < 0:
            outcome = "failure"
        elif new_shifts == 0:
            outcome = "tie"
        elif new_shifts >= 3:
            outcome = "success_with_style"
        else:
            outcome = "success"
        assert outcome == "success"

    def test_three_invocations_success_with_style(self):
        """Three aspects (+6) on shifts=-2 gives shifts=+4 = success_with_style."""
        roll = self._make_failed_roll(skill_total=2, difficulty=4)
        invoked = ["A", "B", "C"]
        bonus = len(invoked) * 2

        new_shifts = (roll["skill_total"] + bonus) - roll["details"]["difficulty"]
        assert new_shifts == 4

        outcome = (
            "failure" if new_shifts < 0
            else "tie" if new_shifts == 0
            else "success_with_style" if new_shifts >= 3
            else "success"
        )
        assert outcome == "success_with_style"

    def test_no_invocation_keeps_failure(self):
        """Skipping invocation (empty list) preserves original outcome."""
        roll = self._make_failed_roll(skill_total=2, difficulty=4)
        invoked = []
        bonus = len(invoked) * 2
        assert bonus == 0

        new_shifts = (roll["skill_total"] + bonus) - roll["details"]["difficulty"]
        assert new_shifts == roll["shifts"]

    def test_invocation_updates_roll_details(self):
        """Verify that invocation metadata is stored in details dict."""
        roll = self._make_failed_roll()
        invoked = ["Aspect A", "Aspect B"]
        bonus = len(invoked) * 2

        roll["skill_total"] += bonus
        roll["shifts"] = roll["skill_total"] - roll["details"]["difficulty"]
        roll["details"]["invoked_aspects"] = invoked
        roll["details"]["invocation_bonus"] = bonus
        roll["details"]["fate_points_spent"] = len(invoked)

        assert roll["details"]["invoked_aspects"] == ["Aspect A", "Aspect B"]
        assert roll["details"]["invocation_bonus"] == 4
        assert roll["details"]["fate_points_spent"] == 2

    def test_roll_result_model_accepts_invocation_data(self):
        """RollResult model can hold invocation metadata in details."""
        roll_data = self._make_failed_roll(skill_total=4, difficulty=4)
        roll_data["outcome"] = "tie"
        roll_data["shifts"] = 0
        roll_data["details"]["invoked_aspects"] = ["My Aspect"]
        roll_data["details"]["fate_points_spent"] = 1

        result = RollResult(**roll_data)
        assert result.outcome == "tie"
        assert result.details["invoked_aspects"] == ["My Aspect"]
        assert result.details["fate_points_spent"] == 1
