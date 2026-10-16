"""World enhance: the player's short text enriches a wizard step (normalization, one call)."""

import json

import pytest

from llm.session import LLMSession
from llm.usage import UsageLedger
from prompts.world_enhance_prompt import build_user_message
from services.engine.engine_data import D6_ATTRIBUTES
from services.world_enhance import (
    WorldEnhanceFailed,
    enhance,
    normalize_character,
    normalize_d6_attributes,
    normalize_d6_skills,
    normalize_fate_skills,
    normalize_world,
)
from services.engine.engine_data import get_d6_skills, get_fate_skills
from tests.characterization.scripted_llm import ScriptedLLMProvider

SLUGS = ["sci_fi", "dark_fantasy", "cyberpunk"]
GENRES = [{"slug": s, "label": s.title()} for s in SLUGS]

WORLD_OUTPUT = {
    "world_config": {"genre": "dark_fantasy", "difficulty": "hard", "duration": "long",
                     "hardcore": False, "lore": "Un royaume sous la cendre, enrichi."},
    "manual_entities": {
        "npcs": [{"name": "Mère Orsa", "description": "Herboriste aveugle."}],
        "locations": [{"name": "Valcendre", "description": "Ville minière."}],
        "organizations": [],
    },
}
CHARACTER_OUTPUT = {
    "character": {"name": "Ilda", "gender": "female", "occupation": "chasseuse",
                  "description": "Taciturne, enrichie."},
    "engine": {"traits": [{"name": "Tenace", "description": "Ne lâche rien."}]},
}


def _pips(dice: str) -> int:
    base, _, rem = dice.partition("D")
    return int(base) * 3 + int(rem.lstrip("+") or 0)


# -- world --------------------------------------------------------------------

def test_world_fills_the_step_from_the_lore():
    out = normalize_world(WORLD_OUTPUT, SLUGS, {"world_config": {"lore": "Royaume de cendre"}})
    assert out["world_config"] == {"genre": "dark_fantasy", "difficulty": "hard",
                                   "duration": "long", "hardcore": False,
                                   "lore": "Un royaume sous la cendre, enrichi."}
    assert out["manual_entities"]["npcs"] == [{"name": "Mère Orsa",
                                               "description": "Herboriste aveugle."}]
    assert "character_data" not in out


def test_world_invalid_values_fall_back_to_the_current_form():
    raw = {"world_config": {"genre": "western", "difficulty": "nightmare", "duration": 3,
                            "hardcore": "yes", "lore": ""}}
    current = {"world_config": {"genre": "cyberpunk", "difficulty": "easy", "duration": "short",
                                "hardcore": True, "lore": "Néons."}}
    out = normalize_world(raw, SLUGS, current)
    assert out["world_config"] == {"genre": "cyberpunk", "difficulty": "easy",
                                   "duration": "short", "hardcore": True, "lore": "Néons."}


def test_world_unknown_genre_on_an_empty_form_takes_the_first_genre():
    out = normalize_world({"world_config": {"genre": "western"}}, SLUGS, {})
    assert out["world_config"]["genre"] == "sci_fi"
    assert out["world_config"]["difficulty"] == "moderate"
    assert out["world_config"]["duration"] == "medium"


def test_world_player_entities_are_kept_first_and_not_duplicated():
    current = {"manual_entities": {"npcs": [{"name": "mère orsa", "description": "Mienne."},
                                            {"name": "  ", "description": "vide"}]}}
    raw = {"manual_entities": {"npcs": [{"name": "Mère Orsa", "description": "LLM."},
                                        {"name": "Kael", "description": ""}, "junk"]}}
    out = normalize_world(raw, SLUGS, current)
    assert out["manual_entities"]["npcs"] == [{"name": "mère orsa", "description": "Mienne."},
                                              {"name": "Kael", "description": ""}]
    assert out["manual_entities"]["locations"] == []


# -- character ----------------------------------------------------------------

def test_character_fills_identity_and_engine_section():
    out = normalize_character(CHARACTER_OUTPUT, "narrative", {"character_data": {"description": "x"}})
    data = out["character_data"]
    assert (data["name"], data["gender"], data["occupation"]) == ("Ilda", "female", "chasseuse")
    assert data["description"] == "Taciturne, enrichie."
    assert data["traits"] == [{"name": "Tenace", "description": "Ne lâche rien."}]
    assert set(out) == {"character_data"}


def test_character_invalid_values_keep_the_current_ones():
    current = {"character_data": {"name": "Valentin", "gender": "male", "description": "x"}}
    out = normalize_character({"character": {"name": "", "gender": "robot"}}, "none", current)
    assert out["character_data"]["name"] == "Valentin"
    assert out["character_data"]["gender"] == "male"


