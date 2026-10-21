"""The resolver v2 after the commit (#154, spec §4.5.6, §4.6, §4.9): the turn's mentions
are stored by entity id and served as such, new entities are created by the identity
service (never by an extractor), extractors run for the types the turn really created or
left bare and see the scene by handle, and a resolver outage keeps the coreference."""

import json
from uuid import UUID

import pytest

from config import get_identity_config
from domain.identity import MentionDecision, NewEntitySpec
from packs.loader import load_lang
from schema.extraction import ProposedEntity
from services.identity.mentions import find_spans, mention_rows
from services.identity.normalize import Normalizer
from services.identity.service import IdentityService
from tests.characterization import payloads
from tests.helpers import narration_with

pytestmark = pytest.mark.integration

NORMALIZER = Normalizer(load_lang("fr"))
TEXT = json.loads(payloads.NARRATION)["narrative_text"]


async def _turn(harness, game_id, narration: str, message: str = "Je continue.") -> None:
    harness.llm._responses["narration"] = narration
    events = await harness.chat(game_id, message)
    await harness.drain()
    assert "done" in harness.summarize(events), events


async def _last_message(conn, game_id) -> UUID:
    return await conn.fetchval(
        """SELECT id FROM messages WHERE game_id = $1 AND role = 'assistant'
           ORDER BY sequence DESC LIMIT 1""",
        game_id,
    )


async def _id_of(conn, game_id, ref: str, entity_type: str) -> UUID:
    entity_id = await conn.fetchval(
        "SELECT find_entity($1, $2, $3)", game_id, ref, entity_type
    )
    assert entity_id is not None, ref
    return entity_id


async def _handle(conn, entity_id: UUID) -> str:
    return "E" + str(
        await conn.fetchval("SELECT handle FROM entity_registry WHERE id = $1", entity_id)
    )


async def _count(conn, game_id, table: str, where: str = "TRUE", *args) -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM {table} WHERE game_id = $1 AND {where}", game_id, *args
    )


def _mention(surface: str, verdict: str, handle: str | None = None, **fields) -> dict:
    return {"surface": surface, "before": "", "decision": verdict, "handle": handle,
            "evidence": "", **fields}


# --- spans (pure) -----------------------------------------------------------------------


def test_spans_are_whole_words_on_the_raw_text_whatever_the_accents():
    text = "Éloïse parle. Eloise sourit ; Eloisette passe."
    spans = find_spans(text, "eloise", NORMALIZER)
    assert [text[s:e] for s, e in spans] == ["Éloïse", "Eloise"]


def test_a_shorter_mention_inside_a_longer_one_is_dropped():
    text = "Le Vieux Moulin tourne."
    mill, other = UUID(int=1), UUID(int=2)
    rows = mention_rows(
        text,
        [
            (MentionDecision(surface="Moulin", decision="MATCH"), other),
            (MentionDecision(surface="Vieux Moulin", decision="MATCH"), mill),
        ],
        NORMALIZER,
    )
    assert [(r.surface, r.entity_id, r.decision) for r in rows] == [
        ("Vieux Moulin", mill, "match")
    ]


def test_shared_surfaces_go_to_the_decision_whose_context_precedes_them():
    """Three « Vauclair », decided one by one (by their `before` words): the house, the
    castle, and one left UNSURE that no link may take."""
    text = "Un parchemin. Vauclair signe. Le chemin de ronde, Vauclair veille. Les murs de Vauclair."
    house, castle = UUID(int=1), UUID(int=2)
    unsure = MentionDecision(surface="Vauclair", decision="UNSURE", before="Un parchemin.")
    rows = mention_rows(
        text,
        [
            (MentionDecision(surface="Vauclair", decision="MATCH",
                             before="chemin de ronde,"), house),
            (MentionDecision(surface="Vauclair", decision="MATCH",
                             before="Les murs de"), castle),
        ],
        NORMALIZER,
        [unsure],
    )  # fmt: skip
    assert [(text[: r.start_pos].split()[-1], r.entity_id) for r in rows] == [
        ("ronde,", house),
        ("de", castle),
    ]


# --- the turn, end to end ----------------------------------------------------------------


