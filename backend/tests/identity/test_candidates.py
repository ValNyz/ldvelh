"""Candidate blocking of the resolver v2 (#154, spec §4.5.2): six SQL generators, no type
excluded, no secret alias without an open disclosure, thresholds from IdentityConfig, and
turn-set recall >= 0.98 on the gold corpus (dev + test; per-mention C@10 printed)."""

import random
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
from repos import entities, messages
from domain.identity import MentionRow
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


async def test_a_never_mentioned_entity_has_no_last_seen_turn(test_pool, game, service):
    async with test_pool.acquire() as conn:
        seen = await _create(conn, service, "character", "Tesk Vahrun")
        unseen = await _create(conn, service, "character", "Mira Sol")
        conversation = await messages.insert_conversation(conn, game, 1)
        for turn in (1, 2):
            message = await messages.insert_message(
                conn, game, conversation, "assistant", "Tesk Vahrun attend.", turn
            )
        await entities.insert_mentions(
            conn, game, message, None, [MentionRow(0, 11, "Tesk Vahrun", seen, "match")]
        )
        cards = {
            c.entity_id: c
            for c in await entities.candidate_cards(conn, game, [seen, unseen])
        }
    assert cards[seen].last_seen_turn == 2
    assert cards[unseen].last_seen_turn is None


async def test_a_secret_name_makes_no_homonym(test_pool, game, service):
    """A present entity whose secret true name is another character's label does not pull
    that character into the context: it would hint at the secret."""
    async with test_pool.acquire() as conn:
        elder = await _create(
            conn,
            service,
            "character",
            "La Kethari âgée",
            "descriptor",
            aliases=[AliasSpec("Nahle Irun", "true_name", False, secret=True)],
        )
        namesake = await _create(conn, service, "character", "Nahle Irun")
        quay = await _create(conn, service, "location", "Corbeau")
        gang = await _create(conn, service, "organization", "Corbeau")
        scene = await _scene(conn, game, present_ids=[elder, quay])
        found = await _block(conn, service, "Personne ne parle.", scene)
    sources = {c.entity_id: c.sources for c in found.context}
    assert namesake not in sources
    assert candidates.CONTEXT.homonym in sources[gang]


async def test_trigram_generator_reads_the_game_trigram_index(
    test_pool, test_user, game, service
):
    """Production shape: a game of a thousand named places among twenty other games. The
    planner looks the words of a narration up in the (game_id, alias_norm) GIN index,
    never comparing every alias of the game with every word."""
    syllables = ["ka", "lo", "mi", "ra", "ten", "vor", "sel", "du", "bri", "an", "zel"]
    draw = random.Random(7)

    def names(seed: int, count: int) -> list[str]:
        return [
            " ".join(
                "".join(draw.choice(syllables) for _ in range(3)).capitalize()
                for _ in range(2)
            )
            + f" {seed}-{n}"
            for n in range(count)
        ]

    places = names(0, 1000)
    words = sorted({name.split()[0].lower() for name in places[:50]})
    async with test_pool.acquire() as conn:
        insert = "INSERT INTO locations (game_id, name) SELECT $1, unnest($2::text[])"
        await conn.execute(insert, game, places)
        for seed in range(1, 21):
            other = await conn.fetchval(
                "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
                test_user["id"],
            )
            await conn.execute(insert, other, names(seed, 300))
        # What autovacuum keeps up to date in a live database: the GIN statistics too.
        await conn.execute("VACUUM ANALYZE entity_aliases")
        async with conn.transaction():
            await entities.set_trgm_threshold(conn, service.config)
            plan = await conn.fetch(
                "EXPLAIN " + entities.CANDIDATES_TRGM_SQL,
                game,
                [],
                words,
                service.config.rich_min_chars,
                service.config.s_sim,
            )
    text = "\n".join(r[0] for r in plan)
    near = text[text.index("CTE near") : text.index("CTE Scan on near")]
    assert "Bitmap Index Scan on idx_entity_aliases_game_norm_trgm" in near, text


async def test_trigram_threshold_does_not_outlive_the_query(test_pool, game, service):
    async with test_pool.acquire() as conn:
        await _create(conn, service, "character", "Pater Ondrev Kasso")
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('pg_trgm.word_similarity_threshold', '0.9', true)"
            )
            found = await entities.candidates_trgm(
                conn, game, ["ondrav"], service.config, disclosed=[]
            )
            after = await conn.fetchval("SHOW pg_trgm.word_similarity_threshold")
    assert found
    assert after == "0.9"