def test_character_fields_the_llm_does_not_fill_are_kept():
    current = {"character_data": {"skills": {"Combat": 4}, "aspects": {"high_concept": "Pilote"}}}
    raw = {"engine": {"aspects": {"trouble": "Dettes", "other": ["A"]}}}
    out = normalize_character(raw, "fate_core", current)
    assert out["character_data"]["skills"] == {"Combat": 4}
    assert out["character_data"]["aspects"] == {"high_concept": "Pilote", "trouble": "Dettes",
                                                "other": ["A", "", ""]}


def test_character_only_the_selected_engine_section_is_applied():
    out = normalize_character(CHARACTER_OUTPUT, "d6", {})
    assert "traits" not in out["character_data"]
    assert "attributes" not in out["character_data"]  # none proposed, none current


# -- Fate pyramid ---------------------------------------------------------------

def _is_pyramid(skills: dict) -> bool:
    levels = sorted(skills.values(), reverse=True)
    return levels == [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]


def test_fate_pyramid_from_a_clean_proposal():
    names = get_fate_skills("sci_fi")[:10]
    proposed = dict(zip(names, [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]))
    assert normalize_fate_skills(proposed, "sci_fi", None) == proposed


def test_fate_pyramid_is_enforced_keeping_the_ranking():
    proposed = {"Pilotage": 5, "piratage": 4, "Magie": 4, "Combat": 4, "Tir": 4,
                "Pilotage ": 1, "Volonté": "haut", "Discrétion": 2}
    skills = normalize_fate_skills(proposed, "sci_fi", None)
    assert _is_pyramid(skills)
    assert skills["Pilotage"] == 4            # highest proposed
    assert skills["Piratage"] == 3            # canonical case
    assert "Magie" not in skills              # not a sci_fi skill
    assert "Volonté" not in skills or skills["Volonté"] <= 1  # invalid level: only as filler
    assert set(skills) <= set(get_fate_skills("sci_fi"))


def test_fate_pyramid_completes_from_the_current_sheet_first():
    current = {"Empathie": 4, "Magie": 3}
    skills = normalize_fate_skills({"Combat": 4}, "sci_fi", current)
    assert _is_pyramid(skills)
    assert skills["Combat"] == 4 and skills["Empathie"] == 3
    assert "Magie" not in skills


def test_fate_pyramid_nothing_usable_keeps_the_sheet():
    assert normalize_fate_skills({"Magie": 4}, "sci_fi", {"Combat": 4}) is None
    assert normalize_fate_skills("Combat", "sci_fi", None) is None
    out = normalize_character({"engine": {"skills": {"Magie": 4}}}, "fate_core",
                              {"world_config": {"genre": "sci_fi"},
                               "character_data": {"skills": {"Combat": 4}}})
    assert out["character_data"]["skills"] == {"Combat": 4}


# -- D6 -----------------------------------------------------------------------

def test_d6_skills_fit_the_budget_and_the_cap():
    proposed = {"Esquive": 3, "piratage": "1D+1", "Arcanes": 2, "Bagarre": "x", "Soulever": 1}
    skills = normalize_d6_skills(proposed, "cyberpunk")
    assert "Arcanes" not in skills and "Bagarre" not in skills  # other genre / invalid
    assert "Piratage" in skills
    pips = {name: _pips(code) for name, code in skills.items()}
    assert all(1 <= p <= 6 for p in pips.values())
    assert sum(pips.values()) == 18  # 3 skills at the 2D cap: 1D left for the player
    allowed = {s for names in get_d6_skills("cyberpunk").values() for s in names}
    assert set(skills) <= allowed


def test_d6_skills_over_budget_are_cut_to_7d():
    proposed = {"Esquive": 2, "Piratage": 2, "Cybernétique": 2, "Escalade": 2, "Natation": 2}
    skills = normalize_d6_skills(proposed, "cyberpunk")
    assert sum(_pips(code) for code in skills.values()) == 7 * 3


def test_d6_skills_nothing_usable():
    assert normalize_d6_skills({"Arcanes": 2}, "cyberpunk") is None
    assert normalize_d6_skills(None, "cyberpunk") is None


def test_d6_character_gets_attributes_and_skills():
    raw = {"engine": {"attributes": {a: 3 for a in D6_ATTRIBUTES},
                      "skills": {"Esquive": 2, "Piratage": 2, "Cybernétique": 2, "Escalade": 1}}}
    out = normalize_character(raw, "d6", {"world_config": {"genre": "cyberpunk"}})
    data = out["character_data"]
    assert data["attributes"] == {a: "3D" for a in D6_ATTRIBUTES}
    assert data["skills"] == {"Esquive": "2D", "Piratage": "2D", "Cybernétique": "2D", "Escalade": "1D"}


