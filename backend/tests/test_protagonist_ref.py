"""#28: the protagonist resolves by type (PROTAGONIST_REF), not by a hardcoded name.

Every world here is the canonical example with its PC renamed "Kira", so a leftover
"Valentin" anywhere in the write path shows up as a missing participant or relation.
"""

import json
from uuid import UUID

import pytest

from llm.session import LLMSession
from schema import DEFAULT_PROTAGONIST_NAME, PROTAGONIST_REF, WorldGeneration
from services.llm_providers import ToolResult
from tests.prompt_examples import WORLD_GENERATION_EXAMPLE
from tests.test_llm_session import FakeProvider

pytestmark = pytest.mark.integration

PC = "Kira"
ARRIVAL_WITH_PC = ("station", "incident", "mood", "need")


class ExtractionProvider(FakeProvider):
    """Answers every tool call with `payload` and records the user prompts it was sent."""

    def __init__(self, payload: dict):
        super().__init__()
        self.payload = payload
        self.user_prompts: list[str] = []

    async def complete_with_tools(self, system_prompt: str, messages: list[dict],
                                  tools: list[dict], tool_choice: dict, temperature: float,
                                  max_tokens: int) -> ToolResult:
        del system_prompt, tool_choice, temperature, max_tokens  # same signature, unused
        self.user_prompts.append(messages[-1]["content"])
        return ToolResult(tool_name=tools[0]["name"], tool_input=self.payload,
                          usage=self.usage)


def kira_json() -> dict:
    return json.loads(WORLD_GENERATION_EXAMPLE.replace("Valentin", PC))


async def populate(test_pool, test_user, data: dict) -> tuple[UUID, WorldGeneration]:
    from services.game_service import GameService

    world_gen = WorldGeneration.model_validate(data)
    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])
    await service.process_init(game_id, world_gen)
    return game_id, world_gen


async def populate_kira(test_pool, test_user) -> tuple[UUID, WorldGeneration]:
    return await populate(test_pool, test_user, kira_json())


async def run_extractor(extractor_cls, test_pool, game_id, payload: dict, cycle: int = 2):
    """Run an extractor through its public run() against a provider answering `payload`."""
    provider = ExtractionProvider(payload)
    extractor = extractor_cls(test_pool, game_id, LLMSession.from_provider(provider))
    result = await extractor.run("Kira salue Marie.", {}, cycle)
    return result, provider


async def run_narrative_arcs(test_pool, game_id, payload: dict, cycle: int = 2) -> dict:
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    result, _ = await run_extractor(NarrativeArcsExtractor, test_pool, game_id, payload, cycle)
    assert result["success"], result
    return result["stats"]


async def protagonist_relations(conn, game_id, target: str, rel_type: str):
    return await conn.fetch(
        """SELECT r.level, r.context, r.known_by_protagonist, r.end_cycle, src.name AS source
           FROM relations r
           JOIN entity_registry src ON src.id = r.source_id
           JOIN entity_registry tgt ON tgt.id = r.target_id
           WHERE r.game_id = $1 AND src.entity_type = 'protagonist'
             AND tgt.name = $2 AND r.type = $3::relation_type""",
        game_id, target, rel_type)


async def fact_participants(conn, game_id, semantic_key: str):
    return await conn.fetch(
        """SELECT er.name, er.entity_type, fp.role FROM facts f
           JOIN fact_participants fp ON fp.fact_id = f.id
           JOIN entity_registry er ON er.id = fp.entity_id
           WHERE f.game_id = $1 AND f.semantic_key = $2""",
        game_id, semantic_key)


async def arrival_participants(conn, game_id) -> list[list[tuple]]:
    return [[(r["name"], r["entity_type"], r["role"])
             for r in await fact_participants(conn, game_id, f"protagonist:arrival:{part}")]
            for part in ARRIVAL_WITH_PC]


# ---------------------------------------------------------------------------
# Resolution (SQL find_entity)
# ---------------------------------------------------------------------------