async def test_a_turn_writes_mentions_served_by_entity_id(harness, world_game):
    await _turn(harness, world_game, payloads.NARRATION)
    async with harness.pool.acquire() as conn:
        message = await _last_message(conn, world_game)
        rows = await conn.fetch(
            """SELECT start_pos, end_pos, surface, entity_id, decision
               FROM entity_mentions WHERE message_id = $1 ORDER BY start_pos""",
            message,
        )
        labels = {
            r["entity_id"]: await conn.fetchval(
                "SELECT display_for_player($1)", r["entity_id"]
            )
            for r in rows
        }
        types = {
            r["entity_id"]: await conn.fetchval(
                "SELECT entity_type FROM entity_registry WHERE id = $1", r["entity_id"]
            )
            for r in rows
        }
        ossek = await _id_of(conn, world_game, "Ossek", "character")
        legacy = await conn.fetchval(
            "SELECT narrator_context FROM messages WHERE id = $1", message
        )
    assert legacy is None  # the dual write is gone (#155; the column goes with #166)
    assert [r["surface"] for r in rows] == ["Quart de Cycle", "Ossek"]
    assert {r["decision"] for r in rows} == {"deterministic"}
    assert all(TEXT[r["start_pos"] : r["end_pos"]] == r["surface"] for r in rows)
    r = await harness.client.get(
        "/api/tooltips/annotations", params={"gameId": world_game}, headers=harness.headers
    )
    served = {m["message_id"]: m["annotations"] for m in r.json()["messages"]}
    assert served[str(message)] == [
        {
            "start": m["start_pos"],
            "end": m["end_pos"],
            "entity_id": str(m["entity_id"]),
            "entity_type": types[m["entity_id"]],
            "label": labels[m["entity_id"]],
        }
        for m in rows
    ]
    # An NPC the PC had not identified, named exactly by the narration: the name is
    # revealed (spec §4.5.5 prepass), so the annotation now shows it.
    assert labels[ossek] == "Ossek"


async def test_new_entity_is_created_by_the_service_not_the_extractor(harness, world_game):
    harness.llm._responses["identity"] = payloads.IDENTITY_NEW_CHARACTER
    # The extractor met her too, outside the scene list: it proposes her again.
    harness.llm._responses["extract:extract_characters"] = (
        payloads.EXTRACT_CHARACTERS_PROPOSED
    )
    await _turn(harness, world_game, payloads.NARRATION_NEW_CHARACTER)
    async with harness.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, occupation FROM characters WHERE game_id = $1 AND true_name = $2",
            world_game,
            payloads.NEW_CHARACTER_NAME,
        )
        sources = await conn.fetch(
            "SELECT DISTINCT source FROM entity_aliases WHERE entity_id = $1",
            rows[0]["id"],
        )
        mention = await conn.fetchval(
            "SELECT decision FROM entity_mentions WHERE entity_id = $1", rows[0]["id"]
        )
    assert len(rows) == 1
    assert rows[0]["occupation"] == "Technicienne"  # the proposal refilled the stub
    assert {r["source"] for r in sources} <= {"system", "resolver", "extractor"}
    assert "resolver" in {r["source"] for r in sources}
    assert mention == "new"


async def test_extractor_runs_only_for_new_or_enriched_types(harness, world_game):
    # Known, already described entities only: no extractor.
    await _turn(harness, world_game, payloads.NARRATION)
    assert not [p for p in harness.llm.purposes() if p.startswith("extract:")]
    harness.llm.calls.clear()

    text = TEXT + "\n\nTu remarques la Halle aux Cordiers au bout de la rue."
    harness.llm._responses["identity"] = json.dumps({
        "mentions": [
            _mention("Halle aux Cordiers", "NEW", new_type="location",
                     new_kind="proper_name"),
        ]
    })
    await _turn(harness, world_game, narration_with(narrative_text=text))
    extracted = [p for p in harness.llm.purposes() if p.startswith("extract:")]
    assert extracted == ["extract:extract_locations"]


async def test_variant_of_a_present_npc_never_creates_a_duplicate(harness, world_game):
    async with harness.pool.acquire() as conn:
        service = await IdentityService.for_game(conn, UUID(world_game))
        eloise = await service.create_entity(
            conn,
            NewEntitySpec("character", "Éloïse", "proper_name", known=True),
            turn_id=None,
            source="world_gen",
        )
        before = await _count(conn, world_game, "characters")
    text = TEXT + "\n\nEloise s'approche. La jeune Eloise te salue."
    await _turn(
        harness,
        world_game,
        narration_with(narrative_text=text, npcs_present=["Ossek", "Éloïse"]),
    )
    async with harness.pool.acquire() as conn:
        after = await _count(conn, world_game, "characters")
        linked = await conn.fetch(
            "SELECT surface FROM entity_mentions WHERE entity_id = $1", eloise
        )
    assert after == before
    assert [r["surface"] for r in linked] == ["Eloise", "Eloise"]