@pytest.mark.parametrize("proposed", [
    {a: 5 for a in D6_ATTRIBUTES},                   # 30D: over budget
    {a: 1 for a in D6_ATTRIBUTES},                   # 6D: under budget
    {D6_ATTRIBUTES[0]: "4D+2", D6_ATTRIBUTES[1]: 9, D6_ATTRIBUTES[2]: "x"},
    {a: 3 for a in D6_ATTRIBUTES},                   # exact
])
def test_d6_attributes_respect_bounds_and_budget(proposed):
    attrs = normalize_d6_attributes(proposed)
    assert set(attrs) == set(D6_ATTRIBUTES)
    pips = [_pips(v) for v in attrs.values()]
    assert all(3 <= p <= 15 for p in pips)
    assert sum(pips) == 18 * 3


def test_d6_exact_budget_is_unchanged():
    assert normalize_d6_attributes({a: 3 for a in D6_ATTRIBUTES}) == {a: "3D" for a in D6_ATTRIBUTES}


# -- prompts and call -----------------------------------------------------------

def test_world_message_has_lore_genres_and_entities():
    msg = build_user_message("world", "Un monde de cendres", "d6", GENRES,
                             {"manual_entities": {"npcs": [{"name": "Kael"}]}})
    assert "Un monde de cendres" in msg
    assert "- dark_fantasy : Dark_Fantasy" in msg
    assert '"name": "Kael"' in msg
    assert "Système D6" not in msg


def test_character_message_has_world_context_and_engine():
    current = {"world_config": {"genre": "cyberpunk", "lore": "Néons"},
               "character_data": {"name": "Nyx", "description": "hackeuse",
                                  "skills": {"Piratage": "1D"}, "attributes": {"Force": "2D"}}}
    msg = build_user_message("character", "hackeuse", "d6", GENRES, current)
    assert "Genre : Cyberpunk" in msg and "Contexte : Néons" in msg
    assert "Système D6" in msg
    assert "Cybernétique" in msg  # cyberpunk D6 skill list
    assert '"name": "Nyx"' in msg and '"Piratage": "1D"' in msg
    assert '"Force"' not in msg.split("## PERSONNAGE ACTUEL")[1]


def test_character_message_lists_the_genre_fate_skills():
    current = {"world_config": {"genre": "dark_fantasy"}}
    msg = build_user_message("character", "mage", "fate_core", GENRES, current)
    assert "exactement 10 compétences" in msg
    assert "Magie" in msg and "Piratage" not in msg


@pytest.mark.parametrize("scope,output,key", [
    ("world", WORLD_OUTPUT, "world_config"),
    ("character", CHARACTER_OUTPUT, "character_data"),
])
async def test_enhance_runs_one_call_and_returns_its_cost(scope, output, key):
    provider = ScriptedLLMProvider({"world_enhance": json.dumps(output)})
    session = LLMSession.from_provider(provider, UsageLedger())
    current = {"world_config": {"lore": "cendres"}, "character_data": {"description": "chasseuse"}}
    result, cost = await enhance(session, scope, "narrative", GENRES, current)
    assert provider.purposes() == ["world_enhance"]
    assert set(result) == ({"world_config", "manual_entities"} if scope == "world" else {key})
    assert cost is not None


@pytest.mark.parametrize("scope", ["world", "character"])
async def test_enhance_with_an_empty_text_invents_the_step(scope):
    output = WORLD_OUTPUT if scope == "world" else CHARACTER_OUTPUT
    provider = ScriptedLLMProvider({"world_enhance": json.dumps(output)})
    session = LLMSession.from_provider(provider, UsageLedger())
    result, _ = await enhance(session, scope, "none", GENRES, {"world_config": {"genre": "sci_fi"}})
    assert provider.purposes() == ["world_enhance"]
    assert result


def test_user_message_flags_an_empty_text():
    msg = build_user_message("world", "  ", "none", GENRES, {"world_config": {"genre": "sci_fi"}})
    assert "(vide : invente" in msg
    msg = build_user_message("character", "", "none", GENRES, {})
    assert "(vide : invente" in msg


async def test_enhance_raises_on_unusable_output():
    provider = ScriptedLLMProvider({"world_enhance": "désolé, je ne peux pas"})
    session = LLMSession.from_provider(provider, UsageLedger())
    with pytest.raises(WorldEnhanceFailed):
        await enhance(session, "world", "none", GENRES, {"world_config": {"lore": "x"}})