def test_entity_ref_schema_tells_the_llm_about_the_token():
    from schema.extraction import RelationUpdate

    schema = RelationUpdate.model_json_schema()
    assert PROTAGONIST_REF in schema["properties"]["source_ref"]["description"]


async def test_sql_find_entity_maps_the_token(test_pool, test_user):
    """The SQL side uses the same spelling and trimming as schema.core.PROTAGONIST_REF."""
    game_id, _ = await populate_kira(test_pool, test_user)
    async with test_pool.acquire() as conn:
        pc_id = await conn.fetchval(
            "SELECT id FROM entity_registry WHERE game_id = $1 AND entity_type = 'protagonist'",
            game_id)

        async def find(name: str, entity_type: str = "protagonist"):
            return await conn.fetchval("SELECT find_entity($1, $2, $3)",
                                       game_id, name, entity_type)

        assert await find(PROTAGONIST_REF) == pc_id
        assert await find(f" {PROTAGONIST_REF.lower()}\n") == pc_id  # like str.strip()
        assert await find(f"\t{PC} ") == pc_id
        assert await find(PROTAGONIST_REF, "character") is None


# ---------------------------------------------------------------------------
# World generation
# ---------------------------------------------------------------------------


async def test_world_with_pc_kira_has_kira_in_arrival_facts(test_pool, test_user):
    game_id, _ = await populate_kira(test_pool, test_user)
    async with test_pool.acquire() as conn:
        assert await arrival_participants(conn, game_id) == [
            [(PC, "protagonist", "actor")]] * len(ARRIVAL_WITH_PC)
        legacy = await conn.fetchval(
            "SELECT COUNT(*) FROM facts WHERE game_id = $1 AND semantic_key LIKE 'valentin:%'",
            game_id)
    assert legacy == 0


async def test_arrival_event_reads_the_protagonist_keys(test_pool, test_user):
    from kg.reader import KnowledgeGraphReader

    game_id, world_gen = await populate_kira(test_pool, test_user)
    async with test_pool.acquire() as conn:
        arrival = await KnowledgeGraphReader(test_pool, game_id).get_arrival_event(conn)
    assert arrival is not None
    ae = world_gen.arrival_event
    assert arrival["initial_mood"] == ae.initial_mood
    assert arrival["immediate_need"] == ae.immediate_need
    assert arrival["incident"] == ae.optional_incident
    assert ae.arrival_method in arrival["arrival_description"]


async def test_world_relations_and_arcs_using_the_token_are_populated(test_pool, test_user):
    """The path the genre examples teach: initial_relations and arcs reference PROTAGONIST."""
    data = kira_json()
    data["initial_relations"].append({"source_ref": PROTAGONIST_REF, "target_ref": "Ossek",
                                      "relation_type": "knows", "level": 2})
    arc = data["narrative_arcs"][0]
    arc["involved_entities"].append(PROTAGONIST_REF)
    game_id, _ = await populate(test_pool, test_user, data)
    async with test_pool.acquire() as conn:
        assert [r["source"] for r in await protagonist_relations(
            conn, game_id, "Ossek", "knows")] == [PC]
        involved = await conn.fetch(
            """SELECT er.name, er.entity_type FROM arc_participants ap
               JOIN narrative_arcs a ON a.id = ap.arc_id
               JOIN entity_registry er ON er.id = ap.entity_id
               WHERE a.game_id = $1 AND a.title = $2""", game_id, arc["title"])
    assert (PC, "protagonist") in [(r["name"], r["entity_type"]) for r in involved]


def test_world_generation_drops_entities_named_after_the_token():
    data = kira_json()
    data["characters"].append({**data["characters"][0], "name": f" {PROTAGONIST_REF.lower()}"})
    world = WorldGeneration.model_validate(data)
    assert len(world.characters) == len(data["characters"]) - 1


