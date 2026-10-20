"""IdentityService (#153, spec §4.4, §4.6, §4.11): creation with derived aliases, reuse of a
label unless a verified trap, internal label suffixes, typed references, writes by id."""

from uuid import UUID

import pytest

from config import get_identity_config
from repos import entities, turns
from repos.uow import uow
from services.identity.aliases import AliasSpec
from services.identity.service import IdentityService
from services.identity.types import (
    IdentityWriteMiss,
    NewEntitySpec,
    RefUnresolved,
    ResolvedRef,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def game(test_pool, test_user) -> UUID:
    async with test_pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
            test_user["id"],
        )


@pytest.fixture
def service(game) -> IdentityService:
    return IdentityService(game, lang="fr", config=get_identity_config())


async def _aliases(conn, game_id, entity_id) -> dict[str, tuple]:
    return {
        a.alias: (a.kind, a.source, a.known, a.secret, a.turn_id)
        for a in await entities.list_aliases(conn, game_id, entity_id)
    }


async def _events(conn, game_id, kind) -> list:
    return await conn.fetch(
        "SELECT entity_id, turn_id, payload FROM identity_events"
        " WHERE game_id = $1 AND kind = $2 ORDER BY id",
        game_id,
        kind,
    )


async def test_for_game_reads_language_and_genre(test_pool, game):
    async with test_pool.acquire() as conn:
        service = await IdentityService.for_game(conn, game)
    assert service.game_id == game
    assert service.normalizer.pack.lang == "fr"
    assert service.lexicon.lang.lang == "fr"


