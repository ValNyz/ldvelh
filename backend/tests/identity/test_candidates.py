"""Candidate blocking of the resolver v2 (#154, spec §4.5.2): six SQL generators, no type
excluded, no secret alias without an open disclosure, thresholds from IdentityConfig, and
turn-set recall >= 0.98 on the gold corpus (dev + test; per-mention C@10 printed)."""

from collections import Counter
from pathlib import Path
from uuid import UUID

import pytest

from config import IdentityConfig, get_identity_config
from domain.identity import AliasSpec, NewEntitySpec, SceneContext
from evals.identity.blocking import candidates_by_mention
from evals.identity.corpus import load_scenes, load_split, parse_expected
from evals.identity.run import RunResult
from evals.identity.scorer import CANDIDATES_K, LINKS, aggregate, score_scene
from evals.identity.world_loader import load_world, scene_context, turn_key
from repos import entities
from services.identity import candidates
from services.identity.service import IdentityService

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity"
RECALL_FLOOR = 0.98


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


async def _scene(conn, game_id: UUID, **fields) -> SceneContext:
    protagonist = await entities.insert_domain_row(
        conn, game_id, "protagonist", {"name": "Rafe"}, label_suffix=None
    )
    values = {
        "location_id": None,
        "present_ids": [],
        "recent_message_ids": [],
        "reveal_refs": [],
        "planned_npc_handles": [],
        "open_disclosure_ids": [],
        "protagonist_id": protagonist,
        "companion_id": None,
        "genre": None,
    }
    return SceneContext(**{**values, **fields})


async def _create(conn, service, entity_type, label, kind="proper_name", **spec):
    return await service.create_entity(
        conn,
        NewEntitySpec(entity_type, label, kind, **spec),
        turn_id=None,
        source="world_gen",
        reuse_aliases=False,
    )


async def _block(conn, service, text, scene, config=None, lexicon=None):
    return await candidates.block(
        conn,
        service.game_id,
        text,
        scene,
        config=config or service.config,
        normalizer=service.normalizer,
        lexicon=lexicon or service.lexicon,
    )


def _by_id(candidate_set):
    return {c.entity_id: c for c in candidate_set.ranked()}


async def test_exact_normalized_match_is_unique_and_typed(test_pool, game, service):
    async with test_pool.acquire() as conn:
        quay = await _create(conn, service, "location", "Quai 9")
        tesk = await _create(conn, service, "character", "Tesk Vahrun")
        scene = await _scene(conn, game)
        found = await _block(
            conn, service, "Tu remontes le quai 9 sans te presser.", scene
        )
    assert {c.entity_id for c in found.exact.values()} == {quay}
    assert found.exact["quai 9"].entity_id == quay
    assert found.exact["quai 9"].entity_type == "location"
    assert candidates.EXACT in found.exact["quai 9"].sources
    assert found.turn[0].entity_id == quay
    assert tesk not in _by_id(found)


async def test_partial_name_is_found_by_token_overlap(test_pool, game, service):
    async with test_pool.acquire() as conn:
        ondrev = await _create(conn, service, "character", "Pater Ondrev")
        scene = await _scene(conn, game)
        found = await _block(conn, service, "Ondrev referme le registre.", scene)
    assert candidates.TOKENS in _by_id(found)[ondrev].sources


async def test_typo_is_found_by_levenshtein(test_pool, game, service):
    """« Eloise » and « Éloïse » share one norm (unaccent): the typo is « Eloize »."""
    async with test_pool.acquire() as conn:
        eloise = await _create(conn, service, "character", "Éloïse")
        scene = await _scene(conn, game)
        found = await _block(conn, service, "Eloize hausse les épaules.", scene)
    assert candidates.LEVENSHTEIN in _by_id(found)[eloise].sources


async def test_descriptor_is_found_by_context_only(test_pool, game, service):
    async with test_pool.acquire() as conn:
        elder = await _create(
            conn, service, "character", "La Kethari âgée", "descriptor"
        )
        scene = await _scene(conn, game, present_ids=[elder])
        found = await _block(conn, service, "La vieille femme te sourit.", scene)
    assert elder not in {c.entity_id for c in found.turn}
    [card] = [c for c in found.context if c.entity_id == elder]
    assert "present" in card.sources
    assert card.score == 0


async def test_occupation_matches_la_cheffe_de_serre(test_pool, game, service):
    async with test_pool.acquire() as conn:
        oriane = await _create(
            conn,
            service,
            "character",
            "Oriane Vasseur",
            fields={"occupation": "cheffe de serre"},
        )
        scene = await _scene(conn, game)
        found = await _block(
            conn, service, "La cheffe de serre essuie ses mains.", scene
        )
    card = _by_id(found)[oriane]
    assert candidates.OCCUPATION in card.sources
    assert card.occupation == "cheffe de serre"