async def test_three_turns_of_resolver_outage_do_not_break_coreference(
    harness, world_game
):
    async with harness.pool.acquire() as conn:
        service = await IdentityService.for_game(conn, UUID(world_game))
        voss = await service.create_entity(
            conn,
            NewEntitySpec("character", "Elara Voss", "proper_name", known=True),
            turn_id=None,
            source="world_gen",
        )
        before = await _count(conn, world_game, "characters")
    harness.llm.fail_on["identity"] = RuntimeError("provider down")
    for line in ("Voss te fait signe.", "Voss hésite.", "Voss s'en va."):
        await _turn(harness, world_game, narration_with(narrative_text=f"{TEXT}\n\n{line}"))
    harness.llm.fail_on.clear()
    # The model answers again, and would invent her: the prepass already linked "Voss".
    harness.llm._responses["identity"] = json.dumps({
        "mentions": [_mention("Voss", "NEW", new_type="character", new_kind="proper_name")]
    })
    await _turn(harness, world_game, narration_with(narrative_text=f"{TEXT}\n\nVoss revient."))
    async with harness.pool.acquire() as conn:
        fallbacks = await _count(conn, world_game, "identity_events", "kind = $2",
                                 "resolver_fallback")
        per_message = await conn.fetch(
            """SELECT m.id, count(em.id) FILTER (WHERE em.entity_id = $2) AS voss
                 FROM messages AS m LEFT JOIN entity_mentions AS em ON em.message_id = m.id
                WHERE m.game_id = $1 AND m.role = 'assistant'
                GROUP BY m.id, m.sequence ORDER BY m.sequence DESC LIMIT 4""",
            world_game,
            voss,
        )
        after = await _count(conn, world_game, "characters")
    assert fallbacks == 3
    assert [r["voss"] for r in per_message] == [1, 1, 1, 1]
    assert after == before


async def test_two_turns_back_to_back_keep_both_resolutions(harness, world_game):
    harness.llm._responses["narration"] = payloads.NARRATION
    await harness.chat(world_game, "Tour A.")
    await harness.chat(world_game, "Tour B.")  # no drain in between on purpose
    await harness.drain()
    async with harness.pool.acquire() as conn:
        counts = await conn.fetch(
            """SELECT count(em.id) AS mentions
                 FROM messages AS m LEFT JOIN entity_mentions AS em ON em.message_id = m.id
                WHERE m.game_id = $1 AND m.role = 'assistant'
                GROUP BY m.id, m.sequence ORDER BY m.sequence DESC LIMIT 2""",
            world_game,
        )
    assert [r["mentions"] for r in counts] == [2, 2]


async def test_companion_mention_matches_the_companion_and_creates_nothing(
    harness, world_game
):
    async with harness.pool.acquire() as conn:
        companion = await conn.fetchval(
            """SELECT id FROM entity_registry WHERE game_id = $1
               AND entity_type = 'companion'""",
            world_game,
        )
        before = await _count(conn, world_game, "characters")
    harness.llm._responses["identity"] = json.dumps({
        "mentions": [
            _mention("Célimène", "NEW", new_type="character", new_kind="proper_name")
        ]
    })
    text = TEXT + "\n\nCélimène soupire dans ton oreillette."
    await _turn(harness, world_game, narration_with(narrative_text=text))
    async with harness.pool.acquire() as conn:
        linked = await conn.fetchval(
            "SELECT entity_id FROM entity_mentions WHERE surface = $1 AND game_id = $2",
            "Célimène",
            world_game,
        )
        after = await _count(conn, world_game, "characters")
    assert linked == companion
    assert after == before


async def test_resolver_output_never_reaches_the_player(harness, world_game):
    surface = "la silhouette au comptoir"
    async with harness.pool.acquire() as conn:
        ossek = await _id_of(conn, world_game, "Ossek", "character")
        handle = await _handle(conn, ossek)
        shown = await conn.fetchval("SELECT display_for_player($1)", ossek)
    harness.llm._responses["identity"] = json.dumps(
        {"mentions": [_mention(surface, "MATCH", handle)]}
    )
    text = TEXT + f"\n\nTu observes {surface} sans un mot."
    await _turn(harness, world_game, narration_with(narrative_text=text))
    async with harness.pool.acquire() as conn:
        message = await _last_message(conn, world_game)
    r = await harness.client.get(
        "/api/tooltips/annotations", params={"gameId": world_game}, headers=harness.headers
    )
    served = {m["message_id"]: m["annotations"] for m in r.json()["messages"]}
    context = served[str(message)]
    spans = [a for a in context if text[a["start"] : a["end"]] == surface]
    assert spans and all(a["label"] == shown for a in spans)
    labels = {a["label"] for m in r.json()["messages"] for a in m["annotations"]}
    assert surface not in labels


