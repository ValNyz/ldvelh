"""Listwise identity decision of the resolver v2 (#154, spec §4.5.3-§4.5.5): the prompt
rendered from the packs, the output schema, the code verifications, the deterministic
prepass and the Haiku -> Sonnet cascade with its fallback."""

import json
from dataclasses import replace
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml

from config import IdentityConfig
from domain.identity import (
    Candidate,
    CandidateAlias,
    CandidateSet,
    SceneContext,
    TurnDecisions,
)
from llm.session import LLMSession
from packs.loader import (
    PACKS_DIR,
    GenrePack,
    LangPack,
    available_genres,
    available_langs,
    load_genre,
    load_lang,
)
from prompts.identity_prompt import (
    IDENTITY_PROMPT_MARKER,
    build_identity_system_prompt,
    build_identity_user_prompt,
    decision_schema,
    render_card,
)
from services.identity import decision
from services.identity.decision import MentionDecision
from services.identity.lexicon import Lexicon, for_game
from repos import entities
from services.identity.mentions import mention_rows
from services.identity.normalize import Normalizer
from services.identity.service import IdentityService
from services.llm_providers import StructuredOutputMode
from tests.characterization.scripted_llm import ScriptedLLMProvider, classify_call

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity"
CONFIG = IdentityConfig()
NORMALIZER = Normalizer(load_lang("fr"), CONFIG)
PROTAGONIST = uuid4()


def _alias(text: str, kind: str = "label", known: bool = True) -> CandidateAlias:
    return CandidateAlias(text, NORMALIZER.norm(text), kind, known, False)


def _candidate(
    handle: int,
    label: str,
    entity_type: str = "character",
    *,
    aliases: list[CandidateAlias] | None = None,
    sources: set[str] | None = None,
) -> Candidate:
    return Candidate(
        entity_id=uuid4(),
        handle=handle,
        entity_type=entity_type,
        label=label,
        aliases=aliases if aliases is not None else [_alias(label)],
        occupation=None,
        usual_location=None,
        last_seen_turn=None,
        description_line=None,
        score=1,
        sources=sources or {"exact"},
    )


def _set(*candidates: Candidate, exact: dict | None = None) -> CandidateSet:
    return CandidateSet(turn=list(candidates), context=[], exact=exact or {})


def _scene(present: list[UUID] | None = None) -> SceneContext:
    return SceneContext(
        location_id=None,
        present_ids=present or [],
        recent_message_ids=[],
        reveal_refs=[],
        planned_npc_handles=[],
        open_disclosure_ids=[],
        protagonist_id=PROTAGONIST,
        companion_id=None,
        genre=None,
    )


def _d(
    surface: str, verdict: str, handle: str | None = None, **fields
) -> MentionDecision:
    return MentionDecision(surface=surface, decision=verdict, handle=handle, **fields)


def _verify(decisions, candidates, text, scene=None, **kwargs):
    return decision.verify(
        decisions,
        candidates,
        text,
        scene or _scene(),
        normalizer=NORMALIZER,
        config=CONFIG,
        **kwargs,
    )


# --- schema --------------------------------------------------------------------------


def test_schema_enumerates_candidate_handles_only():
    schema = decision_schema(["E3", "E17"])
    item = schema["properties"]["mentions"]["items"]
    assert item["properties"]["handle"]["enum"] == ["E3", "E17", None]
    assert item["properties"]["decision"]["enum"] == [
        "MATCH",
        "ALIAS",
        "NEW",
        "UNSURE",
        "SKIP",
    ]
    assert {"surface", "before", "decision", "handle", "evidence"} <= set(
        item["required"]
    )
    assert "confidence" not in item["properties"]
    assert "category" not in item["properties"]  # ruling R40
    for field in ("alias_kind", "new_type", "new_kind", "talks_to"):
        assert field in item["properties"]


# --- verifications (§4.5.4) ----------------------------------------------------------


def test_unknown_handle_is_downgraded_to_unsure_with_an_event():
    known = _candidate(3, "Odran Keswil")
    text = "Odran Keswil entre."
    [out] = _verify([_d("Odran Keswil", "MATCH", "E99")], _set(known), text)
    assert out.decision == "UNSURE"
    assert out.entity_id is None and out.handle is None
    assert out.rejection == "unknown_id_downgraded"
    assert not out.verified
    [ok] = _verify([_d("Odran Keswil", "MATCH", "E3")], _set(known), text)
    assert ok.verified and ok.entity_id == known.entity_id


def test_surface_absent_from_text_is_ignored():
    known = _candidate(3, "Odran Keswil")
    text = "Odrana Keswil sourit ; ÉLOÏSE attend."
    absent, accented = _verify(
        [
            _d("Odran", "MATCH", "E3"),
            _d("eloise", "NEW", new_type="character", new_kind="proper_name"),
        ],
        _set(known),
        text,
    )
    assert absent.ignored and absent.rejection == "surface_absent"
    assert not absent.verified
    # Whole word, case and accents aside.
    assert not accented.ignored and accented.verified


def test_two_mentions_talking_to_each_other_cannot_share_an_id():
    guard = _candidate(4, "garde", aliases=[_alias("garde", "descriptor")])
    text = "Le garde parle au vieux garde de la porte."
    first, second = _verify(
        [
            _d("Le garde", "MATCH", "E4", talks_to=("vieux garde",)),
            _d("vieux garde", "MATCH", "E4"),
        ],
        _set(guard),
        text,
    )
    assert first.decision == second.decision == "UNSURE"
    assert first.rejection == second.rejection == "talks_to_same_id"
    assert first.entity_id is None and second.entity_id is None


