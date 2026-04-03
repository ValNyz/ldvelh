"""
Tests for ContextBuilder (integration, reads from DB)
and Tooltips helpers (unit tests on format functions).

ContextBuilder tests follow the same pattern as test_integration_flow:
create a game via API, populate world via GameService, then call ContextBuilder.

Tooltip helper tests are pure unit tests (no DB needed).
The tooltip API endpoint (/api/tooltips) uses a legacy `entities` table schema
that no longer exists in the current DB -- those tests are skipped with a note.
"""

import json
from uuid import UUID

import pytest

from helpers import auth_headers
from prompts.examples import WORLD_GENERATION_EXAMPLE

pytestmark = pytest.mark.integration


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def world_gen_data():
    """Parsed WorldGeneration dict from the canonical example."""
    return json.loads(WORLD_GENERATION_EXAMPLE)


async def _create_and_populate(client, test_user, test_pool, world_gen_data):
    """Helper: create a game, populate world, return (game_id, service, world_gen)."""
    from schema import WorldGeneration
    from services.game_service import GameService

    resp = await client.post("/api/games", headers=auth_headers(test_user["token"]))
    assert resp.status_code == 200
    game_id = UUID(resp.json()["gameId"])

    world_gen = WorldGeneration.model_validate(world_gen_data)
    service = GameService(test_pool)
    await service.process_init(game_id, world_gen)

    return game_id, service, world_gen


# =============================================================================
# CONTEXT BUILDER - INTEGRATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_build_context_fresh_game(client, test_user, test_pool, world_gen_data):
    """Build narration context on a freshly populated game (cycle 1, no messages)."""
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )

    # Determine arrival location from world gen example
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="Je regarde autour de moi",
            current_cycle=1,
            current_time="08h00",
            current_location_name=arrival_loc,
        )

    # Basic structure checks
    assert ctx.current_cycle == 1
    assert ctx.current_time == "08h00"
    assert ctx.player_input == "Je regarde autour de moi"

    # Protagonist should exist with correct name
    assert ctx.protagonist.name == "Valentin"
    assert ctx.protagonist.credits == 1650
    assert ctx.protagonist.energy.value == 2.5
    assert ctx.protagonist.morale.value == 2.5
    assert ctx.protagonist.health.value == 4.0
    assert "cuisine" in ctx.protagonist.hobbies

    # Employer should be resolved
    assert ctx.protagonist.employer == "Symbiose Tech"

    # World info
    assert ctx.world_name == "Escale Méridienne"
    assert ctx.world_atmosphere is not None

    # Current location should be resolved
    assert ctx.current_location.name == arrival_loc

    # Connected locations should exist (siblings in same sector or accessible)
    assert len(ctx.connected_locations) >= 1

    # All NPCs should be populated (at least 3 from example)
    assert len(ctx.all_npcs) >= 3

    # Organizations should be populated
    assert len(ctx.organizations) >= 1
    org_names = [o.name for o in ctx.organizations]
    assert "Symbiose Tech" in org_names

    # Personal AI should exist
    assert ctx.personal_ai is not None
    assert ctx.personal_ai.name == "Célimène"
    assert "sarcastique" in ctx.personal_ai.personality_traits

    # On a fresh game at cycle 1, cycle summaries only include pre-history
    # (cycle 0 arrival chronology entry may exist from world population)
    for cs in ctx.cycle_summaries:
        assert cs.cycle < 1  # Only cycles before the history window

    # No requested entity details on a fresh game
    assert ctx.requested_entity_details == {}


@pytest.mark.asyncio
async def test_build_context_protagonist_occupation(
    client, test_user, test_pool, world_gen_data
):
    """Verify protagonist occupation and employer are correctly loaded."""
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="test",
            current_cycle=1,
            current_time="08h00",
            current_location_name=arrival_loc,
        )

    assert ctx.protagonist.current_occupation == "développeur IA senior"
    assert ctx.protagonist.employer == "Symbiose Tech"

    # Verify employer appears in organizations with correct relation
    employer_org = next(
        (o for o in ctx.organizations if o.name == "Symbiose Tech"), None
    )
    assert employer_org is not None
    assert employer_org.protagonist_relation == "employed_by"