# --- proposals of the extractors (spec §4.6) --------------------------------------------


@pytest.fixture
async def game(test_pool, test_user) -> UUID:
    async with test_pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
            test_user["id"],
        )


async def test_a_proposal_reuses_an_exact_alias_then_a_close_name_then_creates(
    test_pool, game
):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        mill = await service.create_entity(
            conn,
            NewEntitySpec("location", "Halle aux Cordiers", "proper_name"),
            turn_id=None,
            source="world_gen",
        )
        exact = await service.create_from_extractor(
            conn, ProposedEntity(entity_type="location", label="la Halle aux Cordiers")
        )
        close = await service.create_from_extractor(
            conn, ProposedEntity(entity_type="location", label="Halle Cordiers")
        )
        fresh = await service.create_from_extractor(
            conn, ProposedEntity(entity_type="location", label="Pont des Tanneurs")
        )
        reused = await conn.fetchval(
            """SELECT count(*) FROM identity_events
               WHERE game_id = $1 AND kind = 'extractor_reused' AND entity_id = $2""",
            game,
            mill,
        )
    assert exact == mill and close == mill and fresh != mill
    assert reused == 1


async def test_a_proposal_never_lands_on_a_removed_entity(test_pool, game):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        gone = await service.create_entity(
            conn,
            NewEntitySpec("character", "Tobias Renn", "proper_name"),
            turn_id=None,
            source="world_gen",
        )
        await conn.execute("UPDATE characters SET removed_cycle = 1 WHERE id = $1", gone)
        again = await service.create_from_extractor(
            conn, ProposedEntity(entity_type="character", label="Tobias Renn")
        )
    assert again != gone


# --- application of the decisions (spec §4.5.6) ------------------------------------------


async def _resolve(conn, game, text: str, mentions: list[dict], *, present=(), strong=()):
    """block, decide and apply_resolution on `text` with scripted identity answers (`strong`: the second
    opinion's), outside any turn."""
    from domain.identity import SceneContext, TurnRef
    from llm.session import LLMSession
    from repos import entities, messages
    from tests.characterization.scripted_llm import ScriptedLLMProvider

    protagonist = await conn.fetchval(
        "SELECT id FROM entity_registry WHERE game_id = $1 AND entity_type = 'protagonist'",
        game,
    ) or await entities.insert_domain_row(
        conn, game, "protagonist", {"name": "Rafe"}, label_suffix=None
    )
    conversation = await messages.insert_conversation(conn, game, 1)
    message = await messages.insert_message(conn, game, conversation, "assistant", text, 1)
    scene = SceneContext(
        location_id=None,
        present_ids=list(present),
        recent_message_ids=[],
        reveal_refs=[],
        planned_npc_handles=[],
        open_disclosure_ids=[],
        protagonist_id=protagonist,
        companion_id=None,
    )
    provider = ScriptedLLMProvider({
        "identity": json.dumps({"mentions": mentions}),
        "identity_strong": json.dumps({"mentions": list(strong)}),
    })
    service = IdentityService(game, lang="fr", config=get_identity_config())
    candidates = await service.block(conn, text, scene)
    decided = await service.decide(
        conn, LLMSession.from_provider(provider), text, scene, candidates
    )
    resolution = await service.apply_resolution(
        conn, TurnRef(None, message, 3), text, scene, decided
    )
    return resolution, message


async def test_a_new_descriptor_is_labelled_without_its_article(test_pool, game):
    text = "La vieille au châle tricote près du feu."
    async with test_pool.acquire() as conn:
        resolution, message = await _resolve(
            conn,
            game,
            text,
            [_mention("La vieille au châle", "NEW", new_type="character",
                      new_kind="descriptor")],
        )
        row = await conn.fetchrow(
            "SELECT id, descriptor, true_name, created_cycle FROM characters"
            " WHERE game_id = $1",
            game,
        )
        stored = await conn.fetch(
            "SELECT surface, decision FROM entity_mentions WHERE message_id = $1", message
        )
    assert (row["descriptor"], row["true_name"], row["created_cycle"]) == (
        "Vieille au châle",
        None,
        3,
    )
    assert [(r["surface"], r["decision"]) for r in stored] == [
        ("La vieille au châle", "new")
    ]
    assert resolution.new_types == {"character"}
    assert [(i, line.is_new) for i, line in resolution.created] == [(row["id"], True)]
    assert [line.label for line in resolution.scene_entities] == ["Vieille au châle"]