def test_duplicate_news_of_same_type_and_norm_collapse():
    text = "Une marchande arrive. La marchande sourit."
    news = _verify(
        [
            _d("Une marchande", "NEW", new_type="character", new_kind="descriptor"),
            _d("La marchande", "NEW", new_type="character", new_kind="descriptor"),
        ],
        _set(),
        text,
    )
    primaries = [d for d in news if d.decision == "NEW" and d.same_as is None]
    assert len(primaries) == 1
    assert news[1].same_as == 0


def test_alias_true_name_requires_presence():
    absent = _candidate(5, "la femme au manteau", sources={"trgm"})
    present = _candidate(6, "le vieil homme", sources={"present"})
    text = "« Je suis Odran Keswil », dit-il."
    [refused] = _verify(
        [_d("Odran Keswil", "ALIAS", "E5", alias_kind="true_name")],
        _set(absent, present),
        text,
    )
    assert refused.decision == "UNSURE"
    assert refused.rejection == "true_name_not_present"
    [accepted] = _verify(
        [_d("Odran Keswil", "ALIAS", "E6", alias_kind="true_name")],
        _set(absent, present),
        text,
    )
    assert accepted.verified and accepted.entity_id == present.entity_id
    # Present in the scene by id, whatever the generators said.
    [by_scene] = _verify(
        [_d("Odran Keswil", "ALIAS", "E5", alias_kind="true_name")],
        _set(absent, present),
        text,
        _scene(present=[absent.entity_id]),
    )
    assert by_scene.verified


def test_near_duplicate_new_is_flagged_not_merged():
    keswil = _candidate(
        7, "Odran Keswil", aliases=[_alias("Odran Keswil", "true_name")]
    )
    place = _candidate(8, "Keswil", "location")
    text = "Keswil arrive au quai."
    [new] = _verify(
        [_d("Keswil", "NEW", new_type="character", new_kind="proper_name")],
        _set(keswil, place),
        text,
    )
    assert new.decision == "NEW" and new.verified
    assert new.entity_id is None
    assert new.probable_duplicate == keswil.entity_id


def test_match_to_a_tombstone_is_redirected():
    old = _candidate(9, "Odran Keswil")
    live = uuid4()
    [out] = _verify(
        [_d("Odran Keswil", "MATCH", "E9")],
        _set(old),
        "Odran Keswil entre.",
        redirects={old.entity_id: live},
    )
    assert out.entity_id == live and out.redirected_from == old.entity_id
    assert out.verified


def _events(decisions) -> list:
    return TurnDecisions(decisions, escalated=False, fallback=False, usage={}).events()


def test_rejection_events_keep_what_was_rejected():
    known = _candidate(3, "Odran Keswil")
    guard = _candidate(4, "garde", aliases=[_alias("garde", "descriptor")])
    absent = _candidate(5, "la femme au manteau", sources={"trgm"})
    text = "Odran Keswil voit le garde parler au vieux garde. « Je suis Vela Sorn », dit-on."
    decided = _verify(
        [
            _d("Odran Keswil", "MATCH", "E99"),
            _d("Odran", "MATCH", "E3"),
            _d("le garde", "MATCH", "E4", talks_to=("vieux garde",)),
            _d("vieux garde", "MATCH", "E4"),
            _d("Vela Sorn", "ALIAS", "E5", alias_kind="true_name"),
        ],
        _set(known, guard, absent),
        text,
    )
    unsure = {"decision": "UNSURE", "handle": None}
    assert _events(decided) == [
        ("unknown_id_downgraded", None, {**unsure, "rejected_handle": "E99"}),
        ("talks_to_same_id", guard.entity_id, {**unsure, "rejected_handle": "E4"}),
        ("talks_to_same_id", guard.entity_id, {**unsure, "rejected_handle": "E4"}),
        (
            "true_name_not_present",
            absent.entity_id,
            {**unsure, "rejected_handle": "E5"},
        ),
    ]
    # « Odran » is in « Odran Keswil »: not absent. An absent surface keeps its handle.
    [ignored] = _verify([_d("Keswila", "MATCH", "E3")], _set(known), text)
    assert _events([ignored]) == [
        (
            "surface_absent",
            None,
            {"decision": "MATCH", "handle": "E3", "rejected_handle": "E3"},
        )
    ]


def test_flag_and_redirect_events():
    keswil = _candidate(7, "Odran Keswil")
    old = _candidate(9, "Mira Tassel")
    live = uuid4()
    decided = _verify(
        [
            _d("Keswil", "NEW", new_type="character", new_kind="proper_name"),
            _d("Mira Tassel", "MATCH", "E9"),
        ],
        _set(keswil, old),
        "Keswil croise Mira Tassel.",
        redirects={old.entity_id: live},
    )
    assert _events(decided) == [
        ("probable_duplicate", keswil.entity_id, {"new_type": "character"}),
        ("tombstone_redirected", live, {"from": str(old.entity_id)}),
    ]


def test_two_news_talking_to_each_other_stay_two():
    text = "Un garde parle à un garde."
    first, second = _verify(
        [
            _d(
                "Un garde",
                "NEW",
                new_type="character",
                new_kind="descriptor",
                talks_to=("un garde",),
            ),
            _d("un garde", "NEW", new_type="character", new_kind="descriptor"),
        ],
        _set(),
        text,
    )
    assert first.same_as is None and second.same_as is None


# --- prepass (§4.5.5 step 1) ---------------------------------------------------------


def test_prepass_resolves_unique_exact_matches_without_llm():
    keswil = _candidate(3, "Odran Keswil")
    quay = _candidate(4, "Quai 9", "location")
    candidates = _set(keswil, quay, exact={"odran keswil": keswil, "quai 9": quay})
    text = "Odran Keswil attend au Quai n°9 ; plus tard, odran keswil repart."
    found = decision.prepass(text, candidates, normalizer=NORMALIZER, config=CONFIG)
    assert [(d.surface, d.entity_id) for d in found] == [
        ("Odran Keswil", keswil.entity_id),
        ("Quai n°9", quay.entity_id),
        ("odran keswil", keswil.entity_id),
    ]
    assert all(d.deterministic and d.verified and d.decision == "MATCH" for d in found)
    assert found[0].handle == "E3"