async def test_create_entity_inserts_registry_aliases_and_returns_the_domain_id(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            voss = await service.create_entity(
                conn,
                NewEntitySpec(
                    "character",
                    "Docteur Elara Voss",
                    "proper_name",
                    known=False,
                    fields={"occupation": "médecin"},
                    aliases=[AliasSpec("la doctoresse", "nickname", True)],
                ),
                turn_id=turn_id,
                source="extractor",
            )
            chapel = await service.create_entity(
                conn,
                NewEntitySpec("location", "Saint Ondrev Kasso", "proper_name"),
                turn_id=turn_id,
                source="extractor",
            )
        character = await conn.fetchrow(
            "SELECT true_name, descriptor, known_by_protagonist, occupation"
            " FROM characters WHERE id = $1",
            voss,
        )
        registry = await conn.fetchrow(
            "SELECT entity_type, name, created_turn_id FROM entity_registry WHERE id = $1",
            voss,
        )
        voss_aliases = await _aliases(conn, game, voss)
        chapel_aliases = await _aliases(conn, game, chapel)
    assert dict(character) == {
        "true_name": "Docteur Elara Voss",
        "descriptor": None,
        "known_by_protagonist": False,
        "occupation": "médecin",
    }
    assert dict(registry) == {
        "entity_type": "character",
        "name": "Docteur Elara Voss",
        "created_turn_id": turn_id,
    }
    assert voss_aliases == {
        "Docteur Elara Voss": ("true_name", "system", False, False, turn_id),
        "Elara Voss": ("title", "extractor", False, False, turn_id),
        "Voss": ("short", "extractor", False, False, turn_id),
        "Elara": ("short", "extractor", False, False, turn_id),
        "la doctoresse": ("nickname", "extractor", True, False, turn_id),
    }
    assert chapel_aliases == {
        "Saint Ondrev Kasso": ("label", "system", True, False, turn_id),
        "Ondrev Kasso": ("title", "extractor", True, False, turn_id),
        "Kasso": ("short", "extractor", True, False, turn_id),
        "Ondrev": ("short", "extractor", True, False, turn_id),
    }


async def test_create_secret_entity_marks_every_alias_secret(test_pool, game, service):
    async with test_pool.acquire() as conn:
        vault = await service.create_entity(
            conn,
            NewEntitySpec(
                "location",
                "Chambre forte Ansa",
                "proper_name",
                known=False,
                secret=True,
            ),
            turn_id=None,
            source="world_gen",
        )
        aliases = await entities.list_aliases(conn, game, vault)
    assert aliases and all(a.secret and not a.known for a in aliases)


async def test_create_entity_reuses_an_existing_label_unless_trap(
    test_pool, game, service
):
    guard = NewEntitySpec("character", "Garde du sas", "descriptor")
    async with test_pool.acquire() as conn:
        quay = await service.create_entity(
            conn,
            NewEntitySpec("location", "Quai 9", "proper_name"),
            turn_id=None,
            source="extractor",
        )
        first = await service.create_entity(
            conn, guard, turn_id=None, source="extractor"
        )
        again = await service.create_entity(
            conn,
            NewEntitySpec("character", "le garde du sas", "descriptor"),
            turn_id=None,
            source="resolver",
        )
        trapped = await service.create_entity(
            conn,
            guard,
            turn_id=None,
            source="resolver",
            scene_location_id=quay,
            trap=True,
        )
        third = await service.create_entity(
            conn,
            guard,
            turn_id=None,
            source="resolver",
            scene_location_id=quay,
            trap=True,
        )
        rows = {
            r["id"]: (r["name"], r["descriptor"], r["label_suffix"], r["shown"])
            for r in await conn.fetch(
                "SELECT c.id, er.name, c.descriptor, c.label_suffix,"
                " display_for_player(c.id) AS shown"
                " FROM characters c JOIN entity_registry er ON er.id = c.id"
                " WHERE c.game_id = $1",
                game,
            )
        }
        reused = await _events(conn, game, "create_reused")
        suffixed = await _events(conn, game, "label_suffixed")
        by_label = await entities.find_entity(conn, game, "Garde du sas", "character")
    assert again == first
    assert rows == {
        first: ("Garde du sas", "Garde du sas", None, "Garde du sas"),
        trapped: ("Garde du sas (Quai 9)", "Garde du sas", "Quai 9", "Garde du sas"),
        third: ("Garde du sas (2)", "Garde du sas", "2", "Garde du sas"),
    }
    assert [e["entity_id"] for e in reused] == [first]
    assert [(e["entity_id"], e["payload"]["suffix_from"]) for e in suffixed] == [
        (trapped, "scene_location"),
        (third, "counter"),
    ]
    # Three guards share the descriptor: it names none of them any more.
    assert by_label is None


async def test_label_suffix_is_internal_for_every_entity_type(test_pool, game, service):
    """R14: a location homonym gets the suffix in its registry label only; its name, what
    the player reads and display_for_player stay bare; without a scene location, the
    counter. Renaming keeps the suffix out of the domain name."""
    async with test_pool.acquire() as conn:
        bar = await service.create_entity(
            conn,
            NewEntitySpec("location", "Le Bar du coin", "descriptor"),
            turn_id=None,
            source="extractor",
        )
        twin = await service.create_entity(
            conn,
            NewEntitySpec("location", "Le Bar du coin", "descriptor"),
            turn_id=None,
            source="extractor",
            trap=True,
        )
        row = await conn.fetchrow(
            "SELECT l.name, l.label_suffix, er.name AS label,"
            " display_for_player(l.id) AS shown"
            " FROM locations l JOIN entity_registry er ON er.id = l.id WHERE l.id = $1",
            twin,
        )
        twin_aliases = await _aliases(conn, game, twin)
        by_suffixed_label = await entities.find_entity(
            conn, game, "Le Bar du coin (2)", "location"
        )
        await service.update_entity(conn, twin, "location", {"description": "Enfumé."})
        label_after_update = await conn.fetchval(
            "SELECT name FROM entity_registry WHERE id = $1", twin
        )
    assert twin != bar
    assert dict(row) == {
        "name": "Le Bar du coin",
        "label_suffix": "2",
        "label": "Le Bar du coin (2)",
        "shown": "Le Bar du coin",
    }
    assert {k: v[0] for k, v in twin_aliases.items()} == {
        "Le Bar du coin": "label",
        "Le Bar du coin (2)": "label",
    }
    assert by_suffixed_label == twin
    assert label_after_update == "Le Bar du coin (2)"


async def test_create_descriptor_entity_is_known_and_has_no_true_name(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        elder = await service.create_entity(
            conn,
            NewEntitySpec("character", "La Kethari âgée", "descriptor"),
            turn_id=None,
            source="extractor",
        )
        row = await conn.fetchrow(
            "SELECT true_name, descriptor, known_by_protagonist,"
            " display_for_player(id) AS shown FROM characters WHERE id = $1",
            elder,
        )
        aliases = await _aliases(conn, game, elder)
    assert dict(row) == {
        "true_name": None,
        "descriptor": "La Kethari âgée",
        "known_by_protagonist": False,
        "shown": "La Kethari âgée",
    }
    assert aliases == {"La Kethari âgée": ("descriptor", "system", True, False, None)}


async def test_create_entity_refuses_reserved_types(test_pool, game, service):
    async with test_pool.acquire() as conn:
        with pytest.raises(ValueError):
            await service.create_entity(
                conn,
                NewEntitySpec("protagonist", "Rafe", "proper_name"),
                turn_id=None,
                source="extractor",
            )
        with pytest.raises(ValueError):
            await service.create_entity(
                conn,
                NewEntitySpec(
                    "location", "Quai", "proper_name", fields={"game_id": game}
                ),
                turn_id=None,
                source="extractor",
            )


async def test_resolve_ref_handles_protagonist_companion_handle_and_alias(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        pc = await conn.fetchval(
            "INSERT INTO protagonists (game_id, name) VALUES ($1, 'Rafe') RETURNING id",
            game,
        )
        pal = await conn.fetchval(
            "INSERT INTO companions (game_id, name) VALUES ($1, 'Célimène') RETURNING id",
            game,
        )
        tesk = await service.create_entity(
            conn,
            NewEntitySpec("character", "Tesk Vahrun", "proper_name", known=False),
            turn_id=None,
            source="world_gen",
        )
        tesk_handle = await entities.handle_of(conn, tesk)
        found = {
            "protagonist": await service.resolve_ref(
                conn, "PROTAGONIST", "protagonist"
            ),
            "companion": await service.resolve_ref(conn, "companion", "companion"),
            "handle": await service.resolve_ref(conn, f"E{tesk_handle}", "character"),
            "short alias": await service.resolve_ref(conn, "Vahrun", "character"),
            "unknown": await service.resolve_ref(conn, "Personne", "character"),
        }
        handles = await service.handles_for_prompt(conn, [tesk, pc])
        pc_handle = await entities.handle_of(conn, pc)
    assert found == {
        "protagonist": ResolvedRef(pc, pc_handle, "Rafe"),
        "companion": ResolvedRef(pal, found["companion"].handle, "Célimène"),
        # The label is what the player may read: never an unknown true name.
        "handle": ResolvedRef(tesk, tesk_handle, "Inconnu(e)"),
        "short alias": ResolvedRef(tesk, tesk_handle, "Inconnu(e)"),
        "unknown": None,
    }
    assert handles == {tesk: f"E{tesk_handle}", pc: f"E{pc_handle}"}


async def test_resolve_ref_returns_none_and_logs_an_event_on_ambiguity(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        for name in ("Ana Voss", "Bo Voss"):
            await service.create_entity(
                conn,
                NewEntitySpec("character", name, "proper_name"),
                turn_id=None,
                source="world_gen",
            )
        ambiguous = await service.resolve_ref(conn, "Voss", "character")
        unknown = await service.resolve_ref(conn, "Personne", "character")
        events = await _events(conn, game, "ambiguous_ref")
    assert ambiguous is None and unknown is None
    assert [e["payload"] for e in events] == [
        {"entity_type": "character", "candidates": 2}
    ]


async def test_update_entity_raises_on_zero_rows(test_pool, game, service):
    async with test_pool.acquire() as conn:
        quay = await service.create_entity(
            conn,
            NewEntitySpec("location", "Quai 9", "proper_name"),
            turn_id=None,
            source="extractor",
        )
        await service.update_entity(conn, quay, "location", {"description": "Venteux."})
        description = await conn.fetchval(
            "SELECT description FROM locations WHERE id = $1", quay
        )
        missing = UUID("00000000-0000-4000-8000-000000000000")
        with pytest.raises(IdentityWriteMiss) as miss:
            await service.update_entity(conn, missing, "location", {"description": "x"})
        with pytest.raises(IdentityWriteMiss):
            # Another type's table: no row.
            await service.update_entity(
                conn, quay, "organization", {"description": "x"}
            )
        with pytest.raises(ValueError):
            await service.update_entity(conn, quay, "location", {"id": missing})
    assert description == "Venteux."
    assert (miss.value.table, miss.value.entity_id) == ("locations", missing)
    assert "x" not in str(miss.value)


async def test_rename_keeps_the_old_name_as_former_name_alias(test_pool, game, service):
    async with test_pool.acquire() as conn:
        stranger = await service.create_entity(
            conn,
            NewEntitySpec("character", "Mirel Ansa", "proper_name", known=True),
            turn_id=None,
            source="world_gen",
        )
        await service.update_entity(
            conn, stranger, "character", {"true_name": "Mirel Okonkwo"}
        )
        aliases = {
            k: (v[0], v[2]) for k, v in (await _aliases(conn, game, stranger)).items()
        }
        by_old_name = await service.resolve_ref(conn, "Mirel Ansa", "character")
    assert aliases["Mirel Ansa"] == ("former_name", True)
    assert aliases["Mirel Okonkwo"] == ("true_name", True)
    # The new name gets its derived forms.
    assert aliases["Okonkwo"] == ("short", True)
    assert by_old_name.entity_id == stranger


async def test_require_ref_raises_and_is_counted_by_write_item(
    test_pool, game, service
):
    from kg.item_writes import write_items

    async with test_pool.acquire() as conn:
        quay = await service.create_entity(
            conn,
            NewEntitySpec("location", "Quai 9", "proper_name"),
            turn_id=None,
            source="extractor",
        )
        with pytest.raises(RefUnresolved) as unresolved:
            await service.require_ref(conn, "Le Bureau Fantôme", "location")
        assert "Fantôme" not in str(unresolved.value)

        async def write(item):
            ref, entity_id = item
            if ref is not None:
                await service.require_ref(conn, ref, "location")
            await service.update_entity(conn, entity_id, "location", {"sector": "Est"})
            return True

        missing = UUID("00000000-0000-4000-8000-000000000000")
        stats = {"errors": []}
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            await write_items(
                conn,
                stats,
                "event",
                [("Le Bureau Fantôme", quay), (None, missing), ("Quai 9", quay)],
                write,
                counter="written",
            )
        events = await conn.fetch(
            "SELECT kind, turn_id, payload FROM identity_events"
            " WHERE game_id = $1 AND kind IN ('ref_dropped', 'write_miss') ORDER BY id",
            game,
        )
        sector = await conn.fetchval("SELECT sector FROM locations WHERE id = $1", quay)
    assert stats == {
        "errors": [
            {"code": "ref_dropped", "item": "event"},
            {"code": "write_miss", "item": "event"},
        ],
        "written": 1,
    }
    assert [(e["kind"], e["turn_id"], e["payload"]) for e in events] == [
        (
            "ref_dropped",
            turn_id,
            {"item": "event", "entity_type": "location", "candidates": 0},
        ),
        (
            "write_miss",
            turn_id,
            {"item": "event", "table": "locations", "entity_id": str(missing)},
        ),
    ]
    assert sector == "Est"