async def test_a_new_decided_over_a_shown_candidate_is_never_folded_into_it(
    test_pool, game
):
    """« son terminal » (the cook's) decided NEW while the protagonist's « Terminal
    personnel » (short alias « Terminal ») was on the cards: a new object, not a reuse."""
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        mine = await service.create_entity(
            conn,
            NewEntitySpec("object", "Terminal personnel", "proper_name"),
            turn_id=None,
            source="world_gen",
        )
        text = "Le cuisinier pose son terminal sur le comptoir. Terminal personnel."
        resolution, _ = await _resolve(
            conn,
            game,
            text,
            [_mention("son terminal", "NEW", new_type="object", new_kind="descriptor")],
        )
        objects = await conn.fetch("SELECT id FROM objects WHERE game_id = $1", game)
    [created] = [i for i, line in resolution.created]
    assert created != mine and len(objects) == 2
    assert {r.entity_id for r in resolution.mentions if r.surface == "son terminal"} == {
        created
    }


async def test_an_alias_is_learned_and_a_true_name_is_revealed(test_pool, game):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        smith = await service.create_entity(
            conn,
            NewEntitySpec("character", "Forgeronne au tablier", "descriptor"),
            turn_id=None,
            source="world_gen",
        )
        handle = await _handle(conn, smith)
        text = "« Je suis Maëlle Corvin », dit la forgeronne. La Rouquine sourit."
        true_name = _mention("Maëlle Corvin", "ALIAS", handle, alias_kind="true_name")
        resolution, _ = await _resolve(
            conn,
            game,
            text,
            [true_name, _mention("La Rouquine", "ALIAS", handle, alias_kind="nickname")],
            present=[smith],
            # A revealed true name is escalated: the strong model confirms it.
            strong=[true_name],
        )
        row = await conn.fetchrow(
            "SELECT true_name, known_by_protagonist FROM characters WHERE id = $1", smith
        )
        nickname = await conn.fetchval(
            "SELECT source FROM entity_aliases WHERE entity_id = $1 AND kind = 'nickname'",
            smith,
        )
    assert (row["true_name"], row["known_by_protagonist"]) == ("Maëlle Corvin", True)
    assert nickname == "resolver"
    assert resolution.aliases_added == 1
    assert [r.kind for r in resolution.reveals] == ["applied"]
    assert resolution.escalated
    # A linked stub without description is worth an extraction (enrichable).
    assert resolution.new_types == {"character"}


# --- review round 1: strict close names, fresh links, traps, bounded enrichment -------


def _lexicon_normalizer():
    from services.identity.lexicon import for_game

    return for_game("fr", None), Normalizer(load_lang("fr"), get_identity_config())


@pytest.mark.parametrize(
    "proposal, existing",
    [
        ("Jon Kessler", "Mira Kessler"),
        ("Carte niveau 3", "Carte niveau 2"),
        ("Clé rouillée", "Clé"),
        ("Garde du sas", "Garde"),
    ],
)
def test_close_names_never_fold_distinct_entities(proposal, existing):
    from services.identity.proposals import close_entity

    lexicon, normalizer = _lexicon_normalizer()
    assert (
        close_entity(
            proposal,
            [(UUID(int=1), existing)],
            threshold=get_identity_config().create_from_extractor,
            normalizer=normalizer,
            lexicon=lexicon,
        )
        is None
    )


def test_a_close_name_differing_by_stop_words_only_is_the_same_entity():
    from services.identity.proposals import close_entity

    lexicon, normalizer = _lexicon_normalizer()
    assert close_entity(
        "Halle Cordiers",
        [(UUID(int=1), "la Halle aux Cordiers"), (UUID(int=2), "Pont des Tanneurs")],
        threshold=get_identity_config().create_from_extractor,
        normalizer=normalizer,
        lexicon=lexicon,
    ) == UUID(int=1)