def test_prepass_reveals_an_exact_name_the_pc_does_not_know():
    """An unknown true name read exactly is revealed (ALIAS true_name, deterministic, the
    stored name to reveal), a later short form of it is an ALIAS short, a known name a
    MATCH, and an unknown short form of no unknown name a plain MATCH."""
    vela = _candidate(
        4,
        "la femme au manteau",
        aliases=[
            _alias("Vela Sorn", "true_name", known=False),
            _alias("Sorn", "short", known=False),
        ],
    )
    blade = _candidate(
        5,
        "la lame sans garde",
        "object",
        aliases=[_alias("lame", "short", known=False)],
    )
    keswil = _candidate(3, "Odran Keswil")
    exact = {
        NORMALIZER.norm(form): c
        for form, c in (("Vela Sorn", vela), ("Sorn", vela), ("lame", blade),
                        ("Odran Keswil", keswil))
    }  # fmt: skip
    text = "Odran Keswil salue Vela Sorn. Plus tard, Sorn pose sa lame."
    found = decision.prepass(
        text,
        _set(vela, blade, keswil, exact=exact),
        normalizer=NORMALIZER,
        config=CONFIG,
    )
    by_surface = {d.surface: d for d in found}
    assert by_surface["Odran Keswil"].decision == "MATCH"
    first = by_surface["Vela Sorn"]
    assert (first.decision, first.alias_kind, first.revealed_name) == (
        "ALIAS",
        "true_name",
        "Vela Sorn",
    )
    later = by_surface["Sorn"]
    assert (later.decision, later.alias_kind, later.revealed_name) == (
        "ALIAS",
        "short",
        "Vela Sorn",
    )
    # A short form stored in lower case is a common word: left to the model.
    assert "sa lame" not in by_surface
    assert all(d.deterministic for d in found)
    # Out of the scene, an exact stored name still designates its entity.
    checked = _verify(found, _set(vela, blade, keswil, exact=exact), text)
    assert {d.surface: d.decision for d in checked}["Vela Sorn"] == "ALIAS"
    # The first mention of an unknown short form reveals the name that holds it.
    [only] = decision.prepass(
        "Sorn attend.", _set(vela, exact=exact), normalizer=NORMALIZER, config=CONFIG
    )
    assert (only.alias_kind, only.revealed_name) == ("true_name", "Vela Sorn")


def test_prepass_leaves_a_name_the_text_continues_or_announces_as_another():
    guild = _candidate(6, "Guilde des Pilotes", "organization",
                       aliases=[_alias("Guilde", "short")])  # fmt: skip
    quay = _candidate(7, "Quai 6", "location", aliases=[_alias("Quai", "short")])
    voss = _candidate(8, "Rizka Voss", aliases=[_alias("Voss", "short")])
    key = _candidate(9, "la clé d'os", "object",
                     aliases=[_alias("la clé d'os", "descriptor")])  # fmt: skip
    exact = {
        NORMALIZER.norm(form): c
        for form, c in (("Guilde", guild), ("Quai", quay), ("Voss", voss),
                        ("la clé d'os", key))
    }  # fmt: skip
    candidates = _set(guild, quay, voss, key, exact=exact)
    text = (
        "Elle rejoint la Guilde des Convoyeurs au Quai 9, puis parle avec Elara Voss. "
        "On lui tend une seconde clé d'os."
    )
    found = decision.prepass(text, candidates, normalizer=NORMALIZER, config=CONFIG)
    assert found == []
    plain = "La Guilde attend au Quai. Voss sourit. La clé d'os brille."
    found = decision.prepass(plain, candidates, normalizer=NORMALIZER, config=CONFIG)
    assert [d.entity_id for d in found] == [
        guild.entity_id,
        quay.entity_id,
        voss.entity_id,
        key.entity_id,
    ]


def test_prepass_leaves_a_short_form_written_as_a_common_noun():
    case = _candidate(6, "Valise souple", "object", aliases=[_alias("Valise", "short")])
    house = _candidate(
        7,
        "Maison Ardoise",
        "organization",
        aliases=[
            _alias("Maison Ardoise", known=False),
            _alias("Maison", "short", known=False),
        ],
    )
    exact = {NORMALIZER.norm(f): c for f, c in (("Valise", case), ("Maison", house))}
    candidates = _set(case, house, exact=exact)
    text = "Il pose sa valise devant la maison de commerce."
    assert (
        decision.prepass(text, candidates, normalizer=NORMALIZER, config=CONFIG) == []
    )
    named = "Il pose la Valise. La Maison paiera."
    found = decision.prepass(named, candidates, normalizer=NORMALIZER, config=CONFIG)
    assert [(d.entity_id, d.decision) for d in found] == [
        (case.entity_id, "MATCH"),
        (house.entity_id, "ALIAS"),
    ]


def test_without_case_marking_names_a_short_form_never_links_alone():
    caseless = Normalizer(
        load_lang("fr").model_copy(update={"case_marks_names": False}), CONFIG
    )
    case = _candidate(6, "Valise souple", "object", aliases=[_alias("Valise", "short")])
    keswil = _candidate(3, "Odran Keswil")
    exact = {
        caseless.norm(f): c for f, c in (("Valise", case), ("Odran Keswil", keswil))
    }
    text = (
        "Odran Keswil pose la Valise. Il ouvre la Valise souple, puis le Keswil Bleu."
    )
    found = decision.prepass(
        text, _set(case, keswil, exact=exact), normalizer=caseless, config=CONFIG
    )
    # Names of the other kinds still link, and no capital is read as a continuation.
    assert [d.surface for d in found] == ["Odran Keswil"]
    assert load_lang("fr").case_marks_names and load_lang("en").case_marks_names


