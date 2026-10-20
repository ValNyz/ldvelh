"""Reveals and merges (#153, spec §4.7): the table of reveals row by row, the guarded
merge that keeps every edge on the older entity, and the cases of #25 (orphans)."""

import hashlib
from uuid import UUID, uuid4

import pytest

from config import get_identity_config
from repos import entities, turns
from repos.uow import uow
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


async def _game_state(conn, game_id) -> dict[str, list[str]]:
    """The game's rows in the tables a reveal or a merge writes, as sorted JSON text."""
    out = {}
    for table in ("characters", "entity_registry", "entity_aliases", "entity_merges"):
        rows = await conn.fetch(
            f"SELECT to_jsonb(t)::text AS j FROM {table} AS t WHERE t.game_id = $1",
            game_id,
        )
        out[table] = sorted(r["j"] for r in rows)
    return out


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
            conn, game, "Nahle Irun-Sa", "Nahle Irun-Sah"
        )
        norms = await conn.fetchrow(
            "SELECT ldvelh_norm_for_game($1, 'Nahle Irun-Sa') AS world,"
            " ldvelh_norm_for_game($1, 'Nahle Irun-Sah') AS told",
            game,
        )
        outcome = await service.reveal(
            conn,
            _ref("La Kethari âgée"),
            "Nahle Irun-Sah",
            turn_id=None,
            source="reveal",
        )
        row = await _character_row(conn, nahle)
        aliases = await _aliases(conn, game, nahle)
    # The similarity row, not the same-spelling one: the norms differ.
    assert norms["world"] != norms["told"]
    assert service.config.reveal_match <= similarity < 1
    assert outcome.kind == "known_only"
    assert (row["true_name"], row["known"]) == ("Nahle Irun-Sa", True)
    assert aliases["Nahle Irun-Sa"] == ("true_name", True)
    assert aliases["Nahle Irun-Sah"] == ("true_name", True)


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
        by_name = await entities.find_entity(conn, game, "Ilsa Morn", "character")
    assert (mandatory.merge_id, mandatory.refused) == (None, "both_mandatory")
    assert (reserved.merge_id, reserved.refused) == (None, "reserved_type")
    assert (revealed.kind, revealed.entity_id) == ("merge_refused", second)
    assert [e["payload"]["refused"] for e in refused] == [
        "both_mandatory",
        "reserved_type",
        "both_mandatory",
    ]
    assert (live, merges) == (4, 0)
    # No alias of the refused name: its holder still resolves by it (the refusal event
    # names the holder).
    assert "Ilsa Morn" not in aliases
    assert by_name == first
    assert refused[-1]["payload"]["holder_ids"] == [str(first)]
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


async def test_a_revealed_descriptor_of_an_unnamed_character_never_merges(
    test_pool, game, service
):
    """R18, R19b: a name equal to another unnamed character's descriptor (its registry
    label) designates nobody: no merge, the revealed character takes it as its true name,
    known, and its registry label an internal suffix (R14, event label_suffixed) so the
    registry stays unique; the other character is untouched; the undo restores both."""
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        apron = await _character(conn, game, descriptor="Le Kethari au tablier")
        apron_before = await _character_row(conn, apron)
        turn_id = await turns.open_turn(conn, game)
        before = await _game_state(conn, game)
        async with uow(conn, turn_id):
            outcome = await service.reveal(
                conn,
                _ref("la Kethari âgée"),
                "Le Kethari au tablier",
                turn_id=turn_id,
                source="reveal",
            )
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
        elder_row = await _character_row(conn, elder)
        suffix = await conn.fetchval(
            "SELECT label_suffix FROM characters WHERE id = $1", elder
        )
        bare = await conn.fetchval("SELECT identity_bare_label($1)", elder)
        apron_after = await _character_row(conn, apron)
        suffixed = await _events(conn, game, "label_suffixed")
        elder_aliases = await _aliases(conn, game, elder)
        by_bare_name = await entities.find_entity(
            conn, game, "Le Kethari au tablier", "character"
        )
        apron_handle = await entities.handle_of(conn, apron)
        by_handle = await entities.find_entity(
            conn, game, f"E{apron_handle}", "character"
        )
        await conn.fetchval("SELECT world_changes_undo($1::uuid[])", [turn_id])
        after = await _game_state(conn, game)
    assert (outcome.kind, outcome.entity_id, merges) == ("applied", elder, 0)
    assert suffix
    assert (elder_row["true_name"], elder_row["known"], elder_row["shown"]) == (
        "Le Kethari au tablier",
        True,
        "Le Kethari au tablier",
    )
    assert elder_row["label"] == f"Le Kethari au tablier ({suffix})"
    assert bare == "Le Kethari au tablier"
    assert apron_after == apron_before
    assert [e["entity_id"] for e in suffixed] == [elder]
    # The suffixed label is an internal alias (never known), no stray former name.
    assert elder_aliases == {
        "La Kethari âgée": ("descriptor", True),
        "Le Kethari au tablier": ("true_name", True),
        f"Le Kethari au tablier ({suffix})": ("label", False),
        "tablier": ("short", True),
    }
    # Two homonyms now share the bare name: it is ambiguous, nothing is guessed; the
    # unnamed holder stays reachable by its handle.
    assert by_bare_name is None
    assert by_handle == apron
    assert after == before