async def test_wizard_name_wins_over_the_model_name(harness, test_pool):
    """Scripted world names the PC "Valentin"; the wizard said Kira: Kira is stored."""
    game_id = await harness.create_game("none")
    events = await harness.init_world(game_id, character_data={"name": f" {PC} "})
    assert "error" not in harness.summarize(events), events
    async with test_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT name FROM protagonists WHERE game_id = $1::uuid", game_id) == PC
        assert await arrival_participants(conn, game_id) == [
            [(PC, "protagonist", "actor")]] * len(ARRIVAL_WITH_PC)
        # The model's relations written with "Valentin" follow the rename.
        assert [r["source"] for r in await protagonist_relations(
            conn, game_id, "Symbiose Tech", "employed_by")] == [PC]
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM entity_registry WHERE game_id = $1::uuid"
            " AND LOWER(name) = 'valentin'", game_id) == 0


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


async def test_item_use_fact_has_the_protagonist(test_pool, test_user):
    from services.extraction.inventory import InventoryExtractor

    game_id, _ = await populate_kira(test_pool, test_user)
    result, _ = await run_extractor(InventoryExtractor, test_pool, game_id, {
        "inventory_changes": [
            {"action": "use", "object_ref": "Terminal personnel", "quantity_delta": 1}]})
    assert result["success"], result
    async with test_pool.acquire() as conn:
        rows = await fact_participants(conn, game_id, "protagonist:use:terminal_personnel")
    assert [(r["name"], r["role"]) for r in rows] == [(PC, "actor")]


@pytest.mark.parametrize("source_ref", [PROTAGONIST_REF, PC, PC.upper()])
async def test_extracted_relation_from_protagonist_is_created(test_pool, test_user,
                                                              source_ref):
    """The token and the real PC name both create the relation from the protagonist."""
    game_id, world_gen = await populate_kira(test_pool, test_user)
    npc = world_gen.characters[0].name
    stats = await run_narrative_arcs(test_pool, game_id, {"relations_created": [
        {"cycle": 2, "relation": {"source_ref": source_ref, "target_ref": npc,
                                  "relation_type": "friend_of", "level": 4}}]})
    assert stats["relations_created"] == 1
    async with test_pool.acquire() as conn:
        rows = await protagonist_relations(conn, game_id, npc, "friend_of")
    assert [(r["source"], r["level"]) for r in rows] == [(PC, 4)]


async def test_extracted_update_end_and_fact_with_the_token(test_pool, test_user):
    """relations_updated (raw SQL), relations_ended and fact participants (SQL find_entity)."""
    game_id, world_gen = await populate_kira(test_pool, test_user)
    npc = world_gen.characters[0].name
    await run_narrative_arcs(test_pool, game_id, {"relations_created": [
        {"cycle": 2, "relation": {"source_ref": PROTAGONIST_REF, "target_ref": npc,
                                  "relation_type": "colleague_of", "level": 2}}]})
    await run_narrative_arcs(test_pool, game_id, {
        "relations_updated": [{"source_ref": PROTAGONIST_REF, "target_ref": npc,
                               "relation_type": "colleague_of", "new_level": 6}],
        "facts": [{"fact_type": "decision", "description": f"{PC} décide d'aider {npc}",
                   "semantic_key": "kira:decide:aider", "importance": 3,
                   "participants": [{"entity_ref": PROTAGONIST_REF, "role": "actor"},
                                    {"entity_ref": npc, "role": "target"}]}],
    })
    async with test_pool.acquire() as conn:
        assert [r["level"] for r in await protagonist_relations(
            conn, game_id, npc, "colleague_of")] == [6]
        rows = await fact_participants(conn, game_id, "kira:decide:aider")
        assert sorted((r["name"], r["role"]) for r in rows) == sorted(
            [(PC, "actor"), (npc, "target")])

    await run_narrative_arcs(test_pool, game_id, {"relations_ended": [
        {"source_ref": PROTAGONIST_REF, "target_ref": npc, "relation_type": "colleague_of",
         "cycle": 3, "reason": "Départ"}]}, cycle=3)
    async with test_pool.acquire() as conn:
        assert [r["end_cycle"] for r in await protagonist_relations(
            conn, game_id, npc, "colleague_of")] == [3]