async def test_cross_type_homonyms_are_both_returned_with_their_type(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        bird = await _create(conn, service, "character", "Corbeau")
        gang = await _create(conn, service, "organization", "Corbeau")
        scene = await _scene(conn, game)
        found = await _block(conn, service, "Corbeau t'attend.", scene)
    by_id = _by_id(found)
    assert (by_id[bird].entity_type, by_id[gang].entity_type) == (
        "character",
        "organization",
    )
    assert "corbeau" not in found.exact  # two entities: not unique


async def test_secret_alias_never_appears_without_an_open_disclosure(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        elder = await _create(
            conn,
            service,
            "character",
            "La Kethari âgée",
            "descriptor",
            aliases=[AliasSpec("Nahle Irun-Sa", "true_name", False, secret=True)],
        )
        closed = await _scene(conn, game, present_ids=[elder])
        hidden = await _block(conn, service, "Nahle Irun-Sa", closed)
        opened = await _block(
            conn,
            service,
            "Nahle Irun-Sa",
            SceneContext(**{**closed.__dict__, "open_disclosure_ids": [elder]}),
        )
    assert elder not in {c.entity_id for c in hidden.turn}
    [card] = [c for c in hidden.context if c.entity_id == elder]
    assert all(not a.secret for a in card.aliases)
    assert "nahle irun-sa" not in {a.alias_norm for a in card.aliases}
    disclosed = _by_id(opened)[elder]
    assert candidates.EXACT in disclosed.sources
    assert any(a.secret for a in disclosed.aliases)


async def test_unknown_ordinary_aliases_are_on_the_card(test_pool, game, service):
    async with test_pool.acquire() as conn:
        voss = await _create(
            conn,
            service,
            "character",
            "Elara Voss",
            known=False,
            descriptor="La médecin",
        )
        scene = await _scene(conn, game, present_ids=[voss])
        found = await _block(conn, service, "La médecin se retourne.", scene)
    card = _by_id(found)[voss]
    assert ("Elara Voss", False) in {(a.alias, a.known) for a in card.aliases}
    assert card.label != "Elara Voss"  # what the player may read


async def test_short_low_entropy_aliases_are_not_fuzzed(test_pool, game, service):
    async with test_pool.acquire() as conn:
        rok = await _create(conn, service, "character", "Rok")
        loose = IdentityConfig(s_word=0, s_sim=0)
        scene = await _scene(conn, game)
        found = await _block(conn, service, "Rak entre.", scene, config=loose)
    assert rok not in _by_id(found)


async def test_turn_set_is_capped_by_config(test_pool, game, service):
    async with test_pool.acquire() as conn:
        for n in range(1, 13):
            await _create(conn, service, "location", f"Tour Nord {n}")
        scene = await _scene(conn, game)
        capped = IdentityConfig(max_candidates=5)
        found = await _block(
            conn, service, "Tu montes à la tour.", scene, config=capped
        )
        every = await _block(conn, service, "Tu montes à la tour.", scene)
    assert len(found.turn) == 5
    assert len(every.turn) == 12
    assert [c.score for c in every.turn] == sorted(
        (c.score for c in every.turn), reverse=True
    )


async def test_context_holds_recent_mentions_reveals_and_the_companion(
    test_pool, game, service
):
    async with test_pool.acquire() as conn:
        tesk = await _create(conn, service, "character", "Tesk Vahrun")
        mira = await _create(conn, service, "character", "Mira Sol")
        companion = await entities.insert_domain_row(
            conn, game, "companion", {"name": "Célimène"}, label_suffix=None
        )
        handle = await entities.handle_of(conn, mira)
        scene = await _scene(
            conn, game, companion_id=companion, reveal_refs=[f"E{handle}"]
        )
        found = await _block(conn, service, "Personne ne parle.", scene)
    sources = {c.entity_id: c.sources for c in found.context}
    assert "reveal" in sources[mira]
    assert "companion" in sources[companion]
    assert "protagonist" in sources[scene.protagonist_id]
    assert tesk not in sources


async def test_load_world_rebuilds_a_scene(test_pool, game):
    [scene] = [s for s in load_scenes(FIXTURES) if s.id == "audit-canonique-invente"]
    async with test_pool.acquire() as conn:
        ids = await load_world(conn, game, scene.world, scene.history, turn=scene.turn)
        garrec = ids["character_garrec_mortemain"]
        aliases = {
            a.alias: (a.kind, a.known, a.secret)
            for a in await entities.list_aliases(conn, game, garrec)
        }
        history = await entities.mentions_for_messages(conn, game, [ids[turn_key(14)]])
        earlier = await entities.mentions_for_messages(conn, game, [ids[turn_key(13)]])
        context = scene_context(scene, ids, context_messages=2)
        cards = await entities.candidate_cards(conn, game, [garrec])
    assert {e.id for e in scene.world} <= set(ids)
    assert {turn_key(t) for t in range(1, 15)} <= set(ids)
    assert aliases["Garrec Mortemain"] == ("true_name", False, False)
    assert aliases["l'homme au tablier de cuir"] == ("descriptor", True, False)
    assert {m.entity_id for m in history[ids[turn_key(14)]]} == {
        garrec,
        ids["location_forge_de_la_rue_basse"],
        ids["object_dague_brisee"],
    }
    # Last seen in turn 13, before the history: a message of that turn names it.
    assert {m.entity_id for m in earlier[ids[turn_key(13)]]} == {
        ids["organization_guilde_des_ferrons"]
    }
    assert context.recent_message_ids == [ids[turn_key(14)], ids[turn_key(13)]]
    assert context.location_id == ids["location_forge_de_la_rue_basse"]
    assert set(context.present_ids) == {
        ids["protagonist_isaure"],
        ids["companion_noctule"],
        garrec,
    }
    assert context.reveal_refs == ["Le forgeron borgne"]
    assert cards[0].last_seen_turn == 14
    assert cards[0].occupation == "forgeron de la Forge de la Rue Basse"
    assert cards[0].usual_location == "Forge de la Rue Basse"


# --- recall on the gold corpus -------------------------------------------------------


async def _corpus_candidates(conn, user_id, scene):
    game_id = await conn.fetchval(
        "INSERT INTO games (user_id, language) VALUES ($1, $2) RETURNING id",
        user_id,
        scene.language,
    )
    ids = await load_world(conn, game_id, scene.world, scene.history, turn=scene.turn)
    by_mention, turn = await candidates_by_mention(conn, game_id, scene, ids)
    return by_mention, set(turn)


def _accepted_ids(mention) -> set[str]:
    forms = [mention.parsed, *(parse_expected(a) for a in mention.accept_also)]
    return {f.entity_id for f in forms if f.decision in LINKS}


async def test_blocking_recall_of_the_turn_set_on_the_whole_corpus(
    test_pool, test_user, capsys
):
    """Gate (spec §4.5.2, ruling R24): the gold id of every existing gold mention of dev +
    test is in its scene's CandidateSet (turn and context), at least 98 times in 100. The
    per-mention C@10 of the scorer is printed alongside, not gated."""
    split = load_split(FIXTURES)
    splits = {scene_id: "dev" for scene_id in split.dev}
    splits.update({scene_id: "test" for scene_id in split.test})
    scores = {"dev": [], "test": []}
    turn_hits = {"dev": Counter(), "test": Counter()}
    turn_misses, mention_misses = [], []
    async with test_pool.acquire() as conn:
        for scene in (s for s in load_scenes(FIXTURES) if s.id in splits):
            part = splits[scene.id]
            per_mention, whole = await _corpus_candidates(conn, test_user["id"], scene)
            score = score_scene(scene, RunResult(scene.id, [], per_mention, {}))
            scores[part].append(score)
            for m, outcome in zip(scene.gold, score.outcomes, strict=True):
                if m.parsed.decision not in LINKS:
                    continue
                miss = (part, scene.id, m.category, m.surface, m.expected)
                hit = bool(_accepted_ids(m) & whole)
                turn_hits[part][hit] += 1
                if not hit:
                    turn_misses.append(miss)
                if outcome.candidate_hit is False:
                    ranked = per_mention[m.start]
                    rank = (
                        ranked.index(m.parsed.entity_id) + 1
                        if (m.parsed.entity_id in ranked)
                        else None
                    )
                    mention_misses.append((*miss, rank))

    def recall(counts: Counter) -> float:
        return counts[True] / sum(counts.values())

    overall = recall(turn_hits["dev"] + turn_hits["test"])
    c_at_10 = aggregate(scores["dev"] + scores["test"]).c_at_10
    with capsys.disabled():
        print(
            f"\nturn-set recall (gate >= {RECALL_FLOOR}): dev {recall(turn_hits['dev']):.4f}"
            f" test {recall(turn_hits['test']):.4f} overall {overall:.4f}"
        )
        for miss in turn_misses:
            print("  turn miss", *miss)
        print(
            f"per-mention C@{CANDIDATES_K} (not gated): dev"
            f" {aggregate(scores['dev']).c_at_10:.4f}"
            f" test {aggregate(scores['test']).c_at_10:.4f} overall {c_at_10:.4f}"
        )
        for miss in mention_misses:
            print("  mention miss", *miss)
    assert overall >= RECALL_FLOOR