@pytest.mark.parametrize(
    "entity_type, existing, proposal",
    [
        ("character", "Mira Kessler", "Jon Kessler"),
        ("object", "Carte niveau 2", "Carte niveau 3"),
        ("object", "Clé", "Clé rouillée"),
    ],
)
async def test_a_proposal_close_to_a_short_alias_or_a_number_creates_its_own_entity(
    test_pool, game, entity_type, existing, proposal
):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        first = await service.create_entity(
            conn,
            NewEntitySpec(entity_type, existing, "proper_name"),
            turn_id=None,
            source="world_gen",
        )
        second = await service.create_from_extractor(
            conn, ProposedEntity(entity_type=entity_type, label=proposal)
        )
    assert second != first


async def test_an_acquired_object_is_never_folded_into_a_close_one(test_pool, test_user):
    from schema.extraction import ObjectCreation
    from kg.specialized_populator import ExtractionPopulator
    from services.game_service import GameService

    game_id = await GameService(test_pool).create_game(test_user["id"])
    populator = ExtractionPopulator(test_pool, game_id)
    async with test_pool.acquire() as conn:
        two = await populator.create_object_by_label(
            conn, ObjectCreation(name="Carte niveau 2", from_hint="carte"), 1
        )
        three = await populator.create_object_by_label(
            conn, ObjectCreation(name="Carte niveau 3", from_hint="carte"), 1
        )
    assert two is not None and three is not None and two != three


async def _message(conn, game, text: str) -> UUID:
    from repos import messages

    conversation = await messages.insert_conversation(conn, game, 1)
    sequence = await conn.fetchval(
        "SELECT coalesce(max(sequence), 0) + 1 FROM messages WHERE game_id = $1", game
    )
    return await messages.insert_message(
        conn, game, conversation, "assistant", text, sequence
    )


def _scene(location_id=None, present=()):
    from domain.identity import SceneContext

    return SceneContext(
        location_id=location_id,
        present_ids=list(present),
        recent_message_ids=[],
        reveal_refs=[],
        planned_npc_handles=[],
        open_disclosure_ids=[],
        protagonist_id=None,
        companion_id=None,
    )


async def _apply(conn, game, text, decisions, scene=None):
    """apply_resolution on crafted decisions (no blocking, no model)."""
    from domain.identity import CandidateSet, TurnDecisions, TurnRef
    from services.identity.resolution import DecidedTurn

    service = IdentityService(game, lang="fr", config=get_identity_config())
    message = await _message(conn, game, text)
    decided = DecidedTurn(
        CandidateSet([], [], {}),
        TurnDecisions(decisions, escalated=False, fallback=False, usage={}),
    )
    resolution = await service.apply_resolution(
        conn, TurnRef(None, message, 2), text, scene or _scene(), decided
    )
    return resolution, message


async def test_a_link_follows_a_merge_committed_after_the_decision(test_pool, game):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        keep = await service.create_entity(
            conn, NewEntitySpec("character", "Tobias Renn", "proper_name"),
            turn_id=None, source="world_gen",
        )
        drop = await service.create_entity(
            conn, NewEntitySpec("character", "Toby Renn", "proper_name"),
            turn_id=None, source="world_gen",
        )
        decided_on_drop = [
            MentionDecision(surface="Grand Tob", decision="ALIAS",
                            alias_kind="nickname", entity_id=drop, verified=True),
        ]
        merged = await service.merge(conn, keep, drop, reason="test", turn_id=None)
        assert merged.refused is None
        resolution, message = await _apply(
            conn, game, "Grand Tob salue.", decided_on_drop
        )
        mention = await conn.fetchval(
            "SELECT entity_id FROM entity_mentions WHERE message_id = $1", message
        )
        nickname = await conn.fetchval(
            "SELECT entity_id FROM entity_aliases WHERE kind = 'nickname' AND game_id = $1",
            game,
        )
        redirected = await conn.fetch(
            """SELECT entity_id, payload FROM identity_events
               WHERE game_id = $1 AND kind = 'tombstone_redirected'""",
            game,
        )
    assert mention == keep and nickname == keep
    assert [line.label for line in resolution.scene_entities] == ["Tobias Renn"]
    # The merge caught at write time is recorded like one caught at decision time.
    assert [
        (r["entity_id"], json.loads(r["payload"]) if isinstance(r["payload"], str)
         else r["payload"])
        for r in redirected
    ] == [(keep, {"from": str(drop)})]


async def test_a_link_to_an_entity_gone_since_the_decision_is_dropped(test_pool, game):
    from uuid import uuid4

    async with test_pool.acquire() as conn:
        resolution, message = await _apply(
            conn,
            game,
            "Toby salue.",
            [MentionDecision(surface="Toby", decision="MATCH", entity_id=uuid4(),
                             verified=True)],
        )
        stale = await _count(conn, game, "identity_events", "kind = $2", "link_stale")
    assert resolution.mentions == [] and stale == 1