async def test_entity_update_with_the_token_reaches_the_protagonist(test_pool, test_user):
    """An update without entity_type finds the PC among every type (skills_changed)."""
    from services.extraction.characters import CharactersExtractor

    game_id, _ = await populate_kira(test_pool, test_user)
    result, _ = await run_extractor(CharactersExtractor, test_pool, game_id, {
        "entities_updated": [{"entity_ref": PROTAGONIST_REF, "entity_type": None,
                              "skills_changed": [{"name": "pilotage", "level": 3}]}]})
    assert result["success"], result
    async with test_pool.acquire() as conn:
        level = await conn.fetchval(
            "SELECT level FROM skills WHERE game_id = $1 AND protagonist_id IS NOT NULL"
            " AND name = 'pilotage' AND end_cycle IS NULL", game_id)
    assert level == 3


async def test_extracted_entity_named_after_the_token_is_skipped(test_pool, test_user):
    from services.extraction.characters import CharactersExtractor

    game_id, _ = await populate_kira(test_pool, test_user)
    result, _ = await run_extractor(CharactersExtractor, test_pool, game_id, {
        "entities_created": [{"name": PROTAGONIST_REF, "data": {"occupation": "pilote"}}]})
    assert result["stats"]["entities_created"] == 0
    async with test_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM characters WHERE game_id = $1 AND LOWER(name) = 'protagonist'",
            game_id) == 0


async def test_extractor_user_prompt_names_the_protagonist(test_pool, test_user):
    from services.extraction.characters import CharactersExtractor

    game_id, _ = await populate_kira(test_pool, test_user)
    _, provider = await run_extractor(CharactersExtractor, test_pool, game_id, {})
    [user_prompt] = provider.user_prompts
    assert f"The player character is {PC}" in user_prompt
    assert f'"{PROTAGONIST_REF}"' in user_prompt


# ---------------------------------------------------------------------------
# Prompts and the PC name
# ---------------------------------------------------------------------------


def test_extraction_prompts_teach_the_token_not_a_name():
    from prompts.extraction import (characters_prompt, inventory_prompt, locations_prompt,
                                    narrative_arcs_prompt, organizations_prompt)
    from prompts.extraction.shared import ENTITY_MATCHING_RULE

    assert f'"{PROTAGONIST_REF}"' in ENTITY_MATCHING_RULE
    for module in (characters_prompt, inventory_prompt, locations_prompt,
                   narrative_arcs_prompt, organizations_prompt):
        assert "valentin" not in module.SYSTEM_PROMPT.lower(), module.__name__
        assert ENTITY_MATCHING_RULE in module.SYSTEM_PROMPT, module.__name__
    assert f'"source_ref": "{PROTAGONIST_REF}"' in narrative_arcs_prompt.SYSTEM_PROMPT
    assert f'"entity_ref": "{PROTAGONIST_REF}"' in inventory_prompt.SYSTEM_PROMPT


def test_protagonist_section_injects_the_real_name():
    from prompts.extraction.shared import protagonist_section

    section = protagonist_section(PC)
    assert PC in section and f'"{PROTAGONIST_REF}"' in section
    assert protagonist_section(None) == ""


@pytest.mark.parametrize("data", [{}, {"name": ""}, {"name": "   "}])
def test_protagonist_name_is_required_and_not_blank(data):
    from pydantic import ValidationError

    from schema import ProtagonistData

    with pytest.raises(ValidationError):
        ProtagonistData.model_validate({**data, "skills": [{"name": "a", "level": 1},
                                                           {"name": "b", "level": 2}]})


def test_chosen_name_is_the_trimmed_wizard_name_or_none():
    from pipeline.chosen_name import chosen_name

    assert chosen_name({"name": f"  {PC} "}) == PC
    assert chosen_name({"name": "  "}) is None
    assert chosen_name({}) is None and chosen_name(None) is None