@pytest.mark.asyncio
async def test_build_context_inventory(client, test_user, test_pool, world_gen_data):
    """Verify inventory items are loaded from the populated world."""
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="test",
            current_cycle=1,
            current_time="08h00",
            current_location_name=arrival_loc,
        )

    # Example has 2 inventory items: Terminal personnel, Valise cabine
    assert len(ctx.inventory) >= 2
    inv_names = [i.name for i in ctx.inventory]
    assert "Terminal personnel" in inv_names
    assert "Valise cabine" in inv_names


@pytest.mark.asyncio
async def test_build_context_unknown_location(
    client, test_user, test_pool, world_gen_data
):
    """When the current location does not exist, fallback to default values."""
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="test",
            current_cycle=1,
            current_time="08h00",
            current_location_name="Lieu Inexistant",
        )

    # Should fallback to default LocationSummary
    assert ctx.current_location.name == "Lieu Inexistant"
    assert ctx.current_location.type == "Inconnu"
    assert ctx.current_location.sector == "Inconnu"


@pytest.mark.asyncio
async def test_build_context_active_arcs(
    client, test_user, test_pool, world_gen_data
):
    """Verify active arcs are loaded from populated world."""
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="test",
            current_cycle=1,
            current_time="08h00",
            current_location_name=arrival_loc,
        )

    # Example data has 3 narrative arcs
    assert len(ctx.active_arcs) >= 2
    arc_titles = [a.title for a in ctx.active_arcs]
    # At least one of the example arcs should be present
    assert any("malade" in t.lower() or "burnout" in t.lower() for t in arc_titles)


@pytest.mark.asyncio
async def test_build_context_all_npcs_light(
    client, test_user, test_pool, world_gen_data
):
    """All NPCs should appear in all_npcs as NPCLightSummary."""
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="test",
            current_cycle=1,
            current_time="08h00",
            current_location_name=arrival_loc,
        )

    # Should have at least 3 NPCs from example
    assert len(ctx.all_npcs) >= 3

    # Check that each NPC has the required light summary fields
    for npc in ctx.all_npcs:
        assert npc.name is not None
        assert isinstance(npc.known, bool)
        assert npc.species is not None


@pytest.mark.asyncio
async def test_build_context_after_messages(
    client, test_user, test_pool, world_gen_data
):
    """Build context after saving some messages (simulates a running game)."""
    from schema import NarrationOutput
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    # Process a narration turn to advance game state
    narration_data = {
        "narrative_text": (
            "Valentin traverse le terminal, l'air recycl\u00e9 lui pique les yeux. "
            "Quelques voyageurs press\u00e9s se faufilent entre les kiosques. "
            "Un panneau lumineux indique les arriv\u00e9es du jour."
        ),
        "time": {"new_time": "09h30", "ellipse": False},
        "current_location": arrival_loc,
        "npcs_present": [],
        "suggested_actions": ["Explorer", "S'asseoir"],
        "gauge_deltas": [],
        "credit_delta": None,
        "inventory_hints": [],
        "entity_reveals": [],
        "info_requests": [],
        "extraction_triggers": [],
    }
    narration = NarrationOutput.model_validate(narration_data)
    await service.process_light(game_id, narration, current_cycle=1)
    await service.save_messages(
        game_id=game_id,
        user_message="Je traverse le terminal",
        assistant_message=narration.narrative_text,
        cycle=1,
        time="09h30",
        location_ref=arrival_loc,
    )

    # Now build context for the next turn
    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="Je cherche un caf\u00e9",
            current_cycle=1,
            current_time="09h30",
            current_location_name=arrival_loc,
        )

    assert ctx.current_time == "09h30"
    assert ctx.player_input == "Je cherche un caf\u00e9"
    # Game state should still be valid
    assert ctx.protagonist.name == "Valentin"
    assert ctx.world_name == "Escale M\u00e9ridienne"


@pytest.mark.asyncio
async def test_build_context_organizations_relation(
    client, test_user, test_pool, world_gen_data
):
    """Verify organization-protagonist relation is set correctly."""
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="test",
            current_cycle=1,
            current_time="08h00",
            current_location_name=arrival_loc,
        )

    # Symbiose Tech should be marked as employer
    symbiose = next(
        (o for o in ctx.organizations if o.name == "Symbiose Tech"), None
    )
    assert symbiose is not None
    assert symbiose.protagonist_relation == "employed_by"
    assert symbiose.org_type == "company"
    assert symbiose.domain == "IA agricole"

    # Any non-employer org should have protagonist_relation = None
    non_employer_orgs = [
        o for o in ctx.organizations if o.name != "Symbiose Tech"
    ]
    for org in non_employer_orgs:
        assert org.protagonist_relation is None