async def test_a_short_form_left_by_the_prepass_is_asked_under_to_check():
    case = _candidate(6, "Valise souple", "object", aliases=[_alias("Valise", "short")])
    exact = {NORMALIZER.norm("Valise"): case}
    text = "Il pose sa valise."
    found, doubts = decision.scan(
        text, _set(case, exact=exact), normalizer=NORMALIZER, config=CONFIG
    )
    assert found == [] and [(d.surface, d.handle) for d in doubts] == [
        ("sa valise", "E6")
    ]
    seen = []

    def first(prompt):
        seen.append(prompt)
        return {"mentions": [_mention("sa valise", "MATCH", "E6")]}

    turn, _ = await _decide({"identity": [first]}, _set(case, exact=exact), text)
    assert '## TO CHECK\n"sa valise" (after "Il pose"): E6?' in seen[0]
    assert [d.entity_id for d in turn.decisions] == [case.entity_id]


def test_to_check_quotes_the_text_as_written():
    voss = _candidate(
        3, "Atelier Voss", "location", aliases=[_alias("Coupleur", "short")]
    )
    exact = {NORMALIZER.norm("Coupleur"): voss}
    text = "Un apprenti passe par l'atelier.\n\n— Voss, le coupleur, il est prêt."
    _, [doubt] = decision.scan(
        text, _set(voss, exact=exact), normalizer=NORMALIZER, config=CONFIG
    )
    assert (doubt.surface, doubt.before) == ("le coupleur", "l'atelier. — Voss,")


def test_a_card_names_the_candidates_sharing_its_name_and_their_type():
    place = _candidate(3, "Méridienne", "location")
    ship = _candidate(4, "Méridienne", "object")
    card = render_card(
        place, protagonist=False, companion=False, homonyms=[("E4", "object")]
    )
    assert "same name as E4 (object)" in card
    street = _candidate(5, "Rue Haute", "location")
    assert decision._homonyms([place, ship, street], NORMALIZER) == {
        place.entity_id: [("E4", "object")],
        ship.entity_id: [("E3", "location")],
        street.entity_id: [],
    }


def test_a_lower_case_short_form_never_links_alone_whatever_starts_the_sentence():
    licence = _candidate(
        6, "Licence de pilote", "object", aliases=[_alias("pilote", "short")]
    )
    exact = {NORMALIZER.norm("pilote"): licence}
    found, doubts = decision.scan(
        "Un pilote balafré entre.",
        _set(licence, exact=exact),
        normalizer=NORMALIZER,
        config=CONFIG,
    )
    assert found == [] and [d.surface for d in doubts] == ["Un pilote"]


def test_a_prepass_decision_keeps_to_the_form_it_decided():
    street = _candidate(3, "Rue des Lampions", "location")
    named = MentionDecision(
        surface="les Lampions",
        decision="MATCH",
        entity_id=street.entity_id,
        deterministic=True,
    )
    text = "Les lampions grésillent ; la Brigade patrouille sur les Lampions."
    rows = mention_rows(text, [(named, street.entity_id)], NORMALIZER)
    assert [r.surface for r in rows] == ["les Lampions"]
    model = replace(named, deterministic=False)
    rows = mention_rows(text, [(model, street.entity_id)], NORMALIZER)
    assert [r.surface for r in rows] == ["Les lampions", "les Lampions"]


def test_a_surface_that_repeats_its_context_keeps_only_the_mention():
    voss = _candidate(4, "Rizka Voss", aliases=[_alias("Voss", "short")])
    text = "Si tu cherches Voss, va au sas."
    d = _d("Si tu cherches Voss", "MATCH", "E4", before="Si tu cherches")
    [checked] = _verify([d], _set(voss), text)
    assert (checked.surface, checked.entity_id) == ("Voss", voss.entity_id)
    plain = _d("Voss", "MATCH", "E4", before="Si tu cherches")
    assert _verify([plain], _set(voss), text)[0].surface == "Voss"


def test_a_homonym_link_is_not_a_merge_and_an_abstention_shows_every_card():
    shop = _candidate(
        3, "Échoppe d'Olbert", "location", aliases=[_alias("Olbert", "short")]
    )
    olbert = _candidate(4, "Maître Olbert", aliases=[_alias("Olbert", "short")])
    other = _candidate(5, "Mira Tassel")
    held = _d("Olbert", "MATCH", "E4", entity_id=olbert.entity_id)
    assert not decision._names_another(held, [shop, olbert, other], NORMALIZER)
    lacking = _d("Mira Tassel", "MATCH", "E4", entity_id=olbert.entity_id)
    assert decision._names_another(lacking, [shop, olbert, other], NORMALIZER)


async def test_the_strong_model_sees_every_candidate_for_an_abstention():
    keswil = _candidate(3, "Odran Keswil")
    far = _candidate(9, "le recruteur borgne", "character",
                     aliases=[_alias("le recruteur borgne", "descriptor")])  # fmt: skip
    text = "Le recruteur hoche la tête."
    first = {"mentions": [_mention("Le recruteur", "UNSURE")]}
    strong = {"mentions": [_mention("Le recruteur", "MATCH", "E9")]}
    turn, provider = await _decide(
        {"identity": [first], "identity_strong": [strong]}, _set(keswil, far), text
    )
    assert provider.purposes() == ["identity", "identity_strong"]
    [d] = turn.decisions
    assert (d.decision, d.entity_id, d.escalated) == ("MATCH", far.entity_id, True)


# --- parsing -------------------------------------------------------------------------