def test_world_prompt_uses_the_chosen_name_or_asks_to_invent_one():
    from prompts.world_generation_prompt import (INVENTED_NAME_MARKER,
                                                 build_world_generation_user_prompt)

    genre = {"world_gen_example": '{"protagonist": {"name": "{{PROTAGONIST_NAME}}"}}'}
    blank = build_world_generation_user_prompt(genre=genre)
    assert "valentin" not in blank.lower() and "{{" not in blank
    assert "Nom : à inventer" in blank
    assert f'"name": "{INVENTED_NAME_MARKER}"' in blank
    named = build_world_generation_user_prompt(protagonist_name=PC, genre=genre)
    assert "Nom : Kira" in named and '"name": "Kira"' in named


def test_apply_chosen_name_overrides_the_model_name_and_its_mentions():
    from pipeline.chosen_name import apply_chosen_name

    out = apply_chosen_name(json.loads(WORLD_GENERATION_EXAMPLE), {"name": PC})
    assert out is not None
    assert out["protagonist"]["name"] == PC
    assert [r["source_ref"] for r in out["initial_relations"]][:2] == [PC, PC]
    assert "Valentin" not in json.dumps(out, ensure_ascii=False)


def test_apply_chosen_name_keeps_an_invented_name_and_fills_a_missing_one():
    from pipeline.chosen_name import apply_chosen_name

    invented = apply_chosen_name(json.loads(WORLD_GENERATION_EXAMPLE), {"name": " "})
    assert invented is not None and invented["protagonist"]["name"] == "Valentin"
    missing = json.loads(WORLD_GENERATION_EXAMPLE)
    del missing["protagonist"]["name"]
    filled = apply_chosen_name(missing, {"name": PC})
    assert filled is not None and filled["protagonist"]["name"] == PC
    assert apply_chosen_name({"protagonist": {}}, None) == {  # no name at all: the default
        "protagonist": {"name": DEFAULT_PROTAGONIST_NAME}}
    assert apply_chosen_name(None, {"name": PC}) is None


@pytest.mark.parametrize("parsed", [[{"protagonist": {"name": "Kira"}}], [], "Kira", 3])
def test_apply_chosen_name_returns_a_non_object_answer_unchanged(parsed):
    """A JSON array (or scalar) answer is left for world validation to refuse cleanly."""
    from pipeline.chosen_name import apply_chosen_name

    assert apply_chosen_name(parsed, {"name": PC}) == parsed


def test_apply_chosen_name_leaves_free_text_alone_when_an_npc_shares_the_name():
    from pipeline.chosen_name import apply_chosen_name

    parsed = {"protagonist": {"name": "Marc", "backstory": "Marc a fui."},
              "characters": [{"name": "Marc Dubois", "description": "Le frère de Marc"}],
              "initial_relations": [{"source_ref": "marc", "target_ref": "Marc Dubois"}]}
    out = apply_chosen_name(parsed, {"name": PC})
    assert out is not None
    assert out["protagonist"] == {"name": PC, "backstory": "Marc a fui."}
    assert out["characters"][0]["name"] == "Marc Dubois"
    assert out["initial_relations"] == [{"source_ref": PC, "target_ref": "Marc Dubois"}]


def test_world_generation_accepts_the_token_in_initial_relations():
    parsed = json.loads(WORLD_GENERATION_EXAMPLE)
    for rel in parsed["initial_relations"]:
        if rel["source_ref"] == "Valentin":
            rel["source_ref"] = PROTAGONIST_REF
    kept = WorldGeneration.model_validate(parsed).initial_relations
    assert len(kept) == len(parsed["initial_relations"])