@pytest.mark.asyncio
async def test_build_context_personal_ai_details(
    client, test_user, test_pool, world_gen_data
):
    """Verify personal AI details from the populated world."""
    from services.context_builder import ContextBuilder

    game_id, service, world_gen = await _create_and_populate(
        client, test_user, test_pool, world_gen_data
    )
    arrival_loc = world_gen.arrival_event.arrival_location_ref

    builder = ContextBuilder(test_pool, game_id)
    async with test_pool.acquire() as conn:
        ctx = await builder.build(
            conn,
            player_input="test",
            current_cycle=1,
            current_time="08h00",
            current_location_name=arrival_loc,
        )

    ai = ctx.personal_ai
    assert ai is not None
    assert ai.name == "C\u00e9lim\u00e8ne"
    assert ai.voice_description == "voix rauque, d\u00e9bit lent"
    assert "sarcastique" in ai.personality_traits
    assert "observatrice" in ai.personality_traits
    assert ai.quirk is not None


# =============================================================================
# CONTEXT BUILDER - UNIT TESTS (static/helper methods)
# =============================================================================


class TestExtractParticipantNames:
    """Unit tests for ContextBuilder._extract_participant_names (static method)."""

    def test_dict_participants(self):
        from services.context_builder import ContextBuilder

        participants = [{"name": "Alice"}, {"name": "Bob"}]
        names = ContextBuilder._extract_participant_names(participants)
        assert names == ["Alice", "Bob"]

    def test_string_json_participants(self):
        from services.context_builder import ContextBuilder

        participants = ['{"name": "Alice"}', '{"name": "Bob"}']
        names = ContextBuilder._extract_participant_names(participants)
        assert names == ["Alice", "Bob"]

    def test_plain_string_participants(self):
        from services.context_builder import ContextBuilder

        # Non-JSON strings should be returned as-is
        participants = ["Alice", "Bob"]
        names = ContextBuilder._extract_participant_names(participants)
        assert names == ["Alice", "Bob"]

    def test_mixed_participants(self):
        from services.context_builder import ContextBuilder

        participants = [{"name": "Alice"}, '{"name": "Bob"}', "Charlie"]
        names = ContextBuilder._extract_participant_names(participants)
        assert names == ["Alice", "Bob", "Charlie"]

    def test_empty_participants(self):
        from services.context_builder import ContextBuilder

        assert ContextBuilder._extract_participant_names([]) == []

    def test_none_name_filtered(self):
        from services.context_builder import ContextBuilder

        participants = [{"name": None}, {"other": "value"}]
        names = ContextBuilder._extract_participant_names(participants)
        assert names == []


class TestBuildAllNpcsLight:
    """Unit tests for ContextBuilder._build_all_npcs_light."""

    def _make_builder(self):
        from services.context_builder import ContextBuilder

        # Pool and game_id are not used by _build_all_npcs_light
        return ContextBuilder(pool=None, game_id=None)

    def test_known_npc(self):
        builder = self._make_builder()
        characters = [
            {
                "name": "Alice",
                "known_by_protagonist": True,
                "unknown_name": None,
                "occupation": "engineer",
                "species": "human",
                "relation_level": 5,
                "usual_location": "Lab",
                "ambient": None,
            }
        ]
        result = builder._build_all_npcs_light(characters)
        assert len(result) == 1
        assert result[0].name == "Alice"
        assert result[0].known is True

    def test_unknown_npc_uses_unknown_name(self):
        builder = self._make_builder()
        characters = [
            {
                "name": "Secret Agent",
                "known_by_protagonist": False,
                "unknown_name": "Mysterious Stranger",
                "occupation": None,
                "species": "human",
                "relation_level": None,
                "usual_location": None,
                "ambient": None,
            }
        ]
        result = builder._build_all_npcs_light(characters)
        assert result[0].name == "Mysterious Stranger"
        assert result[0].known is False

    def test_unknown_npc_no_unknown_name_defaults(self):
        builder = self._make_builder()
        characters = [
            {
                "name": "Hidden NPC",
                "known_by_protagonist": False,
                "unknown_name": None,
                "occupation": None,
                "species": "alien",
                "relation_level": None,
                "usual_location": None,
                "ambient": None,
            }
        ]
        result = builder._build_all_npcs_light(characters)
        assert result[0].name == "Inconnu(e)"


