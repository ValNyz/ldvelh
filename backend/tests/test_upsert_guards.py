"""
Entity upserts never wipe or reveal (#87): an extractor that lists an existing entity again
in entities_created must not overwrite a stored value with a default, an empty value or
NULL, and must not change known_by_protagonist (only explicit reveals do).
"""

from llm.session import LLMSession
from schema import EntityCreation, RelationData, RelationType
from services.extraction.characters import CharactersExtractor
from services.extraction.locations import LocationsExtractor
from services.extraction.organizations import OrganizationsExtractor
from services.game_service import GameService
from tests.test_llm_session import FakeProvider


async def _run(extractor_cls, test_pool, game_id, raw_result, cycle=1):
    """Run one extractor through its real write path with a canned LLM result."""
    extractor = extractor_cls(test_pool, game_id, LLMSession.from_provider(FakeProvider()))

    async def fake_call(*_args, **_kwargs):
        return raw_result, {"cost_usd": 0.0}

    extractor._call_llm = fake_call
    result = await extractor.run("texte", {}, cycle)
    assert result["stats"]["errors"] == []
    return extractor


async def _row(test_pool, table, game_id, name):
    async with test_pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT * FROM {table} WHERE game_id = $1 AND name = $2", game_id, name)


async def _game(test_pool, test_user):
    return await GameService(test_pool).create_game(test_user["id"])


HIDDEN_NPC = {
    "entity_type": "character",
    "name": "Justine Lépicier",
    "known_by_protagonist": False,
    "unknown_name": "la femme au manteau gris",
    "data": {"traits": ["méfiante", "loyale"], "description": "Manteau gris, regard vif",
             "species": "humaine", "mood": "sur ses gardes", "occupation": "pilote"},
}


class TestCharacterUpsert:
    async def test_recreating_hidden_npc_keeps_it_hidden_and_keeps_traits(
        self, test_pool, test_user
    ):
        game_id = await _game(test_pool, test_user)
        await _run(CharactersExtractor, test_pool, game_id,
                   {"entities_created": [HIDDEN_NPC]})
        # The extractor lists her again with defaults only: known defaults to True,
        # traits to [].
        await _run(CharactersExtractor, test_pool, game_id,
                   {"entities_created": [{"name": "Justine Lépicier"}]}, cycle=2)
        row = await _row(test_pool, "characters", game_id, "Justine Lépicier")
        assert row["known_by_protagonist"] is False
        assert row["unknown_name"] == "la femme au manteau gris"
        assert row["traits"] == ["méfiante", "loyale"]

    async def test_explicit_known_true_in_creation_does_not_reveal(
        self, test_pool, test_user
    ):
        game_id = await _game(test_pool, test_user)
        await _run(CharactersExtractor, test_pool, game_id,
                   {"entities_created": [HIDDEN_NPC]})
        await _run(CharactersExtractor, test_pool, game_id, {"entities_created": [
            {"name": "Justine Lépicier", "known_by_protagonist": True}]}, cycle=2)
        row = await _row(test_pool, "characters", game_id, "Justine Lépicier")
        assert row["known_by_protagonist"] is False

    async def test_recreating_known_npc_as_unknown_does_not_demote(
        self, test_pool, test_user
    ):
        game_id = await _game(test_pool, test_user)
        await _run(CharactersExtractor, test_pool, game_id, {"entities_created": [
            {"name": "Marcus", "known_by_protagonist": True}]})
        await _run(CharactersExtractor, test_pool, game_id, {"entities_created": [
            {"name": "Marcus", "known_by_protagonist": False,
             "unknown_name": "l'homme au bar"}]}, cycle=2)
        row = await _row(test_pool, "characters", game_id, "Marcus")
        assert row["known_by_protagonist"] is True
        assert row["unknown_name"] is None

    async def test_non_empty_traits_still_replace_stored_traits(self, test_pool, test_user):
        game_id = await _game(test_pool, test_user)
        await _run(CharactersExtractor, test_pool, game_id,
                   {"entities_created": [HIDDEN_NPC]})
        await _run(CharactersExtractor, test_pool, game_id, {"entities_created": [
            {"name": "Justine Lépicier", "data": {"traits": ["rancunière"]}}]}, cycle=2)
        row = await _row(test_pool, "characters", game_id, "Justine Lépicier")
        assert row["traits"] == ["rancunière"]

    async def test_empty_strings_do_not_wipe_text_fields(self, test_pool, test_user):
        game_id = await _game(test_pool, test_user)
        await _run(CharactersExtractor, test_pool, game_id,
                   {"entities_created": [HIDDEN_NPC]})
        await _run(CharactersExtractor, test_pool, game_id, {"entities_created": [
            {"name": "Justine Lépicier", "data": {
                "description": "", "species": "", "mood": "", "occupation": ""}}]},
            cycle=2)
        row = await _row(test_pool, "characters", game_id, "Justine Lépicier")
        assert row["description"] == "Manteau gris, regard vif"
        assert row["species"] == "humaine"
        assert row["mood"] == "sur ses gardes"
        assert row["occupation"] == "pilote"

    async def test_non_empty_text_fields_still_update(self, test_pool, test_user):
        game_id = await _game(test_pool, test_user)
        await _run(CharactersExtractor, test_pool, game_id,
                   {"entities_created": [HIDDEN_NPC]})
        await _run(CharactersExtractor, test_pool, game_id, {"entities_created": [
            {"name": "Justine Lépicier", "data": {"mood": "détendue"}}]}, cycle=2)
        row = await _row(test_pool, "characters", game_id, "Justine Lépicier")
        assert row["mood"] == "détendue"
        assert row["description"] == "Manteau gris, regard vif"


