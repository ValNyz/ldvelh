"""The harness itself must reach the app and record LLM calls."""


async def test_init_world_reaches_world_gen(harness):
    game_id = await harness.create_game("none")
    events = await harness.init_world(game_id)
    types = harness.summarize(events)
    assert "error" not in types, events
    purposes = harness.llm.purposes()
    assert "world_gen" in purposes
    # Proves the double served every call: nothing fell through to an unclassified/real provider.
    assert purposes and "unknown" not in purposes
    db = await harness.db_summary(game_id)
    assert db["locations"] > 0 and db["characters"] > 0


def test_default_payloads_validate_against_schemas():
    """Identity/director constants must be valid, not merely ignored, by their parsers."""
    import json

    from schema.director import DirectorOutput
    from services.identity import decision
    from services.llm_providers import StructuredOutputMode
    from tests.characterization import payloads

    mode = StructuredOutputMode.TOOL_USE
    assert decision.parse(json.loads(payloads.IDENTITY_EMPTY), mode) == []
    out = DirectorOutput.model_validate(json.loads(payloads.DIRECTOR))
    assert out.narrator_guidance and out.tension_level == 3


def test_new_character_payloads_validate_against_schemas():
    import json

    from schema.extraction import CharactersExtraction
    from services.identity import decision
    from services.llm_providers import StructuredOutputMode
    from tests.characterization import payloads

    mode = StructuredOutputMode.TOOL_USE
    [new] = decision.parse(json.loads(payloads.IDENTITY_NEW_CHARACTER), mode)
    assert (new.surface, new.decision) == (payloads.NEW_CHARACTER_NAME, "NEW")
    assert payloads.NEW_CHARACTER_NAME in payloads.NEW_CHARACTER_TEXT
    prompt = f"## ENTITIES IN THIS SCENE\n- E15 · character · {payloads.NEW_CHARACTER_NAME} · known · new"
    ext = CharactersExtraction.model_validate(payloads.extract_characters_new(prompt))
    assert ext.entities_updated[0].entity_ref == "E15"


def test_engine_payloads_validate_against_schemas():
    import json

    from schema.engine import MechanicalDecision
    from schema.narration import NarrationOutput
    from tests.characterization import payloads

    out = NarrationOutput.model_validate(json.loads(payloads.NARRATION_WITH_COMPEL))
    assert out.compel_aspect and out.compel_result == "proposed"
    assert MechanicalDecision.model_validate(
        json.loads(payloads.mechanical(requires_test=True))).requires_test


def test_frozen_world_and_narration_fixtures_validate_against_schemas():
    """The frozen fixtures must stay valid for the current schemas (drift shows up here)."""
    import json

    from schema.narration import NarrationOutput
    from schema.world_generation import WorldGeneration
    from tests.characterization import payloads

    WorldGeneration.model_validate(json.loads(payloads.WORLD_GEN))
    out = NarrationOutput.model_validate(json.loads(payloads.NARRATION))
    assert out.narrative_text