class TestBuildRelevantNpcs:
    """Unit tests for ContextBuilder._build_relevant_npcs."""

    def _make_builder(self):
        from services.context_builder import ContextBuilder

        return ContextBuilder(pool=None, game_id=None)

    def test_excludes_present_npcs(self):
        builder = self._make_builder()
        all_characters = [
            {
                "name": "Alice",
                "known_by_protagonist": True,
                "unknown_name": None,
                "occupation": "engineer",
                "species": "human",
                "relation_level": 5,
                "relation_context": "colleague",
                "usual_location": "Lab",
                "traits": ["friendly"],
                "mood": "happy",
                "ambient": None,
            }
        ]
        # Alice is present, so she should be excluded
        result = builder._build_relevant_npcs(all_characters, exclude_names={"Alice"})
        assert len(result) == 0

    def test_excludes_npcs_without_relation(self):
        builder = self._make_builder()
        all_characters = [
            {
                "name": "Stranger",
                "known_by_protagonist": True,
                "unknown_name": None,
                "occupation": None,
                "species": "human",
                "relation_level": None,
                "relation_context": None,
                "usual_location": None,
                "traits": [],
                "mood": None,
                "ambient": None,
            }
        ]
        result = builder._build_relevant_npcs(all_characters, exclude_names=set())
        # NPCs with relation_level=None should not be included
        assert len(result) == 0

    def test_max_five_results(self):
        builder = self._make_builder()
        all_characters = [
            {
                "name": f"NPC_{i}",
                "known_by_protagonist": True,
                "unknown_name": None,
                "occupation": "worker",
                "species": "human",
                "relation_level": 10 - i,
                "relation_context": "acquaintance",
                "usual_location": "Market",
                "traits": [],
                "mood": None,
                "ambient": None,
            }
            for i in range(10)
        ]
        result = builder._build_relevant_npcs(all_characters, exclude_names=set())
        assert len(result) == 5


class TestEnrichNpcsWithArcs:
    """Unit tests for ContextBuilder._enrich_npcs_with_arcs."""

    def _make_builder(self):
        from services.context_builder import ContextBuilder

        return ContextBuilder(pool=None, game_id=None)

    def test_enriches_matching_npc(self):
        from schema.narration import NPCSummary

        builder = self._make_builder()

        npc = NPCSummary(
            name="Alice",
            occupation="engineer",
            species="human",
            relationship_level=5,
            usual_location="Lab",
            known=True,
            traits=["friendly"],
        )

        arcs_rows = [
            {
                "title": "The Secret Project",
                "domain": "professional",
                "situation": "Working on a classified experiment",
                "intensity": 4,
                "participants": [{"name": "Alice"}],
            }
        ]

        builder._enrich_npcs_with_arcs([npc], arcs_rows)
        assert len(npc.active_arcs) == 1
        assert npc.active_arcs[0].title == "The Secret Project"

    def test_no_match_leaves_empty(self):
        from schema.narration import NPCSummary

        builder = self._make_builder()

        npc = NPCSummary(
            name="Bob",
            occupation="cook",
            species="human",
            relationship_level=3,
            usual_location="Kitchen",
            known=True,
            traits=["calm"],
        )

        arcs_rows = [
            {
                "title": "Alice's Quest",
                "domain": "personal",
                "situation": "Something",
                "intensity": 3,
                "participants": [{"name": "Alice"}],
            }
        ]

        builder._enrich_npcs_with_arcs([npc], arcs_rows)
        assert len(npc.active_arcs) == 0

    def test_max_two_arcs_per_npc(self):
        from schema.narration import NPCSummary

        builder = self._make_builder()

        npc = NPCSummary(
            name="Alice",
            occupation="engineer",
            species="human",
            relationship_level=5,
            usual_location="Lab",
            known=True,
            traits=["friendly"],
        )

        arcs_rows = [
            {
                "title": f"Arc {i}",
                "domain": "personal",
                "situation": "...",
                "intensity": 3,
                "participants": [{"name": "Alice"}],
            }
            for i in range(5)
        ]

        builder._enrich_npcs_with_arcs([npc], arcs_rows)
        # Should be capped at 2 arcs per NPC
        assert len(npc.active_arcs) == 2