async def test_a_revealed_short_form_of_another_name_never_merges(
    test_pool, game, service
):
    """R18: another character's short form (« Nahle » of « Nahle Irun-Sa ») designates
    nobody: the revealed character is named by it, the other one is untouched."""
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        nahle = await service.create_entity(
            conn,
            NewEntitySpec("character", "Nahle Irun-Sa", "proper_name", known=False),
            turn_id=None,
            source="world_gen",
        )
        outcome = await service.reveal(
            conn, _ref("la Kethari âgée"), "Nahle", turn_id=None, source="reveal"
        )
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
        rows = [await _character_row(conn, c) for c in (elder, nahle)]
    assert (outcome.kind, merges) == ("applied", 0)
    assert rows[0]["true_name"] == "Nahle"
    assert (rows[1]["true_name"], rows[1]["known"]) == ("Nahle Irun-Sa", False)


async def test_a_merge_survivor_with_another_hidden_name_believes_the_narration(
    test_pool, game, service
):
    """R17: the older record survives the merge; its different hidden true name gives way
    to the narration's (§4.7 '≠' row), the old one a former name the PC never knew."""
    async with test_pool.acquire() as conn:
        older = await _character(
            conn, game, true_name="Arno Vey", descriptor="Le docker"
        )
        await _character(conn, game, true_name="Brune Okafor")
        turn_id = await turns.open_turn(conn, game)
        before = await _game_state(conn, game)
        async with uow(conn, turn_id):
            outcome = await service.reveal(
                conn,
                _ref("le docker"),
                "Brune Okafor",
                turn_id=turn_id,
                source="reveal",
            )
        row = await _character_row(conn, older)
        aliases = await _aliases(conn, game, older)
        events = await conn.fetch(
            "SELECT kind, entity_id FROM identity_events WHERE game_id = $1"
            " AND kind IN ('merge', 'reveal_conflict') ORDER BY id",
            game,
        )
        await conn.fetchval("SELECT world_changes_undo($1::uuid[])", [turn_id])
        after = await _game_state(conn, game)
    assert (outcome.kind, outcome.entity_id, outcome.merged_into) == (
        "merged",
        older,
        older,
    )
    assert (row["true_name"], row["known"]) == ("Brune Okafor", True)
    assert aliases["Arno Vey"] == ("former_name", False)
    assert aliases["Brune Okafor"] == ("true_name", True)
    assert [tuple(e) for e in events] == [
        ("merge", older),
        ("reveal_conflict", older),
    ]
    assert after == before