# One string per field: (model name, wizard name, text before, text after).
RENAME_CASES = [
    pytest.param("Kira", "Kira Voss", "Kira Voss a fui. Kira rit.",
                 "Kira Voss a fui. Kira Voss rit.", id="model-prefix-of-wizard"),
    pytest.param("Kira Voss", "Kira", "Kira Voss a fui, Kira rit.",
                 "Kira a fui, Kira rit.", id="wizard-prefix-of-model"),
    pytest.param("Kira", "kira", "Kira a fui.", "Kira a fui.", id="equal-names-other-case"),
    pytest.param("Ana", "Kira", "Anaïs mange une banane, Ana rit.",
                 "Anaïs mange une banane, Kira rit.", id="name-inside-another-word"),
    pytest.param("Élodie", "Anaïs", "Élodie salue Élodie-Rose et élodie.",
                 "Anaïs salue Élodie-Rose et Anaïs.", id="accented-names"),  # compound kept
    pytest.param("Ana", "Kira", "ANA vit. ana dort.", "Kira vit. Kira dort.",
                 id="case-differences"),
    pytest.param("Valentin", "Kira", "Valentin, Valentin et encore Valentin.",
                 "Kira, Kira et encore Kira.", id="multiple-occurrences"),
    pytest.param("Valentin Moreau", "Kira Voss", "Valentin Moreau arrive. Valentin a fui.",
                 "Kira Voss arrive. Kira a fui.", id="first-name-mention"),
    # Surname-only mentions may be another family member: left alone on purpose.
    pytest.param("Kira Voss", "Ana Lo", "Kira Voss part. Voss rit.", "Ana Lo part. Voss rit.",
                 id="surname-only-mention-kept"),
    # Case-folding oddities: casefold() rewrites ß, İ and ς, so the regex must come from the
    # original strings. Each one combined with the prefix case (wizard name contains model name).
    pytest.param("Kira", "Kira Weiß", "Kira Weiß a fui. Kira rit.",
                 "Kira Weiß a fui. Kira Weiß rit.", id="sharp-s-in-wizard-name"),
    pytest.param("Weiß", "Kira", "Weiß a fui. weiß rit.", "Kira a fui. Kira rit.",
                 id="sharp-s-in-model-name"),
    # "ß" written "SS"/"ss": re.IGNORECASE never folds it, so the casefold spelling is matched too.
    pytest.param("Weiß", "Kira", "WEISS rit. Weiss dort.", "Kira rit. Kira dort.",
                 id="sharp-s-written-ss"),
    pytest.param("Kira", "Kira Weiß", "KIRA WEISS part. Kira rit.",
                 "KIRA WEISS part. Kira Weiß rit.", id="sharp-s-written-ss-in-target"),
    pytest.param("Strauß", "Strauß Kemal", "Strauß Kemal part. Strauß rit.",
                 "Strauß Kemal part. Strauß Kemal rit.", id="sharp-s-prefix"),
    pytest.param("İlker", "İlker Kaya", "İlker Kaya part. İlker rit. ilker dort.",
                 "İlker Kaya part. İlker Kaya rit. İlker Kaya dort.", id="turkish-dotted-i-prefix"),
    pytest.param("Οδυσσεύς", "Οδυσσεύς Λαέρτη", "Οδυσσεύς Λαέρτη έφυγε. Οδυσσεύς γελά.",
                 "Οδυσσεύς Λαέρτη έφυγε. Οδυσσεύς Λαέρτη γελά.", id="greek-final-sigma-prefix"),
    # ' and ’ (U+2019) are the same apostrophe, in both directions.
    pytest.param("N'Diaye", "Kira", "N’Diaye rit. N'Diaye dort.", "Kira rit. Kira dort.",
                 id="typographic-apostrophe-in-text"),
    pytest.param("N’Diaye", "Kira", "N'Diaye rit.", "Kira rit.", id="straight-apostrophe-in-text"),
    pytest.param("N'Diaye", "Kira N’Diaye", "Kira N'Diaye part. N'Diaye rit.",
                 "Kira N'Diaye part. Kira N’Diaye rit.", id="apostrophe-prefix"),  # target kept as is
]