def test_text_mode_parses_json_from_prose():
    raw = (
        "Here are my decisions.\n"
        + json.dumps(
            {
                "mentions": [
                    {
                        "surface": "Odran",
                        "before": "",
                        "decision": "MATCH",
                        "handle": "E3",
                        "evidence": " ".join(["word"] * 40),
                    }
                ]
            }
        )
        + "\nThat is all."
    )
    [out] = decision.parse(raw, StructuredOutputMode.TEXT, config=CONFIG)
    # A stray list before the real object is skipped.
    [again] = decision.parse(
        'Candidates ["E3"] considered. ' + raw, StructuredOutputMode.TEXT, config=CONFIG
    )
    assert again.handle == "E3"
    assert (out.surface, out.decision, out.handle) == ("Odran", "MATCH", "E3")
    assert len(out.evidence.split()) == CONFIG.evidence_max_words
    with pytest.raises(decision.DecisionOutputInvalid):
        decision.parse("no json here", StructuredOutputMode.TEXT, config=CONFIG)
    with pytest.raises(decision.DecisionOutputInvalid):
        decision.parse(
            {"mentions": [{"surface": "x", "decision": "MAYBE"}]},
            StructuredOutputMode.TOOL_USE,
            config=CONFIG,
        )


# --- cascade (§4.5.5) ----------------------------------------------------------------


class _Conn:
    """follow_merges reads `redirects` (tombstone -> live); none by default."""

    def __init__(self, redirects: dict | None = None):
        self.redirects = redirects or {}

    async def fetch(self, sql, ids):
        return [{"id": i, "live": self.redirects.get(i, i)} for i in ids]


def _mention(surface, verdict, handle=None, **fields):
    return {
        "surface": surface,
        "before": "",
        "decision": verdict,
        "handle": handle,
        "evidence": "",
        **fields,
    }


async def _decide(
    responses: dict,
    candidates: CandidateSet,
    text: str,
    scene=None,
    *,
    mode: StructuredOutputMode = StructuredOutputMode.TOOL_USE,
    fail_on: dict | None = None,
    redirects: dict | None = None,
):
    provider = ScriptedLLMProvider(responses, mode=mode)
    provider.fail_on.update(fail_on or {})
    session = LLMSession.from_provider(provider)
    turn = await decision.decide_turn(
        session,
        _Conn(redirects),
        text,
        candidates,
        scene or _scene(),
        thresholds=CONFIG,
        normalizer=NORMALIZER,
        lexicon=for_game("fr", None),
    )
    return turn, provider


async def test_cascade_escalates_only_unsure_true_name_and_merges_once():
    keswil = _candidate(3, "Odran Keswil")
    stranger = _candidate(4, "la femme au manteau", sources={"present"})
    guard = _candidate(5, "le garde", aliases=[_alias("le garde", "descriptor")])
    tassel = _candidate(6, "Mira Tassel")
    # « Mira Tassel » is no unique exact form here (the prepass leaves it to the model).
    candidates = _set(keswil, stranger, guard, tassel, exact={"odran keswil": keswil})
    text = (
        "Odran Keswil salue le garde. « Je suis Vela Sorn », dit la femme au manteau. "
        "Un passant regarde Mira Tassel."
    )
    first = {
        "mentions": [
            _mention("le garde", "MATCH", "E5"),
            _mention("Vela Sorn", "ALIAS", "E4", alias_kind="true_name"),
            _mention("Un passant", "UNSURE"),
            # Would merge: « Mira Tassel » is a name of E6, not of E3.
            _mention("Mira Tassel", "MATCH", "E3"),
        ]
    }
    strong = {
        "mentions": [
            _mention("Vela Sorn", "ALIAS", "E4", alias_kind="true_name"),
            _mention("Un passant", "SKIP"),
            _mention("Mira Tassel", "MATCH", "E6"),
            # Not escalated: ignored.
            _mention("le garde", "SKIP"),
        ]
    }
    turn, provider = await _decide(
        {"identity": [first], "identity_strong": [strong]}, candidates, text
    )
    assert provider.purposes().count("identity") == 1
    assert provider.purposes().count("identity_strong") == 1
    assert turn.escalated and not turn.fallback
    by_surface = {d.surface: d for d in turn.decisions}
    assert by_surface["Odran Keswil"].deterministic
    assert by_surface["le garde"].decision == "MATCH"
    assert not by_surface["le garde"].escalated
    assert by_surface["Vela Sorn"].escalated and by_surface["Vela Sorn"].verified
    assert by_surface["Un passant"].decision == "SKIP"
    assert by_surface["Mira Tassel"].entity_id == tassel.entity_id
    assert set(turn.usage) == {"identity", "identity_strong"}
    assert turn.usage["identity"]["calls"] == 1

    # Nothing to escalate: one call only.
    calm = {"mentions": [_mention("le garde", "MATCH", "E5")]}
    turn, provider = await _decide({"identity": [calm]}, candidates, text)
    assert provider.purposes() == ["identity"]
    assert not turn.escalated


async def test_without_escalation_the_small_model_decisions_stand():
    stranger = _candidate(4, "la femme au manteau", sources={"present"})
    text = "« Je suis Vela Sorn », dit la femme au manteau. Un passant regarde."
    first = {
        "mentions": [
            _mention("Vela Sorn", "ALIAS", "E4", alias_kind="true_name"),
            _mention("Un passant", "UNSURE"),
        ]
    }
    provider = ScriptedLLMProvider({"identity": [first]})
    turn = await decision.decide_turn(
        LLMSession.from_provider(provider),
        _Conn(),
        text,
        _set(stranger),
        _scene(),
        thresholds=CONFIG.model_copy(update={"escalation": False}),
        normalizer=NORMALIZER,
        lexicon=for_game("fr", None),
    )
    assert provider.purposes() == ["identity"]
    assert not turn.escalated and set(turn.usage) == {"identity"}
    by_surface = {d.surface: d for d in turn.decisions}
    assert by_surface["Vela Sorn"].decision == "ALIAS"
    assert by_surface["Un passant"].decision == "UNSURE"
    assert not any(d.escalated for d in turn.decisions)