async def test_a_decision_that_takes_no_span_writes_nothing(test_pool, game):
    """I1: the prepass took « Le Terminal »; a model ALIAS, a reveal and a NEW on
    « Terminal » inside it own no span, so no alias, no reveal and no entity is written,
    and every alias, reveal or entity the turn writes has a mention of its own."""
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        hall = await service.create_entity(
            conn, NewEntitySpec("location", "Terminal", "proper_name"),
            turn_id=None, source="world_gen",
        )
        quay = await service.create_entity(
            conn, NewEntitySpec("location", "Terminal Quai 7", "proper_name"),
            turn_id=None, source="world_gen",
        )
        before = await _count(conn, game, "entity_registry")
        aliases = await _count(conn, game, "entity_aliases")
        text = "Le Terminal clignote. Tu avances."
        decisions = [
            MentionDecision(surface="Le Terminal", decision="MATCH", entity_id=hall,
                            verified=True, deterministic=True, start=0),
            MentionDecision(surface="Terminal", decision="ALIAS", before="Le",
                            alias_kind="nickname", entity_id=quay, verified=True),
            MentionDecision(surface="Terminal", decision="ALIAS", before="Le",
                            alias_kind="true_name", entity_id=quay, verified=True),
            MentionDecision(surface="Terminal", decision="NEW", before="Le",
                            new_type="location", new_kind="proper_name",
                            verified=True),
        ]  # fmt: skip
        resolution, message = await _apply(conn, game, text, decisions)
        stored = await conn.fetch(
            "SELECT entity_id, decision FROM entity_mentions WHERE message_id = $1",
            message,
        )
        assert await _count(conn, game, "entity_registry") == before
        assert await _count(conn, game, "entity_aliases") == aliases
    assert [(r["entity_id"], r["decision"]) for r in stored] == [
        (hall, "deterministic")
    ]
    assert resolution.created == [] and resolution.reveals == []
    assert resolution.aliases_added == 0
    stats = resolution.stats()
    assert (stats["created"], stats["aliases"], stats["reveals"]) == (0, 0, 0)


async def test_a_new_that_creates_nothing_never_hands_its_span_to_a_non_owner(
    test_pool, game
):
    """N1: the NEW « Vieux Moulin » owns the span but its label is ambiguous (aliases of
    two mills) and creates nothing; the shorter ALIAS « Moulin » it covered owned no span,
    wrote no alias, and gets no mention either (the spans are placed once)."""
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        mills = []
        for label in ("Moulin Haut", "Moulin Bas"):
            mill = await service.create_entity(
                conn, NewEntitySpec("location", label, "proper_name"),
                turn_id=None, source="world_gen",
            )
            await service.add_alias(conn, mill, "Vieux Moulin", "nickname", known=True,
                                    source="world_gen")
            mills.append(mill)
        aliases = await _count(conn, game, "entity_aliases")
        decisions = [
            MentionDecision(surface="Vieux Moulin", decision="NEW", new_type="location",
                            new_kind="proper_name", verified=True),
            MentionDecision(surface="Moulin", decision="ALIAS", alias_kind="nickname",
                            entity_id=mills[0], verified=True),
        ]  # fmt: skip
        resolution, message = await _apply(
            conn, game, "Le Vieux Moulin tourne.", decisions
        )
        stored = await _count(conn, game, "entity_mentions", "message_id = $2", message)
        assert await _count(conn, game, "entity_aliases") == aliases
    assert stored == 0 and resolution.mentions == [] and resolution.spans == []
    assert resolution.created == [] and resolution.aliases_added == 0


def _new_guard(**fields) -> MentionDecision:
    return MentionDecision(surface="le garde", decision="NEW", new_type="character",
                           new_kind="descriptor", verified=True, **fields)


async def _guards(conn, game) -> list:
    return await conn.fetch(
        """SELECT c.id, er.name FROM characters AS c JOIN entity_registry AS er
           ON er.id = c.id WHERE c.game_id = $1 AND c.descriptor = 'Garde'""",
        game,
    )


async def _guard_and_places(conn, service, *, works_at: bool):
    dock = await service.create_entity(
        conn, NewEntitySpec("location", "Quai Nord", "proper_name"),
        turn_id=None, source="world_gen",
    )
    hall = await service.create_entity(
        conn, NewEntitySpec("location", "Halle aux Cordiers", "proper_name"),
        turn_id=None, source="world_gen",
    )
    guard = await service.create_entity(
        conn,
        NewEntitySpec("character", "Garde", "descriptor",
                      fields={"workplace_id": dock} if works_at else {}),
        turn_id=None, source="world_gen",
    )
    return guard, dock, hall