async def test_a_name_two_characters_hold_is_an_ambiguous_refusal(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        elder = await _character(conn, game, descriptor="La Kethari âgée")
        ilsa = await _character(conn, game, true_name="Ilsa Morn")
        other = await _character(conn, game, true_name="Ilsa Morn-Vey")
        await service.add_alias(
            conn, other, "Ilsa Morn", "true_name", known=False, source="world_gen"
        )
        outcome = await service.reveal(
            conn, _ref("la Kethari âgée"), "Ilsa Morn", turn_id=None, source="reveal"
        )
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
        refused = await _events(conn, game, "merge_refused")
        elder_aliases = await _aliases(conn, game, elder)
    assert (outcome.kind, outcome.entity_id, merges) == ("merge_refused", elder, 0)
    assert [e["payload"]["refused"] for e in refused] == ["ambiguous"]
    assert sorted(refused[0]["payload"]["holder_ids"]) == sorted(
        [str(ilsa), str(other)]
    )
    assert "Ilsa Morn" not in elder_aliases


async def test_an_object_is_never_merged_by_a_reveal(test_pool, game, service):
    async with test_pool.acquire() as conn:
        cup, mug = [
            await service.create_entity(
                conn,
                NewEntitySpec("object", label, "proper_name"),
                turn_id=None,
                source="extractor",
            )
            for label in ("Gobelet fêlé", "Tasse de cuivre")
        ]
        outcome = await service.reveal(
            conn,
            EntityRef("Tasse de cuivre", "object"),
            "Gobelet fêlé",
            turn_id=None,
            source="reveal",
        )
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
        refused = await _events(conn, game, "merge_refused")
    assert (outcome.kind, outcome.entity_id, merges) == ("merge_refused", mug, 0)
    assert [e["payload"]["refused"] for e in refused] == ["never_auto_merged"]
    assert cup != mug


async def test_a_location_reveal_follows_the_same_table(test_pool, game, service):
    """A location's "true name" is its name, its knowledge the flags of its aliases:
    the same name marks them known, another name renames it (former name kept)."""
    async with test_pool.acquire() as conn:
        bar = await service.create_entity(
            conn,
            NewEntitySpec("location", "Le Bar des Docks", "proper_name", known=False),
            turn_id=None,
            source="world_gen",
        )
        handle = await entities.handle_of(conn, bar)
        ref = EntityRef(f"E{handle}", "location")
        hidden = await _aliases(conn, game, bar)
        same = await service.reveal(
            conn, ref, "bar des docks", turn_id=None, source="reveal"
        )
        known = await _aliases(conn, game, bar)
        other = await service.reveal(
            conn, ref, "Le Comptoir de Mia", turn_id=None, source="reveal"
        )
        renamed = await _aliases(conn, game, bar)
        name = await conn.fetchval("SELECT name FROM locations WHERE id = $1", bar)
    assert hidden["Le Bar des Docks"] == ("label", False)
    assert (same.kind, same.entity_id) == ("known_only", bar)
    assert known["Le Bar des Docks"] == ("label", True)
    assert (other.kind, name) == ("conflict", "Le Comptoir de Mia")
    assert renamed["Le Bar des Docks"] == ("former_name", True)
    assert renamed["Le Comptoir de Mia"] == ("label", True)


@pytest.mark.parametrize(
    "case", ["same_entity", "missing", "type_mismatch", "already_merged"]
)
async def test_merge_guards_refuse_with_their_code(test_pool, game, service, case):
    async with test_pool.acquire() as conn:
        first = await _character(conn, game, true_name="Orin Kell")
        second = await _character(conn, game, true_name="Tesk Vahrun")
        keep, drop = first, second
        if case == "same_entity":
            drop = first
        elif case == "missing":
            drop = uuid4()
        elif case == "type_mismatch":
            drop = await conn.fetchval(
                "INSERT INTO locations (game_id, name) VALUES ($1, 'Quai 9') RETURNING id",
                game,
            )
        else:
            third = await _character(conn, game, true_name="Ilsa Morn")
            assert (
                await service.merge(conn, first, third, reason="t", turn_id=None)
            ).merge_id
            keep, drop = second, third
        outcome = await service.merge(conn, keep, drop, reason="test", turn_id=None)
        merges = await conn.fetchval(
            "SELECT count(*) FROM entity_merges WHERE game_id = $1", game
        )
        refused = await _events(conn, game, "merge_refused")
    assert (outcome.merge_id, outcome.refused) == (None, case)
    assert merges == (1 if case == "already_merged" else 0)
    assert [e["payload"]["refused"] for e in refused] == [case]


async def test_dedup_keeps_two_different_reveals_and_drops_the_same_one_twice(
    test_pool, game, service
):
    """In one turn (the commit then the extraction's re-apply): the same no-op twice is
    one event, even under another spelling of the same reference; two different
    unresolved reveals are two (keyed on a hash of the normalised reference)."""
    async with test_pool.acquire() as conn:
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            for ref in ("Personne", "Quelqu'un d'autre", "la personne"):
                await service.reveal(
                    conn, _ref(ref), "Tom", turn_id=turn_id, source="reveal"
                )
        noops = await _events(conn, game, "reveal_noop")
    assert [e["payload"]["ref_key"] for e in noops] == [
        hashlib.sha256(service.normalizer.norm(ref).encode()).hexdigest()
        for ref in ("Personne", "Quelqu'un d'autre")
    ]


async def test_dedup_keeps_a_refusal_against_other_holders(test_pool, game, service):
    """The dedup compares payloads by equality: a refusal against fewer holders in the
    same turn is another event, not absorbed by the first one."""
    async with test_pool.acquire() as conn:
        await _character(conn, game, descriptor="La Kethari âgée")
        holders = [
            await _character(conn, game, true_name=name)
            for name in ("Ilsa Morn", "Ilsa Morn-Vey", "Ilsa Morn-Sel")
        ]
        for holder in holders[1:]:
            await service.add_alias(
                conn, holder, "Ilsa Morn", "true_name", known=False, source="world_gen"
            )
        turn_id = await turns.open_turn(conn, game)
        async with uow(conn, turn_id):
            await service.reveal(
                conn,
                _ref("la Kethari âgée"),
                "Ilsa Morn",
                turn_id=turn_id,
                source="reveal",
            )
        await conn.execute(
            "DELETE FROM entity_aliases WHERE entity_id = $1 AND alias = 'Ilsa Morn'",
            holders[2],
        )
        async with uow(conn, turn_id):
            await service.reveal(
                conn,
                _ref("la Kethari âgée"),
                "Ilsa Morn",
                turn_id=turn_id,
                source="reveal",
            )
        refused = await _events(conn, game, "merge_refused")
    assert [len(e["payload"]["holder_ids"]) for e in refused] == [3, 2]


async def test_renaming_a_suffixed_character_onto_a_free_name_leaves_no_intermediate_label(
    test_pool, game, service
):
    """A suffixed homonym renamed onto a free name drops its suffix in the same write: no
    alias of a label it never had (« <new name> (2) »); the old suffixed label becomes a
    former name, as any replaced label."""
    async with test_pool.acquire() as conn:
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
        handle = await entities.handle_of(conn, guards[1])
        outcome = await service.reveal(
            conn,
            _ref(f"E{handle}"),
            "Brune Okafor",
            turn_id=None,
            source="reveal",
        )
        row = await _character_row(conn, guards[1])
        suffix = await conn.fetchval(
            "SELECT label_suffix FROM characters WHERE id = $1", guards[1]
        )
        aliases = await _aliases(conn, game, guards[1])
    assert (outcome.kind, suffix, row["label"]) == ("applied", None, "Brune Okafor")
    assert not [a for a in aliases if a.startswith("Brune Okafor (")]
    assert aliases["Garde du sas (2)"][0] == "former_name"
    assert aliases["Brune Okafor"] == ("true_name", True)


async def test_a_second_pass_in_the_same_turn_records_no_new_event(
    test_pool, game, service
):
    """The production path: every row of the table applied twice under one turn; the
    second pass changes nothing and records no event (noop, conflict, refusal)."""
    async with test_pool.acquire() as conn:
        await _character(conn, game, descriptor="Le guichetier")
        await _character(conn, game, true_name="Arno Vey", descriptor="Le docker")
        await _character(conn, game, true_name="Ilsa Morn", is_mandatory=True)
        await _character(conn, game, descriptor="La capitaine", is_mandatory=True)
        reveals = [
            ("le guichetier", None),
            ("Personne Ici", "Tom"),
            ("le docker", "Brune Okafor"),
            ("la capitaine", "Ilsa Morn"),
        ]
        turn_id = await turns.open_turn(conn, game)

        async def one_pass():
            async with uow(conn, turn_id):
                return [
                    (
                        await service.reveal(
                            conn, _ref(r), real, turn_id=turn_id, source="reveal"
                        )
                    ).kind
                    for r, real in reveals
                ]

        async def count():
            return await conn.fetchval(
                "SELECT count(*) FROM identity_events WHERE game_id = $1", game
            )

        first = await one_pass()
        events = await count()
        second = await one_pass()
        again = await count()
    assert first == ["noop", "noop", "conflict", "merge_refused"]
    assert second == ["noop", "noop", "known_only", "merge_refused"]
    assert again == events


async def test_revealing_a_homonym_by_its_own_descriptor_keeps_its_suffix(
    test_pool, game, service
):
    """A rename whose bare label does not change is a no-op on the label: an unnamed
    homonym revealed with its own descriptor keeps its suffix, gets no « … (3) », no
    former name of its suffixed label and no second label_suffixed event."""
    async with test_pool.acquire() as conn:
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
        handle = await entities.handle_of(conn, guards[1])
        before = await _character_row(conn, guards[1])
        outcome = await service.reveal(
            conn, _ref(f"E{handle}"), "Garde du sas", turn_id=None, source="reveal"
        )
        row = await _character_row(conn, guards[1])
        suffix = await conn.fetchval(
            "SELECT label_suffix FROM characters WHERE id = $1", guards[1]
        )
        aliases = await _aliases(conn, game, guards[1])
        suffixed = await _events(conn, game, "label_suffixed")
    assert outcome.kind == "applied"
    assert (suffix, row["label"]) == ("2", before["label"])
    assert (row["true_name"], row["known"]) == ("Garde du sas", True)
    assert {a: k for a, k in aliases.items() if "(" in a} == {
        "Garde du sas (2)": ("label", False)
    }
    assert [e["entity_id"] for e in suffixed] == [guards[1]]
