"""Listwise identity decision of the resolver v2 (#154, spec §4.5.3-§4.5.5): the prompt
rendered from the packs, the output schema, the code verifications, the deterministic
prepass and the Haiku -> Sonnet cascade with its fallback."""

import json
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml

from config import IdentityConfig
from domain.identity import Candidate, CandidateAlias, CandidateSet, SceneContext
from llm.session import LLMSession
from packs.loader import PACKS_DIR, GenrePack, LangPack, load_lang
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
from services.identity.normalize import Normalizer
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
    for field in ("category", "alias_kind", "new_type", "new_kind", "talks_to"):
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
                        "category": "PART",
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
    """No merge tombstone: follow_merges finds nothing to redirect."""

    async def fetch(self, *args):
        return []


def _mention(surface, verdict, handle=None, **fields):
    return {
        "surface": surface,
        "before": "",
        "decision": verdict,
        "handle": handle,
        "evidence": "",
        **fields,
    }


async def _decide(responses: dict, candidates: CandidateSet, text: str, scene=None):
    provider = ScriptedLLMProvider(responses, mode=StructuredOutputMode.TOOL_USE)
    session = LLMSession.from_provider(provider)
    turn = await decision.decide_turn(
        session,
        _Conn(),
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


# --- prompt (§4.5.3, §4.12) ----------------------------------------------------------


def _corpus_names() -> set[str]:
    names = set()
    for path in sorted((FIXTURES / "scenes").glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for entity in raw.get("world", []):
            names |= {entity["label"], entity.get("true_name") or ""}
            names |= {a["text"] for a in entity.get("aliases", [])}
    return {n for n in names if n}


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


def test_prompt_examples_contain_no_corpus_name():
    names = _corpus_names()
    assert len(names) > 100
    prompt = _rendered(for_game("fr", None))
    # Proper names only: a descriptor alias (« le garde ») may well be a common word.
    proper = {n for n in names if any(w[:1].isupper() for w in n.split())}
    leaked = {
        n
        for n in proper
        if _occurs(n, prompt) and NORMALIZER.key(n) not in _pack_words("fr")
    }
    assert leaked == set()


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
        "identity": [{"input": "Lang input sample.", "output": "Lang output sample."}]
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
    user = build_identity_user_prompt(
        "Le texte.", [card], ['"x" = E3'], ["present: E17"]
    )
    assert "Le texte." in user and card in user and '"x" = E3' in user
    assert "present: E17" in user