async def test_the_prepass_wins_over_the_model_on_its_surfaces():
    keswil = _candidate(3, "Odran Keswil")
    tassel = _candidate(6, "Mira Tassel")
    candidates = _set(keswil, tassel, exact={"mira tassel": tassel})
    first = {"mentions": [_mention("Mira Tassel", "MATCH", "E3")]}
    turn, provider = await _decide(
        {"identity": [first]}, candidates, "Un homme regarde Mira Tassel."
    )
    assert provider.purposes() == ["identity"]
    [d] = turn.decisions
    assert d.deterministic and d.entity_id == tassel.entity_id


async def test_unconfirmed_escalation_never_guesses():
    stranger = _candidate(4, "la femme au manteau", sources={"present"})
    text = "« Je suis Vela Sorn », dit la femme au manteau."
    first = {"mentions": [_mention("Vela Sorn", "ALIAS", "E4", alias_kind="true_name")]}
    turn, provider = await _decide(
        {"identity": [first], "identity_strong": [{"nope": True}]}, _set(stranger), text
    )
    assert provider.purposes() == ["identity", "identity_strong"]
    [d] = turn.decisions
    assert d.decision == "UNSURE" and d.rejection == "escalation_unconfirmed"
    assert turn.escalated and not turn.fallback


async def test_two_invalid_json_fall_back_to_the_prepass():
    keswil = _candidate(3, "Odran Keswil")
    candidates = _set(keswil, exact={"odran keswil": keswil})
    text = "Odran Keswil salue le garde."
    turn, provider = await _decide(
        {"identity": [{"nope": True}, {"mentions": "nope"}]}, candidates, text
    )
    assert provider.purposes() == ["identity", "identity"]
    assert turn.fallback and not turn.escalated
    assert [(d.surface, d.deterministic) for d in turn.decisions] == [
        ("Odran Keswil", True)
    ]
    assert ("resolver_fallback", None, {"prepass": 1}) in turn.events()
    assert turn.usage["identity"]["calls"] == 2


async def test_the_fallback_still_follows_merges():
    keswil = _candidate(3, "Odran Keswil")
    live = uuid4()
    turn, _ = await _decide(
        {"identity": [{"nope": True}]},
        _set(keswil, exact={"odran keswil": keswil}),
        "Odran Keswil salue le garde.",
        redirects={keswil.entity_id: live},
    )
    assert turn.fallback
    [d] = turn.decisions
    assert d.entity_id == live and d.redirected_from == keswil.entity_id


async def test_a_failing_structured_call_is_retried_once_without_a_text_fallback():
    """§4.5.5: at most two IDENTITY calls and one IDENTITY_STRONG call per turn; the
    session's silent plain-text retry is off for them, and usage counts every call."""
    keswil = _candidate(3, "Odran Keswil")
    candidates = _set(keswil, exact={"odran keswil": keswil})
    text = "Odran Keswil salue le garde."
    turn, provider = await _decide(
        {}, candidates, text, fail_on={"identity": RuntimeError("down")}
    )
    assert provider.purposes() == ["identity", "identity"]
    assert [c.method for c in provider.calls] == ["complete_with_tools"] * 2
    assert turn.fallback and turn.usage["identity"]["calls"] == 2

    # A schema answer that does not parse: retried by the cascade, not as plain text.
    turn, provider = await _decide(
        {"identity": ["not json", "still not json"]},
        candidates,
        text,
        mode=StructuredOutputMode.JSON_SCHEMA,
    )
    assert provider.purposes() == ["identity", "identity"]
    assert [c.method for c in provider.calls] == ["complete_with_schema"] * 2
    assert turn.fallback and turn.usage["identity"]["calls"] == 2

    # The strong call fails: one call, no retry.
    stranger = _candidate(4, "la femme au manteau", sources={"present"})
    first = {"mentions": [_mention("Vela Sorn", "ALIAS", "E4", alias_kind="true_name")]}
    turn, provider = await _decide(
        {"identity": [first]},
        _set(stranger),
        "« Je suis Vela Sorn », dit la femme au manteau.",
        fail_on={"identity_strong": RuntimeError("down")},
    )
    assert provider.purposes() == ["identity", "identity_strong"]
    assert turn.usage["identity_strong"]["calls"] == 1
    assert turn.decisions[0].rejection == "escalation_unconfirmed"


async def test_a_retry_that_succeeds_applies_its_decisions():
    guard = _candidate(5, "le garde", aliases=[_alias("le garde", "descriptor")])
    valid = {"mentions": [_mention("le garde", "MATCH", "E5")]}
    turn, provider = await _decide(
        {"identity": [{"nope": True}, valid]}, _set(guard), "Le marin salue le garde."
    )
    assert provider.purposes() == ["identity", "identity"]
    assert not turn.fallback
    [d] = turn.decisions
    assert d.verified and d.entity_id == guard.entity_id


async def test_text_mode_decides_from_a_plain_completion():
    guard = _candidate(5, "le garde", aliases=[_alias("le garde", "descriptor")])
    valid = {"mentions": [_mention("le garde", "MATCH", "E5")]}
    turn, provider = await _decide(
        {"identity": ["Here it is: " + json.dumps(valid)]},
        _set(guard),
        "Le marin salue le garde.",
        mode=StructuredOutputMode.TEXT,
    )
    assert [(c.method, c.purpose) for c in provider.calls] == [("complete", "identity")]
    [d] = turn.decisions
    assert d.verified and d.entity_id == guard.entity_id


