"""Reveals and merges (#153, spec §4.7): the table of reveals row by row, the guarded
merge that keeps every edge on the older entity, and the cases of #25 (orphans)."""

from uuid import UUID

import pytest

from config import get_identity_config
from repos import entities
from services.identity.service import IdentityService
from services.identity.types import EntityRef, FactRef, NewEntitySpec

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


async def _character(conn, game_id: UUID, **fields) -> UUID:
    cols = ", ".join(["game_id", *fields])
    marks = ", ".join(f"${i}" for i in range(1, len(fields) + 2))
    return await conn.fetchval(
        f"INSERT INTO characters ({cols}) VALUES ({marks}) RETURNING id",
        game_id,
        *fields.values(),
    )


async def _relation(conn, game_id, source, target, kind) -> UUID:
    return await conn.fetchval(
        """INSERT INTO relations (game_id, type, source_id, target_id, start_cycle)
           VALUES ($1, $2::relation_type, $3, $4, 1) RETURNING id""",
        game_id,
        kind,
        source,
        target,
    )


async def _fact(conn, game_id, *participants) -> UUID:
    return await conn.fetchval(
        "SELECT create_fact($1, 1, 'action', 'Un fait', p_participants => $2::jsonb)",
        game_id,
        [{"entity_id": str(p), "role": "actor"} for p in participants],
    )


async def _aliases(conn, game_id, entity_id) -> dict[str, tuple]:
    return {
        a.alias: (a.kind, a.known)
        for a in await entities.list_aliases(conn, game_id, entity_id)
    }


async def _events(conn, game_id, kind) -> list:
    return await conn.fetch(
        "SELECT entity_id, payload FROM identity_events"
        " WHERE game_id = $1 AND kind = $2 ORDER BY id",
        game_id,
        kind,
    )


async def _character_row(conn, entity_id) -> dict:
    row = await conn.fetchrow(
        """SELECT c.true_name, c.descriptor, c.known_by_protagonist AS known, c.name,
                  er.name AS label, display_for_player(c.id) AS shown
           FROM characters AS c JOIN entity_registry AS er ON er.id = c.id
           WHERE c.id = $1""",
        entity_id,
    )
    return dict(row)


def _ref(text: str) -> EntityRef:
    return EntityRef(text, "character")


async def test_reveal_by_descriptor_with_article_sets_the_true_name(
    test_pool, game, service
):
    """The Kethari case: a character known by its descriptor is named by it, with its
    article; the revealed name becomes its true name, known, with its short form."""
    async with test_pool.acquire() as conn:
        elder = await service.create_entity(
            conn,
            NewEntitySpec("character", "La Kethari âgée", "descriptor"),
            turn_id=None,
            source="extractor",
        )
        outcome = await service.reveal(
            conn,
            _ref("La Kethari âgée"),
            "Nahle Irun-Sa",
            turn_id=None,
            source="reveal",
        )
        row = await _character_row(conn, elder)
        aliases = await _aliases(conn, game, elder)
        applied = await _events(conn, game, "reveal_applied")
    assert (outcome.kind, outcome.entity_id, outcome.merged_into) == (
        "applied",
        elder,
        None,
    )
    assert row == {
        "true_name": "Nahle Irun-Sa",
        "descriptor": "La Kethari âgée",
        "known": True,
        "name": "Nahle Irun-Sa",
        "label": "Nahle Irun-Sa",
        "shown": "Nahle Irun-Sa",
    }
    assert aliases["Nahle Irun-Sa"] == ("true_name", True)
    assert aliases["Nahle"] == ("short", True)
    assert aliases["La Kethari âgée"] == ("descriptor", True)
    assert [e["entity_id"] for e in applied] == [elder]


