"""Roll inputs come from the character sheet and tolerate LLM formats (#13)."""

from types import SimpleNamespace

import pytest

from schema.engine import MechanicalDecision
from services.engine import d6, fate_core, get_engine


def _decision(**kw):
    return MechanicalDecision(requires_test=True, **kw)


FATE_STATS = {"skills": [{"name": "Combat", "level": 1}, {"name": "Athlétisme", "level": 3}]}
D6_STATS = {
    "attributes": {"Dextérité": "3D", "Perception": "2D+2"},
    "skills": [{"attribute": "Dextérité", "name": "Blasters", "dice_value": "4D+2"}],
}


class TestSchemaAcceptsDiceCodes:
    def test_skill_value_accepts_d6_code(self):
        assert _decision(skill="Blasters", skill_value="4D+2").skill_value == "4D+2"


class TestFateResolution:
    def test_known_skill_uses_sheet_value_not_llm_value(self):
        engine = get_engine("fate_core")
        resolved = engine.resolve_roll_inputs(_decision(skill="combat", skill_value=8, difficulty=2), FATE_STATS)
        assert resolved.skill_value == 1

    def test_unknown_skill_is_mediocre(self):
        engine = get_engine("fate_core")
        resolved = engine.resolve_roll_inputs(_decision(skill="Pilotage", skill_value=5, difficulty=2), FATE_STATS)
        assert resolved.skill_value == 0

    def test_no_sheet_keeps_llm_value(self):
        engine = get_engine("fate_core")
        resolved = engine.resolve_roll_inputs(_decision(skill="Combat", skill_value=2, difficulty=2), {})
        assert resolved.skill_value == 2

    @pytest.mark.parametrize("opp,expected_total", [("+3", 3), ("Bon", 3), (3, 3), ("n'importe quoi", 0)])
    def test_string_opposition_never_raises(self, monkeypatch, opp, expected_total):
        monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: 0))
        roll = get_engine("fate_core").roll_dice(_decision(
            skill="Combat", skill_value=1, opposition={"npc_name": "Garde", "skill_value": opp}))
        assert roll.shifts == 1 - expected_total


class TestD6Resolution:
    def test_known_skill_keeps_pips_from_sheet(self, monkeypatch):
        monkeypatch.setattr(d6, "random", SimpleNamespace(randint=lambda a, b: 4))
        engine = get_engine("d6")
        resolved = engine.resolve_roll_inputs(_decision(skill="Blasters", skill_value=9, difficulty=10), D6_STATS)
        assert resolved.skill_value == "4D+2"
        roll = engine.roll_dice(resolved)
        assert roll.details["pip_bonus"] == 2
        assert len(roll.details["regular_dice"]) + len(roll.details["wild_die_rolls"]) == 4

    def test_attribute_name_uses_attribute_code(self):
        resolved = get_engine("d6").resolve_roll_inputs(_decision(skill="perception", skill_value="6D"), D6_STATS)
        assert resolved.skill_value == "2D+2"

    def test_unknown_skill_is_capped_at_best_attribute(self):
        engine = get_engine("d6")
        assert engine.resolve_roll_inputs(_decision(skill="Pilotage", skill_value="7D"), D6_STATS).skill_value == "3D"
        assert engine.resolve_roll_inputs(_decision(skill="Pilotage", skill_value="2D"), D6_STATS).skill_value == "2D"

    def test_int_opposition_rolls_that_many_dice(self, monkeypatch):
        monkeypatch.setattr(d6, "random", SimpleNamespace(randint=lambda a, b: 4))
        roll = get_engine("d6").roll_dice(_decision(
            skill="Blasters", skill_value="4D+2", opposition={"npc_name": "Garde", "skill_value": 5}))
        # 5 dice showing 4 = 20 (a single die would give 4)
        assert roll.opposition_total == 20