async def test_the_strong_model_links_only_the_candidates_it_was_shown():
    keswil = _candidate(3, "Odran Keswil", sources={"trgm"})
    stranger = _candidate(4, "la femme au manteau", sources={"present"})
    text = "« Je suis Vela Sorn », dit la femme au manteau."
    first = {"mentions": [_mention("Vela Sorn", "ALIAS", "E4", alias_kind="true_name")]}
    strong = {"mentions": [_mention("Vela Sorn", "MATCH", "E3")]}
    turn, _ = await _decide(
        {"identity": [first], "identity_strong": [strong]},
        _set(keswil, stranger),
        text,
    )
    [d] = turn.decisions
    assert d.decision == "UNSURE" and d.rejection == "unknown_id_downgraded"
    assert d.rejected_handle == "E3" and d.escalated


async def test_a_redirected_match_emits_its_event():
    old = _candidate(9, "Odran Keswil")
    guard = _candidate(5, "le garde", aliases=[_alias("le garde", "descriptor")])
    live = uuid4()
    first = {"mentions": [_mention("le garde", "MATCH", "E5")]}
    turn, _ = await _decide(
        {"identity": [first]},
        _set(old, guard, exact={"odran keswil": old}),
        "Odran Keswil salue le garde.",
        redirects={old.entity_id: live},
    )
    [d] = [d for d in turn.decisions if d.deterministic]
    assert d.entity_id == live
    assert ("tombstone_redirected", live, {"from": str(old.entity_id)}) in turn.events()


@pytest.mark.integration
async def test_follow_merges_redirects_a_tombstone_chain_to_the_live_entity(
    test_pool, test_user
):
    async with test_pool.acquire() as conn:
        game = await conn.fetchval(
            "INSERT INTO games (user_id, language) VALUES ($1, 'fr') RETURNING id",
            test_user["id"],
        )
        service = IdentityService(game, lang="fr", config=CONFIG)
        first, second, third = [
            await conn.fetchval(
                "INSERT INTO characters (game_id, true_name) VALUES ($1, $2) RETURNING id",
                game,
                name,
            )
            for name in ("Orin Kell", "Tesk Vahrun", "Ilsa Morn")
        ]
        assert (
            await service.merge(conn, second, third, reason="t", turn_id=None)
        ).merge_id
        assert (
            await service.merge(conn, first, second, reason="t", turn_id=None)
        ).merge_id
        found = await entities.follow_merges(conn, [first, second, third])
        missing = await entities.follow_merges(conn, [uuid4()])
    assert found == {second: first, third: first}
    assert missing == {}


# --- prompt (§4.5.3, §4.12) ----------------------------------------------------------


def _corpus_labels() -> set[str]:
    """Every label, true name, descriptor and alias of the gold corpus (scenes and
    sequences, every split), and the surface of every gold mention, of the narration
    and of the history."""
    labels: set[str] = set()
    paths = [
        *sorted((FIXTURES / "scenes").glob("*.yaml")),
        *sorted((FIXTURES / "sequences").glob("*.yaml")),
    ]
    for path in paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for scene in raw.get("turns", [raw]):
            for e in scene.get("world", []):
                labels |= {
                    e["label"],
                    e.get("true_name") or "",
                    e.get("descriptor") or "",
                }
                labels |= {a["text"] for a in e.get("aliases", [])}
            mentions = [*scene.get("gold", [])]
            for message in scene.get("history", []):
                mentions += message.get("mentions", [])
            labels |= {m["surface"] for m in mentions}
    return {label for label in labels if label.strip()}


def _form(text: str) -> str:
    """Words of `text`, folded (case, accents, apostrophes): what the comparison reads."""
    return " ".join(re.findall(r"\w+", NORMALIZER.fold(text)))


def _heads() -> set[str]:
    """Leading words a label may start with (articles, elisions) in every pack."""
    heads = set()
    for lang in available_langs():
        pack = load_lang(lang)
        heads |= {_form(w) for w in pack.articles + pack.elisions}
    return heads - {""}


def _core(label: str, heads: set[str]) -> str:
    words = _form(label).split()
    if len(words) > 1 and words[0] in heads:
        words = words[1:]
    return " ".join(words)


def _all_examples() -> list[str]:
    examples = [
        e
        for lang in available_langs()
        for e in load_lang(lang).prompt_examples.identity
    ]
    for slug in available_genres():
        for group in load_genre(slug).identity.prompt_examples.values():
            examples += group
    return [f"{e.input} {e.output}" for e in examples]


def _occurs(phrase: str, text: str) -> bool:
    folded = NORMALIZER.fold(phrase)
    return (
        re.search(rf"(?<!\w){re.escape(folded)}(?!\w)", NORMALIZER.fold(text))
        is not None
    )


def _rendered(lexicon) -> str:
    return build_identity_system_prompt(lexicon) + build_identity_system_prompt(
        lexicon, strong=True
    )


def _pack_forms() -> set[str]:
    """Every lexical entry of every language pack, in `_form` (« celui-là » → « celui
    la »)."""
    forms: set[str] = set()

    def walk(value):
        if isinstance(value, str):
            forms.add(_form(value))
        elif isinstance(value, list | dict):
            for v in value.values() if isinstance(value, dict) else value:
                walk(v)

    skipped = {"lang", "version", "apostrophes", "prompt_examples"}
    for lang in available_langs():
        raw = yaml.safe_load((PACKS_DIR / "lang" / f"{lang}.yaml").read_text("utf-8"))
        for key, value in raw.items():
            if key not in skipped:
                walk(value)
    return forms - {""}


def test_a_card_says_the_protagonist_carries_an_object():
    terminal = replace(_candidate(8, "Terminal personnel", "object"), carried=True)
    card = render_card(terminal, protagonist=False, companion=False)
    assert "carried by the PROTAGONIST" in card
    other = render_card(
        _candidate(9, "Bague", "object"), protagonist=False, companion=False
    )
    assert "carried" not in other