async def test_a_fuzzy_multi_word_name_stays_within_the_cap(test_pool, game, service):
    """Both words misspelled: the coverage of the two words adds up, so the name outranks
    aliases one of its words covers better on its own (scored by its best word alone, it
    would fall behind them, out of the cap). Labels only, no derived short alias."""
    async with test_pool.acquire() as conn:
        insert = "INSERT INTO locations (game_id, name) VALUES ($1, $2) RETURNING id"
        target = await conn.fetchval(insert, game, "Halle Marbrière")
        for n in range(1, 9):
            await conn.fetchval(insert, game, f"Halle {n}")
        scene = await _scene(conn, game)
        capped = IdentityConfig(max_candidates=3)
        found = await _block(
            conn, service, "Tu entres sous les halles marbrieres.", scene, config=capped
        )
    assert found.turn[0].entity_id == target
    assert candidates.TRGM in found.turn[0].sources


async def test_two_inflections_of_one_word_credit_it_once(test_pool, game, service):
    """« halle » and « halles » both match the word « halle » of « Halle Nord »: it is
    credited once, so the partial name stays below an exact match."""
    async with test_pool.acquire() as conn:
        north = await conn.fetchval(
            "INSERT INTO locations (game_id, name) VALUES ($1, 'Halle Nord') RETURNING id",
            game,
        )
        scores = dict(
            await entities.candidates_trgm(
                conn, game, ["halle", "halles"], service.config, disclosed=[]
            )
        )
        exact = dict(
            await entities.candidates_trgm(
                conn, game, ["halle", "nord"], service.config, disclosed=[]
            )
        )
    assert 0 < scores[north] < 1
    assert exact[north] == pytest.approx(1)


async def test_a_secret_name_of_another_entity_makes_no_homonym(
    test_pool, game, service
):
    """The mirror case: a present entity whose public label is another entity's secret
    true name does not pull that entity in either."""
    async with test_pool.acquire() as conn:
        hidden = await _create(
            conn,
            service,
            "character",
            "La Kethari âgée",
            "descriptor",
            aliases=[AliasSpec("Nahle Irun", "true_name", False, secret=True)],
        )
        place = await _create(conn, service, "location", "Nahle Irun")
        scene = await _scene(conn, game, present_ids=[place])
        found = await _block(conn, service, "Personne ne parle.", scene)
    assert hidden not in {c.entity_id for c in found.context}


async def test_card_turn_follows_a_merge_chain(test_pool, game, service):
    async with test_pool.acquire() as conn:
        keep = await _create(conn, service, "character", "Tesk Vahrun")
        middle = await _create(conn, service, "character", "Mira Sol")
        last = await _create(conn, service, "character", "Odon Lebrac")
        conversation = await messages.insert_conversation(conn, game, 1)
        mentioned = {1: keep, 2: last}  # turn 3: nobody; `middle` is never mentioned
        for turn in (1, 2, 3):
            message = await messages.insert_message(
                conn, game, conversation, "assistant", "Quelqu'un attend.", turn
            )
            if turn in mentioned:
                await entities.insert_mentions(
                    conn,
                    game,
                    message,
                    None,
                    [MentionRow(0, 4, "Quel", mentioned[turn], "match")],
                )
        await entities.merge_entities(conn, middle, last, "test", None)
        await entities.merge_entities(conn, keep, middle, "test", None)
        [card] = await entities.candidate_cards(conn, game, [keep])
    assert card.last_seen_turn == 2  # the turn of the mention of the entity merged last


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


def _print_misses(label: str, misses: list[tuple]) -> None:
    """Every dev miss in detail; for the frozen test split, counts by category only."""
    for miss in misses:
        if miss[0] == "dev":
            print(f"  {label}", *miss)
    test = Counter(miss[2] for miss in misses if miss[0] == "test")
    print(f"  {label} test by category: {dict(sorted(test.items()))}")


def _accepted_ids(mention) -> set[str]:
    forms = [mention.parsed, *(parse_expected(a) for a in mention.accept_also)]
    return {f.entity_id for f in forms if f.decision in LINKS}


async def test_blocking_recall_of_the_turn_set_on_the_whole_corpus(
    test_pool, test_user, capsys
):
    """Gate (spec §4.5.2, ruling R24): the gold id of every existing gold mention of dev +
    test is in its scene's CandidateSet (turn and context), at least 98 times in 100. The
    per-mention C@10 of the scorer is printed alongside, not gated. Misses are printed in
    detail for dev only; the frozen test split shows counts by category, never details."""
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
        _print_misses("turn miss", turn_misses)
        print(
            f"per-mention C@{CANDIDATES_K} (not gated): dev"
            f" {aggregate(scores['dev']).c_at_10:.4f}"
            f" test {aggregate(scores['test']).c_at_10:.4f} overall {c_at_10:.4f}"
        )
        _print_misses("mention miss", mention_misses)
    assert overall >= RECALL_FLOOR