async def test_reveal_of_a_hidden_name_with_the_same_spelling_marks_known(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        voss = await _character(
            conn, game, true_name="Elara Voss", descriptor="La doctoresse"
        )
        before = await _character_row(conn, voss)
        outcome = await service.reveal(
            conn, _ref("la doctoresse"), "elara voss", turn_id=None, source="reveal"
        )
        row = await _character_row(conn, voss)
        aliases = await _aliases(conn, game, voss)
    assert (before["known"], before["shown"]) == (False, "La doctoresse")
    assert outcome.kind == "known_only"
    assert (row["true_name"], row["known"], row["shown"]) == (
        "Elara Voss",
        True,
        "Elara Voss",
    )
    assert aliases == {
        "Elara Voss": ("true_name", True),
        "La doctoresse": ("descriptor", True),
    }


async def test_reveal_with_a_different_spelling_keeps_the_world_gen_spelling_as_canonical(
    test_pool, game, service
):
    """Similar names (similarity >= IdentityConfig.reveal_match, norms different): the
    world-gen spelling stays the true name, the narration's becomes a known alias."""
    async with test_pool.acquire() as conn:
        nahle = await _character(
            conn, game, true_name="Nahle Irun-Sa", descriptor="La Kethari âgée"
        )
        similarity = await entities.name_similarity(
            conn, game, "Nahle Irun-Sa", "Nahle Irun Sa"
        )
        outcome = await service.reveal(
            conn,
            _ref("La Kethari âgée"),
            "Nahle Irun Sa",
            turn_id=None,
            source="reveal",
        )
        row = await _character_row(conn, nahle)
        aliases = await _aliases(conn, game, nahle)
    assert similarity >= service.config.reveal_match
    assert outcome.kind == "known_only"
    assert (row["true_name"], row["known"]) == ("Nahle Irun-Sa", True)
    assert aliases["Nahle Irun-Sa"] == ("true_name", True)
    assert aliases["Nahle Irun Sa"] == ("true_name", True)


async def test_conflicting_reveal_believes_the_narration_and_keeps_the_old_name_as_former(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        docker = await _character(
            conn, game, true_name="Arno Vey", descriptor="Le docker"
        )
        outcome = await service.reveal(
            conn, _ref("le docker"), "Brune Okafor", turn_id=None, source="reveal"
        )
        row = await _character_row(conn, docker)
        aliases = await _aliases(conn, game, docker)
        conflicts = await _events(conn, game, "reveal_conflict")
        by_old_name = await entities.find_entity(conn, game, "Arno Vey", "character")
    assert outcome.kind == "conflict"
    assert (row["true_name"], row["known"], row["label"]) == (
        "Brune Okafor",
        True,
        "Brune Okafor",
    )
    assert aliases["Arno Vey"] == ("former_name", False)
    assert aliases["Brune Okafor"] == ("true_name", True)
    assert aliases["Le docker"] == ("descriptor", True)
    assert [e["entity_id"] for e in conflicts] == [docker]
    assert by_old_name == docker


async def test_reveal_without_real_name_is_a_counted_noop(test_pool, game, service):
    """Nothing to reveal (no real name, no true name), an unknown reference, or a
    reference two homonyms share: no write, a counted reveal_noop, never a guess."""
    async with test_pool.acquire() as conn:
        clerk = await _character(conn, game, descriptor="Le guichetier")
        guards = [
            await service.create_entity(
                conn,
                NewEntitySpec("character", "Garde du sas", "descriptor"),
                turn_id=None,
                source="extractor",
                trap=True,
            )
            for _ in range(2)
        ]
        no_name = await service.reveal(
            conn, _ref("le guichetier"), None, turn_id=None, source="reveal"
        )
        unknown = await service.reveal(
            conn, _ref("Personne Ici"), "Tom", turn_id=None, source="reveal"
        )
        ambiguous = await service.reveal(
            conn, _ref("Garde du sas"), "Tom", turn_id=None, source="reveal"
        )
        rows = [await _character_row(conn, c) for c in (clerk, *guards)]
        noops = await _events(conn, game, "reveal_noop")
    assert (no_name.kind, no_name.entity_id) == ("noop", clerk)
    assert (unknown.kind, unknown.entity_id) == ("noop", None)
    assert (ambiguous.kind, ambiguous.entity_id) == ("noop", None)
    assert all(r["true_name"] is None and not r["known"] for r in rows)
    assert [(e["entity_id"], e["payload"]["reason"]) for e in noops] == [
        (clerk, "no_name"),
        (None, "unresolved"),
        (None, "unresolved"),
    ]


async def test_reveal_to_an_existing_name_merges_and_keeps_every_edge(
    test_pool, game, service
):
    """#25 case 1: the revealed name is another character's; the two records are one
    character, merged into the older with every relation and fact of both, no orphan,
    an audit row and a tombstone."""
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        nahle = await _character(
            conn, game, true_name="Nahle Irun-Sa", known_by_protagonist=True
        )
        tesk = await _character(conn, game, true_name="Tesk Vahrun")
        relations = [
            await _relation(conn, game, elder, tesk, "knows"),
            await _relation(conn, game, nahle, tesk, "friend_of"),
            await _relation(conn, game, tesk, nahle, "enemy_of"),
        ]
        facts = [await _fact(conn, game, elder), await _fact(conn, game, nahle, tesk)]
        outcome = await service.reveal(
            conn,
            _ref("La Kethari âgée"),
            "Nahle Irun-Sa",
            turn_id=None,
            source="reveal",
        )
        ends = await conn.fetch(
            "SELECT id, source_id, target_id, end_cycle FROM relations"
            " WHERE id = ANY($1::uuid[]) ORDER BY source_id = $2, type",
            relations,
            tesk,
        )
        participants = await conn.fetch(
            "SELECT fact_id, entity_id FROM fact_participants"
            " WHERE fact_id = ANY($1::uuid[])",
            facts,
        )
        orphans = await conn.fetchval(
            """SELECT count(*) FROM (
                   SELECT source_id AS id FROM relations WHERE game_id = $1
                   UNION ALL SELECT target_id FROM relations WHERE game_id = $1
                   UNION ALL SELECT fp.entity_id FROM fact_participants AS fp
                     JOIN facts AS ft ON ft.id = fp.fact_id WHERE ft.game_id = $1) AS e
               LEFT JOIN entity_registry AS er ON er.id = e.id
               WHERE er.id IS NULL OR er.merged_into IS NOT NULL""",
            game,
        )
        merges = await conn.fetch(
            "SELECT kept_id, dropped_id, reason FROM entity_merges WHERE game_id = $1",
            game,
        )
        tombstone = await conn.fetchval(
            "SELECT merged_into FROM entity_registry WHERE id = $1", nahle
        )
        dropped_row = await conn.fetchval(
            "SELECT count(*) FROM characters WHERE id = $1", nahle
        )
        row = await _character_row(conn, elder)
        by_name = await entities.find_entity(conn, game, "Nahle Irun-Sa", "character")
    assert (outcome.kind, outcome.entity_id, outcome.merged_into) == (
        "merged",
        elder,
        elder,
    )
    assert sorted((r["source_id"], r["target_id"]) for r in ends) == sorted(
        [(elder, tesk), (elder, tesk), (tesk, elder)]
    )
    # Three relations of three types: moved, none a duplicate to close.
    assert [r["end_cycle"] for r in ends] == [None, None, None]
    assert {r["entity_id"] for r in participants} == {elder, tesk}
    assert orphans == 0
    assert [tuple(m) for m in merges] == [(elder, nahle, "reveal")]
    assert (tombstone, dropped_row) == (elder, 0)
    assert (row["true_name"], row["descriptor"], row["known"]) == (
        "Nahle Irun-Sa",
        "La Kethari âgée",
        True,
    )
    assert by_name == elder


async def test_merge_is_refused_for_two_mandatory_npcs_and_for_the_companion(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        first = await _character(conn, game, true_name="Ilsa Morn", is_mandatory=True)
        second = await _character(
            conn, game, descriptor="La capitaine", is_mandatory=True
        )
        companion = await conn.fetchval(
            "INSERT INTO companions (game_id, name) VALUES ($1, 'Célimène') RETURNING id",
            game,
        )
        # One companion per game: it is merged with a character of its name.
        twin = await _character(conn, game, true_name="Célimène")
        mandatory = await service.merge(
            conn, first, second, reason="test", turn_id=None
        )
        reserved = await service.merge(
            conn, companion, twin, reason="test", turn_id=None
        )
        revealed = await service.reveal(
            conn, _ref("la capitaine"), "Ilsa Morn", turn_id=None, source="reveal"
        )
        refused = await _events(conn, game, "merge_refused")
        live = await conn.fetchval(
            "SELECT count(*) FROM entity_registry WHERE id = ANY($1::uuid[])"
            " AND merged_into IS NULL",
            [first, second, companion, twin],
        )
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
        aliases = await _aliases(conn, game, second)
        second_row = await _character_row(conn, second)
    assert (mandatory.merge_id, mandatory.refused) == (None, "both_mandatory")
    assert (reserved.merge_id, reserved.refused) == (None, "reserved_type")
    assert (revealed.kind, revealed.entity_id) == ("merge_refused", second)
    assert [e["payload"]["refused"] for e in refused] == [
        "both_mandatory",
        "reserved_type",
        "both_mandatory",
    ]
    assert (live, merges) == (4, 0)
    # The name is learned, as an alias; the character keeps its own records.
    assert aliases["Ilsa Morn"] == ("nickname", True)
    assert second_row["true_name"] is None


async def test_merge_keeps_the_oldest_entity(test_pool, game, service):
    """The record created first carries the planned arcs: a newer descriptor record
    revealed as its name is merged into it, not the reverse."""
    async with test_pool.acquire() as conn:
        older = await _character(conn, game, true_name="Nahle Irun-Sa")
        newer = await _character(conn, game, descriptor="La Kethari âgée")
        arc = await conn.fetchval(
            """INSERT INTO narrative_arcs (game_id, title, owner_id, created_cycle)
               VALUES ($1, 'Arc', $2, 1) RETURNING id""",
            game,
            older,
        )
        outcome = await service.reveal(
            conn,
            _ref("La Kethari âgée"),
            "Nahle Irun-Sa",
            turn_id=None,
            source="reveal",
        )
        tombstone = await conn.fetchval(
            "SELECT merged_into FROM entity_registry WHERE id = $1", newer
        )
        owner = await conn.fetchval(
            "SELECT owner_id FROM narrative_arcs WHERE id = $1", arc
        )
        row = await _character_row(conn, older)
        by_descriptor = await entities.find_entity(
            conn, game, "la kethari âgée", "character"
        )
    assert (outcome.kind, outcome.entity_id, outcome.merged_into) == (
        "merged",
        newer,
        older,
    )
    assert (tombstone, owner, by_descriptor) == (older, older, older)
    assert (row["true_name"], row["descriptor"], row["known"]) == (
        "Nahle Irun-Sa",
        "La Kethari âgée",
        True,
    )


async def test_deleting_a_character_deletes_its_registry_row(test_pool, game):
    """#25 case 2: no orphan registry row (nor alias) outlives its character."""
    async with test_pool.acquire() as conn:
        orin = await _character(conn, game, true_name="Orin Kell")
        await conn.execute("DELETE FROM characters WHERE id = $1", orin)
        registry = await conn.fetchval(
            "SELECT count(*) FROM entity_registry WHERE id = $1", orin
        )
        aliases = await conn.fetchval(
            "SELECT count(*) FROM entity_aliases WHERE entity_id = $1", orin
        )
    assert (registry, aliases) == (0, 0)


async def test_a_new_npc_named_like_a_deleted_one_starts_with_no_relations(
    test_pool, game, service
):
    """#25 case 3: the relations of a deleted character go with it; a newcomer under its
    name is a new entity without them."""
    async with test_pool.acquire() as conn:
        orin = await _character(conn, game, true_name="Orin Kell")
        tesk = await _character(conn, game, true_name="Tesk Vahrun")
        await _relation(conn, game, orin, tesk, "knows")
        await _relation(conn, game, tesk, orin, "friend_of")
        await conn.execute("DELETE FROM characters WHERE id = $1", orin)
        newcomer = await service.create_entity(
            conn,
            NewEntitySpec("character", "Orin Kell", "proper_name"),
            turn_id=None,
            source="extractor",
        )
        relations = await conn.fetchval(
            "SELECT count(*) FROM relations WHERE $1 IN (source_id, target_id)"
            " OR $2 IN (source_id, target_id)",
            newcomer,
            orin,
        )
    assert newcomer != orin
    assert relations == 0


async def test_recreating_a_known_npc_keeps_it_known(test_pool, game, service):
    """#25 case 4: creating a character under the label of a known one returns it, still
    known (an extraction that does not know it is known never hides it again)."""
    async with test_pool.acquire() as conn:
        orin = await service.create_entity(
            conn,
            NewEntitySpec("character", "Orin Kell", "proper_name", known=True),
            turn_id=None,
            source="world_gen",
        )
        again = await service.create_entity(
            conn,
            NewEntitySpec("character", "Orin Kell", "proper_name", known=False),
            turn_id=None,
            source="extractor",
        )
        row = await _character_row(conn, orin)
        count = await conn.fetchval(
            "SELECT count(*) FROM characters WHERE game_id = $1", game
        )
    assert again == orin
    assert (row["known"], row["shown"], count) == (True, "Orin Kell", 1)


async def test_reveal_is_idempotent(test_pool, game, service):
    """Applied twice (the commit, then the extraction's re-apply): the second finds
    nothing to do and records no event, a merge included."""

    async def reveal_both(conn):
        return [
            await service.reveal(
                conn,
                _ref("La Kethari âgée"),
                "Nahle Irun-Sa",
                turn_id=None,
                source="reveal",
            ),
            await service.reveal(
                conn, _ref("le guichetier"), "Orin Kell", turn_id=None, source="reveal"
            ),
        ]

    async def state(conn):
        events = await conn.fetchval(
            "SELECT count(*) FROM identity_events WHERE game_id = $1", game
        )
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
        rows = [await _character_row(conn, c) for c in (elder, clerk)]
        aliases = [await _aliases(conn, game, c) for c in (elder, clerk)]
        return events, merges, rows, aliases

    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        clerk = await _character(conn, game, descriptor="Le guichetier")
        await _character(conn, game, true_name="Orin Kell")
        first = await reveal_both(conn)
        after_first = await state(conn)
        second = await reveal_both(conn)
        after_second = await state(conn)
    assert [o.kind for o in first] == ["applied", "merged"]
    assert [(o.kind, o.entity_id) for o in second] == [
        ("known_only", elder),
        ("known_only", clerk),
    ]
    assert after_second == after_first
    assert after_first[1] == 1


async def test_reveal_of_a_fact_marks_it_known(test_pool, game, service):
    async with test_pool.acquire() as conn:
        tesk = await _character(conn, game, true_name="Tesk Vahrun")
        fact = await _fact(conn, game, tesk)
        await conn.execute("UPDATE facts SET known = false WHERE id = $1", fact)
        handle = await conn.fetchval("SELECT handle FROM facts WHERE id = $1", fact)
        first = await service.reveal(
            conn, FactRef(f"F{handle}"), None, turn_id=None, source="reveal"
        )
        second = await service.reveal(
            conn, FactRef(str(fact)), None, turn_id=None, source="reveal"
        )
        unknown = await service.reveal(
            conn, FactRef("F999999"), None, turn_id=None, source="reveal"
        )
        known = await conn.fetchval("SELECT known FROM facts WHERE id = $1", fact)
    assert [(o.kind, o.entity_id) for o in (first, second, unknown)] == [
        ("applied", fact),
        ("known_only", fact),
        ("noop", None),
    ]
    assert known is True