def test_a_card_marks_a_label_the_pc_does_not_know():
    named = _candidate(
        8,
        "Coffre Gris",
        "object",
        aliases=[_alias("Coffre Gris", known=False), _alias("le coffre", "descriptor")],
    )
    card = render_card(named, protagonist=False, companion=False)
    assert '"Coffre Gris" (unknown to the PC)' in card
    person = _candidate(
        9, "Ana Ferro", aliases=[_alias("Ana Ferro", "true_name", known=False)]
    )
    card = render_card(person, protagonist=False, companion=False)
    assert '"Ana Ferro" (name unknown to the PC)' in card
    known = render_card(_candidate(10, "Rue Haute", "location"), protagonist=False,
                        companion=False)  # fmt: skip
    assert "unknown" not in known


def test_prompt_examples_contain_no_corpus_name():
    """No label, alias, descriptor or mention surface of the gold corpus (any split,
    narrations and histories) in an example of any pack nor in a rendered prompt: the
    examples must never teach a held-out case. Exempt: a form that is one pack entry
    (« le garde », a pronoun the prompt lists) or a field name of the output schema."""
    heads = _heads()
    fields = set(
        decision_schema(["E1"])["properties"]["mentions"]["items"]["properties"]
    )
    exempt = _pack_forms() | fields
    cores = {
        core
        for label in _corpus_labels()
        if (core := _core(label, heads)) and core not in exempt
    }
    assert len(cores) > 300
    texts = _all_examples() + [
        _rendered(for_game(lang, None)) for lang in available_langs()
    ]
    assert len(texts) > len(available_langs())
    leaked = {
        core for core in cores for text in texts if f" {core} " in f" {_form(text)} "
    }
    assert sorted(leaked) == [], ", ".join(sorted(leaked))


def _pack_words(lang: str) -> set[str]:
    raw = yaml.safe_load((PACKS_DIR / "lang" / f"{lang}.yaml").read_text("utf-8"))
    words: set[str] = set()

    def walk(value):
        if isinstance(value, str):
            words.add(NORMALIZER.key(value))
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)

    skipped = {"lang", "version", "apostrophes", "prompt_examples"}
    for key, value in raw.items():
        if key not in skipped and not isinstance(value, bool | int):
            walk(value)
    return words - {""}


def _stub_lexicon() -> Lexicon:
    raw = yaml.safe_load((PACKS_DIR / "lang" / "en.yaml").read_text("utf-8"))
    raw["pronouns"] = {
        "personal": ["zorb"],
        "demonstrative": ["quilm"],
        "indefinite": ["anyfrob"],
    }
    raw["reveal_cues"] = ["the name is glorp"]
    raw["source_cues"] = ["blinkplate"]
    raw["prompt_examples"] = {
        "identity": [{"input": "Lang input sample.", "output": "Lang output sample."}],
        "extraction": [],
    }
    genre = GenrePack.model_validate(
        {
            "slug": "stub",
            "identity": {
                "prompt_examples": {
                    "identity": [
                        {
                            "input": "Genre input sample.",
                            "output": "Genre output sample.",
                        }
                    ]
                }
            },
        }
    )
    return Lexicon(LangPack.model_validate(raw), genre)


def test_prompt_renders_pack_lists_and_genre_examples():
    lexicon = _stub_lexicon()
    prompt = build_identity_system_prompt(lexicon)
    for word in ("zorb", "quilm", "anyfrob", "the name is glorp", "blinkplate"):
        assert word in prompt
    # The genre's examples replace the language's.
    assert "Genre input sample." in prompt and "Genre output sample." in prompt
    assert "Lang input sample." not in prompt
    assert prompt.startswith(IDENTITY_PROMPT_MARKER)
    assert classify_call(prompt) == "identity"
    strong = build_identity_system_prompt(lexicon, strong=True)
    assert classify_call(strong) == "identity_strong"
    assert classify_call(strong, tool_name="identity_decisions") == "identity_strong"

    # With the English pack, no French word in the prompt: what the English pack brings
    # (its words, the words of its phrases and of its examples) is English by definition.
    english = _rendered(for_game("en", None))
    english_examples = load_lang("en").prompt_examples.identity
    brought = {
        NORMALIZER.key(w)
        for text in [
            *_pack_words("en"),
            *(e.input + " " + e.output for e in english_examples),
        ]
        for w in re.findall(r"\w+", text)
    }
    french_only = _pack_words("fr") - _pack_words("en") - brought
    assert {w for w in french_only if _occurs(w, english)} == set()
    assert all(e.input in english for e in english_examples)


def test_card_and_user_prompt_render_the_candidate():
    stranger = Candidate(
        entity_id=uuid4(),
        handle=17,
        entity_type="character",
        label="la femme âgée",
        aliases=[
            _alias("Vela Sorn", "true_name", known=False),
            _alias("la vieille", "descriptor"),
        ],
        occupation="tisserande",
        usual_location="le marché",
        last_seen_turn=12,
        description_line="Cheveux blancs.",
        score=0,
        sources={"present"},
    )
    card = render_card(stranger, protagonist=False, companion=False)
    for part in (
        "E17",
        "character",
        "la femme âgée",
        "Vela Sorn",
        "la vieille",
        "tisserande",
        "le marché",
        "12",
        "Cheveux blancs.",
    ):
        assert part in card
    assert "PROTAGONIST" in render_card(stranger, protagonist=True, companion=False)
    assert 'la femme âgée" (unknown' not in card  # a known descriptor label
    user = build_identity_user_prompt(
        "Le texte.", [card], ['"x" = E3'], ["present: E17"]
    )
    assert "Le texte." in user and card in user and '"x" = E3' in user
    assert "present: E17" in user