# =============================================================================
# TOOLTIPS - UNIT TESTS (helper functions)
# =============================================================================


class TestTruncate:
    """Unit tests for the truncate() helper."""

    def test_short_text_unchanged(self):
        from api.tooltips import truncate

        assert truncate("hello", 50) == "hello"

    def test_exact_length_unchanged(self):
        from api.tooltips import truncate

        text = "x" * 50
        assert truncate(text, 50) == text

    def test_long_text_truncated(self):
        from api.tooltips import truncate

        text = "x" * 60
        result = truncate(text, 50)
        assert len(result) == 50
        assert result.endswith("\u2026")

    def test_empty_string(self):
        from api.tooltips import truncate

        assert truncate("", 50) == ""

    def test_none_returns_none(self):
        from api.tooltips import truncate

        # truncate guards with "if not text"
        assert truncate(None, 50) is None


class TestFormatConnaissance:
    """Unit tests for format_connaissance()."""

    def test_known_key(self):
        from api.tooltips import format_connaissance

        result = format_connaissance("metier", "Ingénieur")
        assert result == "M\u00e9tier: Ing\u00e9nieur"

    def test_unknown_key_title_case(self):
        from api.tooltips import format_connaissance

        result = format_connaissance("custom_field", "some value")
        assert result == "Custom Field: some value"

    def test_list_value(self):
        from api.tooltips import format_connaissance

        result = format_connaissance("traits", ["calm", "friendly", "smart"])
        assert result == "Traits: calm, friendly, smart"

    def test_long_value_truncated(self):
        from api.tooltips import format_connaissance

        long_val = "x" * 100
        result = format_connaissance("metier", long_val)
        # truncate default is 50, so label + ": " + truncated value
        assert "\u2026" in result

    def test_physique_key(self):
        from api.tooltips import format_connaissance

        result = format_connaissance("physique", "Grand, cheveux noirs")
        assert result.startswith("Apparence:")

    def test_espece_key(self):
        from api.tooltips import format_connaissance

        result = format_connaissance("espece", "Keth")
        assert result == "Esp\u00e8ce: Keth"

    def test_type_lieu_key(self):
        from api.tooltips import format_connaissance

        result = format_connaissance("type_lieu", "café")
        assert result == "Type: caf\u00e9"


