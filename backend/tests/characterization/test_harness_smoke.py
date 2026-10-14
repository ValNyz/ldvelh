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
    """Resolver/director constants must be valid, not merely ignored, by their models."""
    import json

    from schema.director import DirectorOutput
    from schema.extraction import EntityResolution
    from tests.characterization import payloads

    EntityResolution.model_validate(json.loads(payloads.RESOLVER_EMPTY))
    out = DirectorOutput.model_validate(json.loads(payloads.DIRECTOR))
    assert out.narrator_guidance and out.tension_level == 3


def test_new_character_payloads_validate_against_schemas():
    import json

    from schema.extraction import CharactersExtraction, EntityResolution
    from tests.characterization import payloads

    res = EntityResolution.model_validate(json.loads(payloads.RESOLVER_NEW_CHARACTER))
    assert res.new[0].suggested_name == payloads.NEW_CHARACTER_NAME
    ext = CharactersExtraction.model_validate(payloads.EXTRACT_CHARACTERS_NEW)
    assert ext.entities_created[0].name == payloads.NEW_CHARACTER_NAME


def test_engine_payloads_validate_against_schemas():
    import json

    from schema.engine import MechanicalDecision
    from schema.narration import NarrationOutput
    from tests.characterization import payloads

    out = NarrationOutput.model_validate(json.loads(payloads.NARRATION_WITH_COMPEL))
    assert out.compel_aspect and out.compel_result == "proposed"
    assert MechanicalDecision.model_validate(
        json.loads(payloads.mechanical(requires_test=True))).requires_test