async def test_a_descriptor_seen_elsewhere_than_its_holder_is_a_second_entity(
    test_pool, game
):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        guard, _, hall = await _guard_and_places(conn, service, works_at=True)
        resolution, _ = await _apply(
            conn, game, "Le garde te barre la route.", [_new_guard()], _scene(hall)
        )
        guards = await _guards(conn, game)
    assert len(guards) == 2
    newcomer = next(r for r in guards if r["id"] != guard)
    assert newcomer["name"] != "Garde"  # internal suffix, never shown to the player
    assert [i for i, _ in resolution.created] == [newcomer["id"]]


async def test_a_descriptor_whose_holder_has_no_known_place_is_that_holder(
    test_pool, game
):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        guard, _, hall = await _guard_and_places(conn, service, works_at=False)
        resolution, message = await _apply(
            conn, game, "Le garde te barre la route.", [_new_guard()], _scene(hall)
        )
        guards = await _guards(conn, game)
        mention = await conn.fetchval(
            "SELECT entity_id FROM entity_mentions WHERE message_id = $1", message
        )
    assert [r["id"] for r in guards] == [guard] and mention == guard
    assert resolution.created == []


async def test_a_descriptor_at_its_holders_place_is_that_holder(test_pool, game):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        guard, dock, _ = await _guard_and_places(conn, service, works_at=True)
        await _apply(conn, game, "Le garde te barre la route.", [_new_guard()],
                     _scene(dock))
        guards = await _guards(conn, game)
    assert [r["id"] for r in guards] == [guard]


async def test_two_people_talking_under_one_descriptor_are_two_entities(test_pool, game):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        guard, dock, _ = await _guard_and_places(conn, service, works_at=True)
        await _apply(
            conn,
            game,
            "Le garde parle à Voss.",
            [_new_guard(talks_to=("Voss",))],
            _scene(dock, present=[guard]),
        )
        guards = await _guards(conn, game)
    assert len(guards) == 2


async def test_a_bare_stub_is_sent_to_its_extractor_once(test_pool, game):
    service = IdentityService(game, lang="fr", config=get_identity_config())
    async with test_pool.acquire() as conn:
        stub = await service.create_entity(
            conn, NewEntitySpec("location", "Quai 9", "proper_name"),
            turn_id=None, source="resolver",
        )
        link = [MentionDecision(surface="Quai 9", decision="MATCH", entity_id=stub,
                                verified=True)]
        first, _ = await _apply(conn, game, "Le Quai 9 est vide.", link)
        second, _ = await _apply(conn, game, "Le Quai 9 est toujours vide.", link)
    assert first.new_types == {"location"}
    assert second.new_types == set()


async def test_no_pool_connection_is_held_during_the_model_calls(test_pool, test_user):
    """#94: the resolver's model calls run with no connection of the pool held."""
    from types import SimpleNamespace

    from domain.identity import TurnRef
    from llm.session import LLMCall
    from services.extraction import orchestrator
    from services.game_service import GameService
    from services.llm_providers import StructuredOutputMode

    game_id = await GameService(test_pool).create_game(test_user["id"])
    async with test_pool.acquire() as conn:
        message = await _message(conn, game_id, TEXT)
    pool = _CountingPool(test_pool)
    seen = []

    class _Session:
        def provider_for(self, purpose):
            return SimpleNamespace(structured_output_mode=StructuredOutputMode.TOOL_USE)

        async def extract_structured(self, *args, **kwargs):
            seen.append(pool.in_use)
            return LLMCall(value={"mentions": []}, cost=None)

    resolution = await orchestrator.resolve_phase(
        pool, _Session(), game_id, TurnRef(None, message, 1), TEXT, {}
    )
    assert seen == [0]
    assert resolution is not None


class _CountingPool:
    """A real pool whose acquired connections are counted (`in_use`)."""

    def __init__(self, pool):
        self._pool = pool
        self.in_use = 0

    def acquire(self):
        outer = self

        class _Acquire:
            async def __aenter__(self):
                self._cm = outer._pool.acquire()
                conn = await self._cm.__aenter__()
                outer.in_use += 1
                return conn

            async def __aexit__(self, *exc):
                outer.in_use -= 1
                return await self._cm.__aexit__(*exc)

        return _Acquire()