class TestFormatTooltip:
    """Unit tests for format_tooltip()."""

    def test_personnage_tooltip(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "personnage",
            "entite_nom": "Alice Dupont",
            "connaissances": {
                "metier": "ingénieure",
                "espece": "human",
                "traits": ["calme", "intelligente"],
            },
            "relation_valentin": {"type": "ami_de"},
        }
        result = format_tooltip(data)

        assert result.icon == "\U0001f464"  # person emoji
        assert result.nom == "Alice Dupont"
        assert result.type == "personnage"
        assert result.relation == "Ami"
        # Check that connaissances are formatted
        assert any("M\u00e9tier" in info for info in result.infos)
        assert any("Esp\u00e8ce" in info for info in result.infos)

    def test_lieu_tooltip(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "lieu",
            "entite_nom": "Le Quart de Cycle",
            "connaissances": {
                "type_lieu": "café",
                "ambiance": "fonctionnel",
            },
            "relation_valentin": None,
        }
        result = format_tooltip(data)

        assert result.icon == "\U0001f4cd"  # pin emoji
        assert result.nom == "Le Quart de Cycle"
        assert result.type == "lieu"
        assert result.relation is None
        assert any("Type" in info for info in result.infos)
        assert any("Ambiance" in info for info in result.infos)

    def test_organisation_tooltip(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "organisation",
            "entite_nom": "Symbiose Tech",
            "connaissances": {
                "domaine": "IA agricole",
                "type_org": "company",
            },
            "relation_valentin": {"type": "employe_de"},
        }
        result = format_tooltip(data)

        assert result.icon == "\U0001f3e2"  # office building emoji
        assert result.relation == "Employeur"
        assert any("Domaine" in info for info in result.infos)

    def test_unknown_type(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "unknown_type",
            "entite_nom": "Mystery",
            "connaissances": {},
            "relation_valentin": None,
        }
        result = format_tooltip(data)

        assert result.icon == "\u2753"  # question mark emoji
        assert result.nom == "Mystery"
        assert result.infos == []
        assert result.relation is None

    def test_empty_connaissances(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "personnage",
            "entite_nom": "Nobody",
            "connaissances": {},
            "relation_valentin": None,
        }
        result = format_tooltip(data)

        assert result.infos == []
        assert result.relation is None

    def test_priority_order_respected(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "personnage",
            "entite_nom": "Test",
            "connaissances": {
                "hobby": "reading",
                "metier": "doctor",
                "espece": "human",
                "custom_field": "custom_value",
            },
            "relation_valentin": None,
        }
        result = format_tooltip(data)

        # metier should come before espece which should come before hobby
        # custom_field should come last (not in PRIORITY_ORDER)
        info_labels = [info.split(":")[0] for info in result.infos]
        metier_idx = info_labels.index("M\u00e9tier")
        espece_idx = info_labels.index("Esp\u00e8ce")
        hobby_idx = info_labels.index("Hobby")
        custom_idx = info_labels.index("Custom Field")

        assert metier_idx < espece_idx
        assert espece_idx < hobby_idx
        assert hobby_idx < custom_idx

    def test_relation_valentin_empty_type(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "personnage",
            "entite_nom": "Test",
            "connaissances": {},
            "relation_valentin": {"type": ""},
        }
        result = format_tooltip(data)

        # Empty string is falsy, so relation should be None
        assert result.relation is None

    def test_relation_valentin_unknown_type(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "personnage",
            "entite_nom": "Test",
            "connaissances": {},
            "relation_valentin": {"type": "unknown_relation"},
        }
        result = format_tooltip(data)

        # Unknown relation type should pass through as-is
        assert result.relation == "unknown_relation"

    def test_nom_key_excluded_from_infos(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "personnage",
            "entite_nom": "Test",
            "connaissances": {
                "nom": "Test Name",
                "metier": "doctor",
            },
            "relation_valentin": None,
        }
        result = format_tooltip(data)

        # "nom" key should be excluded from infos
        assert not any("Test Name" in info for info in result.infos)
        assert any("M\u00e9tier" in info for info in result.infos)

    def test_falsy_connaissance_values_excluded(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "personnage",
            "entite_nom": "Test",
            "connaissances": {
                "metier": "doctor",
                "espece": "",
                "traits": [],
                "age": None,
            },
            "relation_valentin": None,
        }
        result = format_tooltip(data)

        # Only "metier" has a truthy value, so only one info line
        assert len(result.infos) == 1
        assert "M\u00e9tier" in result.infos[0]

    def test_ia_type_tooltip(self):
        from api.tooltips import format_tooltip

        data = {
            "entite_type": "ia",
            "entite_nom": "C\u00e9lim\u00e8ne",
            "connaissances": {
                "voix": "voix rauque",
                "occupation": "assistant personnel",
            },
            "relation_valentin": None,
        }
        result = format_tooltip(data)

        assert result.icon == "\U0001f916"  # robot emoji
        assert result.nom == "C\u00e9lim\u00e8ne"
        assert any("Voix" in info for info in result.infos)


# =============================================================================
# TOOLTIPS - PYDANTIC MODELS
# =============================================================================


class TestTooltipModels:
    """Test the Pydantic response models."""

    def test_tooltip_info_model(self):
        from api.tooltips import TooltipInfo

        info = TooltipInfo(
            icon="\U0001f464",
            nom="Alice",
            type="personnage",
            infos=["M\u00e9tier: ing\u00e9nieure"],
            relation="Ami",
        )
        assert info.nom == "Alice"
        assert info.relation == "Ami"

    def test_tooltip_info_no_relation(self):
        from api.tooltips import TooltipInfo

        info = TooltipInfo(
            icon="\U0001f4cd",
            nom="Le Caf\u00e9",
            type="lieu",
            infos=[],
        )
        assert info.relation is None

    def test_tooltip_entry_model(self):
        from api.tooltips import TooltipEntry, TooltipInfo
        from uuid import uuid4

        entry = TooltipEntry(
            entite_id=uuid4(),
            entite_type="personnage",
            entite_nom="Alice",
            alias=["Al"],
            connaissances={"metier": "engineer"},
            formatted=TooltipInfo(
                icon="\U0001f464",
                nom="Alice",
                type="personnage",
                infos=["M\u00e9tier: engineer"],
            ),
        )
        assert entry.entite_nom == "Alice"
        assert entry.alias == ["Al"]
        assert entry.relation_valentin is None