class TestLocationUpsert:
    async def test_empty_strings_do_not_wipe_location_fields(self, test_pool, test_user):
        game_id = await _game(test_pool, test_user)
        full = {"entity_type": "location", "name": "Le Quart de Cycle", "data": {
            "location_type": "bar", "sector": "anneau B",
            "description": "Bar enfumé", "atmosphere": "feutrée"}}
        await _run(LocationsExtractor, test_pool, game_id, {"entities_created": [full]})
        await _run(LocationsExtractor, test_pool, game_id, {"entities_created": [
            {"name": "Le Quart de Cycle", "data": {
                "location_type": "", "sector": "", "description": "",
                "atmosphere": ""}}]}, cycle=2)
        row = await _row(test_pool, "locations", game_id, "Le Quart de Cycle")
        assert (row["location_type"], row["sector"], row["description"],
                row["atmosphere"]) == ("bar", "anneau B", "Bar enfumé", "feutrée")


class TestOrganizationUpsert:
    async def test_empty_strings_do_not_wipe_organization_fields(
        self, test_pool, test_user
    ):
        game_id = await _game(test_pool, test_user)
        full = {"entity_type": "organization", "name": "Syndicat des Docks", "data": {
            "org_type": "syndicat", "domain": "logistique",
            "description": "Contrôle les quais"}}
        await _run(OrganizationsExtractor, test_pool, game_id,
                   {"entities_created": [full]})
        await _run(OrganizationsExtractor, test_pool, game_id, {"entities_created": [
            {"name": "Syndicat des Docks", "data": {
                "org_type": "", "domain": "", "description": ""}}]}, cycle=2)
        row = await _row(test_pool, "organizations", game_id, "Syndicat des Docks")
        assert (row["org_type"], row["domain"], row["description"]) == (
            "syndicat", "logistique", "Contrôle les quais")


class TestRelationUpsert:
    async def _relation_known(self, test_pool, game_id, extractor, known_first, known_again,
                              context_again="liés"):
        async with test_pool.acquire() as conn:
            await extractor.populator.load_registry(conn)
            for known, context in ((known_first, "liés en secret"),
                                   (known_again, context_again)):
                await extractor.populator.create_relation(conn, RelationData(
                    source_ref="Justine Lépicier", target_ref="Marcus",
                    relation_type=RelationType.KNOWS, level=5, context=context,
                    known_by_protagonist=known))
            return await conn.fetchrow(
                "SELECT known_by_protagonist, context FROM relations WHERE game_id = $1",
                game_id)

    async def _two_npcs(self, test_pool, test_user):
        game_id = await _game(test_pool, test_user)
        extractor = await _run(CharactersExtractor, test_pool, game_id, {
            "entities_created": [HIDDEN_NPC, {"name": "Marcus"}]})
        return game_id, extractor

    async def test_recreating_hidden_relation_does_not_reveal(self, test_pool, test_user):
        game_id, extractor = await self._two_npcs(test_pool, test_user)
        row = await self._relation_known(test_pool, game_id, extractor, False, True)
        assert row["known_by_protagonist"] is False

    async def test_recreating_known_relation_does_not_demote(self, test_pool, test_user):
        game_id, extractor = await self._two_npcs(test_pool, test_user)
        row = await self._relation_known(test_pool, game_id, extractor, True, False)
        assert row["known_by_protagonist"] is True

    async def test_empty_context_does_not_wipe_relation_context(self, test_pool, test_user):
        game_id, extractor = await self._two_npcs(test_pool, test_user)
        row = await self._relation_known(test_pool, game_id, extractor, True, True,
                                         context_again="")
        assert row["context"] == "liés en secret"


class TestEntityCreationDefault:
    def test_unknown_name_without_flag_means_hidden(self):
        ec = EntityCreation(entity_type="character", name="Justine",
                            unknown_name="la femme au manteau gris")
        assert ec.known_by_protagonist is False

    def test_no_flag_and_no_unknown_name_stays_known(self):
        assert EntityCreation(entity_type="character", name="Marcus").known_by_protagonist

    def test_explicit_flag_wins_over_unknown_name(self):
        ec = EntityCreation(entity_type="character", name="Justine",
                            known_by_protagonist=True, unknown_name="la femme")
        assert ec.known_by_protagonist is True