@pytest.mark.parametrize("model_name,wizard_name,before,after", RENAME_CASES)
def test_rename_is_whole_name_and_idempotent(model_name, wizard_name, before, after):
    from pipeline.chosen_name import apply_chosen_name

    def world():
        return {"protagonist": {"name": model_name, "backstory": before},
                "initial_relations": [{"source_ref": model_name.upper(), "target_ref": "Ossek"}]}

    out = apply_chosen_name(world(), {"name": wizard_name})
    assert out is not None
    assert out["protagonist"] == {"name": wizard_name.strip(), "backstory": after}
    expected_ref = model_name.upper() if model_name.lower() == wizard_name.lower() else wizard_name
    assert out["initial_relations"][0]["source_ref"] == expected_ref
    again = apply_chosen_name(out, {"name": wizard_name})  # idempotent
    assert again == out


def test_wizard_name_rule_matches_the_shared_cases():
    """The wizard (frontend/tests/wizardForm.test.mjs) and the API apply one rule: same cases, same
    message, from one fixture."""
    import json
    from pathlib import Path

    from fastapi import HTTPException

    from api.routes import INVALID_PC_NAME, _reject_unusable_wizard_name

    fixture = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/protagonist-names.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    assert INVALID_PC_NAME == cases["message"]
    for name in cases["accepted"]:
        _reject_unusable_wizard_name({"name": name})
    for name in cases["refused"]:
        with pytest.raises(HTTPException) as exc:
            _reject_unusable_wizard_name({"name": name})
        assert (exc.value.status_code, exc.value.detail) == (400, cases["message"]), name


@pytest.mark.parametrize("wizard", ["valentin", "Kira"], ids=["no-rename", "rename"])
def test_apply_chosen_name_leaves_its_input_untouched(wizard):
    import copy

    from pipeline.chosen_name import apply_chosen_name

    world = {"protagonist": {"name": "Valentin", "backstory": "Valentin a fui."}}
    before = copy.deepcopy(world)
    out = apply_chosen_name(world, {"name": wizard})
    assert out is not None and out["protagonist"]["name"] == wizard
    assert world == before


@pytest.mark.parametrize("name", ["<prénom inventé>", "Kira <inventé>"])
def test_protagonist_name_rejects_the_invented_name_marker(name):
    from pydantic import ValidationError

    from schema import ProtagonistData

    with pytest.raises(ValidationError):
        ProtagonistData.model_validate({"name": name, "skills": [{"name": "a", "level": 1},
                                                                 {"name": "b", "level": 2}]})


def test_blank_name_prompt_explains_the_marker():
    from prompts.world_generation_prompt import (INVENTED_NAME_MARKER,
                                                 build_world_generation_user_prompt)

    line = next(line for line in build_world_generation_user_prompt().splitlines()
                if line.startswith("Nom : à inventer"))
    assert INVENTED_NAME_MARKER in line


@pytest.mark.parametrize("wizard", [None, {"name": ""}, {"name": "<x>"}, {"name": "PROTAGONIST"}])
def test_blank_or_unusable_wizard_name_keeps_a_usable_model_name(wizard):
    from pipeline.chosen_name import apply_chosen_name

    out = apply_chosen_name({"protagonist": {"name": "Valentin"}}, wizard)
    assert out == {"protagonist": {"name": "Valentin"}}


def test_marker_name_is_replaced_by_the_default_and_its_references_follow():
    from pipeline.chosen_name import apply_chosen_name

    marker = "<prénom inventé>"
    out = apply_chosen_name({"protagonist": {"name": marker, "backstory": f"{marker} a fui."},
                             "initial_relations": [{"source_ref": marker, "target_ref": "Ossek"}]},
                            None)
    assert out == {"protagonist": {"name": DEFAULT_PROTAGONIST_NAME,
                                   "backstory": f"{DEFAULT_PROTAGONIST_NAME} a fui."},
                   "initial_relations": [{"source_ref": DEFAULT_PROTAGONIST_NAME,
                                          "target_ref": "Ossek"}]}
