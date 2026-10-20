"""Listwise identity decision of the resolver v2 (spec §4.5.3-§4.5.5): one model call per
turn over the turn's candidates, every answer checked by code, a deterministic prepass
before it, one escalation to the strong model and a fallback.

The cascade: the prepass links the unique exact names of the text without the model; the
small model (Purpose.IDENTITY) decides the rest, with one retry on an invalid output; the
strong model (Purpose.IDENTITY_STRONG) is called once at most, for the abstentions, the
revealed true names and the links that would merge two entities only. When the small model
fails twice, only the prepass applies (`fallback`, identity_events `resolver_fallback`).

The verifications (§4.5.4) reject or downgrade, never guess: a rejected link becomes
UNSURE and keeps the code of the check in `rejection` (its identity_events kind). Logs
above DEBUG hold codes, handles and counts only, never a surface or a name.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from uuid import UUID

from config import IdentityConfig, get_identity_config, get_settings
from domain.identity import (
    ALIAS_KINDS,
    DECISIONS,
    MENTION_CATEGORIES,
    NEW_ENTITY_TYPES,
    NEW_KINDS,
    Candidate,
    CandidateSet,
    MentionDecision,
    SceneContext,
    TurnDecisions,
)
from llm.session import LLMSession, Purpose
from prompts.identity_prompt import (
    DECISION_TOOL,
    build_identity_system_prompt,
    build_identity_user_prompt,
    decision_schema,
    format_handle,
    render_card,
)
from repos import entities
from services.identity.lexicon import Lexicon
from services.identity.normalize import Normalizer
from services.llm_providers import StructuredOutputMode
from utils import parse_json_response
from utils.log_safe import log_cause
from utils.trigrams import name_similarity

logger = logging.getLogger(__name__)

MATCH, ALIAS, NEW, UNSURE, SKIP = DECISIONS
TRUE_NAME = "true_name"
# Types a resolver links but never changes (spec §4.10).
RESERVED_TYPES = frozenset({"protagonist", "companion"})
# Context sources that put an entity in the scene for a self-introduction (§4.5.4).
_IN_SCENE = frozenset({entities.CONTEXT.present, entities.CONTEXT.mentioned})

# Rejection codes (identity_events kinds).
UNKNOWN_ID = "unknown_id_downgraded"
SURFACE_ABSENT = "surface_absent"
TALKS_TO_SAME_ID = "talks_to_same_id"
TRUE_NAME_ABSENT = "true_name_not_present"
NEW_INCOMPLETE = "new_without_type"
ALIAS_KIND_MISSING = "alias_kind_missing"
ALIAS_ON_RESERVED = "alias_on_reserved"
UNCONFIRMED = "escalation_unconfirmed"

_WORD = re.compile(r"\w+")
_TOOL_DESCRIPTION = "Record the identity decision of every mention of the narration."


class DecisionOutputInvalid(ValueError):
    """The model's output is not a list of decisions (the caller retries once)."""


# --- parsing --------------------------------------------------------------------------


def _json_in(text: str, mode: StructuredOutputMode):
    """The decision object of a model's text; in TEXT mode it may sit inside prose (the
    first object or list that holds decisions), else the whole text is JSON (repaired
    when it can be)."""
    if mode is StructuredOutputMode.TEXT:
        decoder = json.JSONDecoder()
        for start in (i for i, ch in enumerate(text) if ch in "{["):
            try:
                value, _ = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                continue
            if isinstance(value, list) or (
                isinstance(value, dict) and "mentions" in value
            ):
                return value
    return parse_json_response(text)


def _choice(raw: dict, key: str, allowed: tuple[str, ...]) -> str | None:
    """An optional enum field; a value outside `allowed` is dropped (the checks then
    downgrade the decision that needed it)."""
    value = raw.get(key)
    return value if value in allowed else None


def _text(raw: dict, key: str) -> str:
    value = raw.get(key)
    return value.strip() if isinstance(value, str) else ""


def _item(raw, config: IdentityConfig) -> MentionDecision:
    if not isinstance(raw, dict):
        raise DecisionOutputInvalid("a mention is not an object")
    surface = _text(raw, "surface")
    verdict = raw.get("decision")
    if not surface or verdict not in DECISIONS:
        raise DecisionOutputInvalid("a mention has no surface or no valid decision")
    handle = raw.get("handle")
    talks_to = raw.get("talks_to")
    return MentionDecision(
        surface=surface,
        decision=verdict,
        before=_text(raw, "before"),
        category=_choice(raw, "category", MENTION_CATEGORIES),
        handle=None if handle in (None, "") else str(handle).strip(),
        alias_kind=_choice(raw, "alias_kind", ALIAS_KINDS),
        new_type=_choice(raw, "new_type", NEW_ENTITY_TYPES),
        new_kind=_choice(raw, "new_kind", NEW_KINDS),
        evidence=" ".join(_text(raw, "evidence").split()[: config.evidence_max_words]),
        talks_to=tuple(
            t.strip() for t in talks_to or () if isinstance(t, str) and t.strip()
        )
        if isinstance(talks_to, list)
        else (),
    )


def parse(
    raw: dict | list | str | None,
    mode: StructuredOutputMode,
    *,
    config: IdentityConfig | None = None,
) -> list[MentionDecision]:
    """The decisions of a model output: a tool input or schema answer (a dict), or a
    text (JSON, inside prose in TEXT mode). Every mode gets the same checks: a mention
    without a surface or a valid decision makes the output invalid."""
    config = config or get_identity_config()
    value = _json_in(raw, mode) if isinstance(raw, str) else raw
    if isinstance(value, dict):
        value = value.get("mentions")
    if not isinstance(value, list):
        raise DecisionOutputInvalid("no list of mentions")
    return [_item(m, config) for m in value]


# --- verifications (§4.5.4) -----------------------------------------------------------


def _occurs(phrase: str, folded_text: str) -> bool:
    """`phrase` (folded) is a run of whole words of `folded_text`."""
    pattern = rf"(?<!\w){re.escape(phrase.strip())}(?!\w)"
    return bool(phrase.strip()) and re.search(pattern, folded_text) is not None


def _downgrade(d: MentionDecision, code: str) -> MentionDecision:
    return replace(
        d,
        decision=UNSURE,
        handle=None,
        entity_id=None,
        alias_kind=None,
        redirected_from=None,
        rejection=code,
    )


def _in_scene(c: Candidate, scene: SceneContext) -> bool:
    return c.entity_id in scene.present_ids or bool(c.sources & _IN_SCENE)


def _check_link(
    d: MentionDecision,
    c: Candidate,
    scene: SceneContext,
    redirects: dict[UUID, UUID],
) -> MentionDecision:
    """A MATCH or an ALIAS whose handle is a candidate's."""
    d = replace(d, entity_id=c.entity_id, redirected_from=None)
    if d.decision == ALIAS:
        if c.entity_type in RESERVED_TYPES:
            d = replace(d, decision=MATCH, alias_kind=None, rejection=ALIAS_ON_RESERVED)
        elif d.alias_kind is None:
            d = replace(d, decision=MATCH, rejection=ALIAS_KIND_MISSING)
        elif d.alias_kind == TRUE_NAME and not _in_scene(c, scene):
            return _downgrade(d, TRUE_NAME_ABSENT)
    live = redirects.get(c.entity_id)
    if live is not None and live != c.entity_id:
        d = replace(d, entity_id=live, redirected_from=c.entity_id)
    return d


def _check_one(
    d: MentionDecision,
    by_handle: dict[str, Candidate],
    folded_text: str,
    scene: SceneContext,
    normalizer: Normalizer,
    redirects: dict[UUID, UUID],
) -> MentionDecision:
    if d.ignored:
        return d
    if not _occurs(normalizer.fold(d.surface), folded_text):
        return replace(d, ignored=True, entity_id=None, rejection=SURFACE_ABSENT)
    if d.decision in (SKIP, UNSURE):
        return replace(d, handle=None, entity_id=None, redirected_from=None)
    if d.decision == NEW:
        if d.new_type is None or d.new_kind is None:
            return _downgrade(d, NEW_INCOMPLETE)
        return replace(d, handle=None, entity_id=None, redirected_from=None)
    c = by_handle.get(d.handle) if d.handle else None
    if c is None:
        return _downgrade(d, UNKNOWN_ID)
    return _check_link(d, c, scene, redirects)


def _apart_when_talking(
    decisions: list[MentionDecision], normalizer: Normalizer
) -> list[MentionDecision]:
    """Two mentions that talk to each other are two entities: both links are refused."""
    by_surface: dict[str, list[int]] = {}
    for i, d in enumerate(decisions):
        by_surface.setdefault(normalizer.fold(d.surface).strip(), []).append(i)
    clash: set[int] = set()
    for i, d in enumerate(decisions):
        if d.entity_id is None or d.ignored:
            continue
        for other in d.talks_to:
            for j in by_surface.get(normalizer.fold(other).strip(), []):
                if j != i and decisions[j].entity_id == d.entity_id:
                    clash |= {i, j}
    return [
        _downgrade(d, TALKS_TO_SAME_ID) if i in clash else d
        for i, d in enumerate(decisions)
    ]


def _is_new(d: MentionDecision) -> bool:
    return d.decision == NEW and not d.ignored


def _collapse_news(
    decisions: list[MentionDecision], normalizer: Normalizer
) -> list[MentionDecision]:
    """Two NEW of one type and one normalised surface are one entity: the later ones
    point at the first (`same_as`)."""
    first: dict[tuple[str, str], int] = {}
    out = []
    for i, d in enumerate(decisions):
        if not _is_new(d):
            out.append(replace(d, same_as=None))
            continue
        key = (d.new_type, normalizer.norm(d.surface))
        origin = first.setdefault(key, i)
        out.append(replace(d, same_as=None if origin == i else origin))
    return out


def _closest(
    d: MentionDecision,
    candidates: CandidateSet,
    normalizer: Normalizer,
    config: IdentityConfig,
) -> UUID | None:
    """The candidate of the NEW's type whose name is closest to it, from
    `probable_duplicate` similarity up."""
    norm = normalizer.norm(d.surface)
    best, best_score = None, config.probable_duplicate
    for c in candidates.ranked():
        if c.entity_type != d.new_type:
            continue
        names = {normalizer.norm(c.label), *(a.alias_norm for a in c.aliases)}
        score = max(name_similarity(norm, n) for n in names)
        if score >= best_score:
            best, best_score = c.entity_id, score
    return best


def verify(
    decisions: list[MentionDecision],
    candidates: CandidateSet,
    text: str,
    scene: SceneContext,
    *,
    normalizer: Normalizer,
    config: IdentityConfig | None = None,
    redirects: dict[UUID, UUID] | None = None,
) -> list[MentionDecision]:
    """The decisions after every check of §4.5.4. `redirects`: merge tombstone -> live
    entity, for the candidates merged since the blocking. Idempotent: a checked list
    checks the same."""
    config = config or get_identity_config()
    by_handle = {
        format_handle(c.handle): c
        for c in [*candidates.exact.values(), *candidates.ranked()]
    }
    folded_text = normalizer.fold(text)
    checked = [
        _check_one(d, by_handle, folded_text, scene, normalizer, redirects or {})
        for d in decisions
    ]
    checked = _collapse_news(_apart_when_talking(checked, normalizer), normalizer)
    return [
        replace(
            d,
            probable_duplicate=_closest(d, candidates, normalizer, config)
            if _is_new(d) and d.same_as is None
            else None,
            verified=d.rejection is None and not d.ignored,
        )
        for d in checked
    ]


# --- prepass (§4.5.5 step 1) ----------------------------------------------------------


def _joins(normalizer: Normalizer) -> re.Pattern[str]:
    """What may stand between two words of one name: spaces, apostrophes, hyphens and the
    signs of the pack's ordinal markers (never a sentence break)."""
    signs = {
        ch
        for marker in normalizer.pack.ordinal_markers
        for ch in marker
        if not ch.isalnum() and not ch.isspace()
    }
    allowed = "".join(
        re.escape(ch) for ch in {*normalizer.pack.apostrophes, "-", *signs}
    )
    return re.compile(rf"[\s{allowed}]*")


def prepass(
    text: str,
    candidates: CandidateSet,
    *,
    normalizer: Normalizer,
    config: IdentityConfig | None = None,
) -> list[MentionDecision]:
    """MATCH, without the model, every run of words of `text` whose normalised form names
    exactly one entity (`candidates.exact`), longest run first, left to right."""
    if not candidates.exact:
        return []
    config = config or get_identity_config()
    longest = max(len(norm.split()) for norm in candidates.exact)
    # A name's words, plus as many glued or leading words (article, elision, ordinal).
    reach = longest + longest + 1
    joins = _joins(normalizer)
    words = list(_WORD.finditer(text))
    found = []
    i = 0
    while i < len(words):
        hit = None
        for last in range(i, min(len(words), i + reach)):
            if last > i and not joins.fullmatch(
                text[words[last - 1].end() : words[last].start()]
            ):
                break
            surface = text[words[i].start() : words[last].end()]
            c = candidates.exact.get(normalizer.norm(surface))
            if c is not None:
                hit = (last + 1, surface, c)
        if hit is None:
            i += 1
            continue
        end, surface, c = hit
        start = max(0, i - config.before_words)
        found.append(
            MentionDecision(
                surface=surface,
                decision=MATCH,
                before=" ".join(w.group() for w in words[start:i]),
                handle=format_handle(c.handle),
                entity_id=c.entity_id,
                verified=True,
                deterministic=True,
            )
        )
        i = end
    return found


# --- the cascade (§4.5.5) -------------------------------------------------------------


def _add_usage(usage: dict, purpose: Purpose, cost: dict | None) -> None:
    entry = usage.setdefault(
        purpose.value,
        {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    )
    entry["calls"] += 1
    for key in ("input_tokens", "output_tokens", "cost_usd"):
        entry[key] += (cost or {}).get(key) or 0


async def _attempt(
    session: LLMSession,
    purpose: Purpose,
    system: str,
    user: str,
    schema: dict,
    config: IdentityConfig,
    usage: dict,
) -> list[MentionDecision] | None:
    """One call and its parsed decisions; None when it failed or its output is invalid."""
    mode = session.provider_for(purpose).structured_output_mode
    try:
        if mode is StructuredOutputMode.TEXT:
            call = await session.complete_text(
                purpose,
                system,
                [{"role": "user", "content": user}],
                0,
                config.decision_max_tokens,
            )
        else:
            call = await session.extract_structured(
                system,
                user,
                DECISION_TOOL,
                _TOOL_DESCRIPTION,
                schema,
                0,
                config.decision_max_tokens,
                purpose=purpose,
            )
    except Exception as e:
        log_cause(
            logger,
            logging.WARNING,
            f"[IDENTITY] {purpose.value} call failed",
            e,
            debug_detail=get_settings().log_prompts,
        )
        return None
    _add_usage(usage, purpose, call.cost)
    try:
        return parse(call.value, mode, config=config)
    except DecisionOutputInvalid as e:
        logger.warning(f"[IDENTITY] {purpose.value} output invalid: {e}")
        return None


class _Prompt:
    """The prompts of a turn: cards, resolved mentions and scene lines."""

    def __init__(
        self,
        text: str,
        candidates: CandidateSet,
        scene: SceneContext,
        lexicon: Lexicon,
        session: LLMSession,
    ):
        self.text, self.scene, self.lexicon, self.session = (
            text,
            scene,
            lexicon,
            session,
        )
        everyone = {c.entity_id: c for c in candidates.ranked()}
        for c in candidates.exact.values():
            everyone.setdefault(c.entity_id, c)
        self.candidates = list(everyone.values())
        self.handle_of = {c.entity_id: format_handle(c.handle) for c in self.candidates}

    def card(self, c: Candidate) -> str:
        return render_card(
            c,
            protagonist=c.entity_id == self.scene.protagonist_id,
            companion=c.entity_id == self.scene.companion_id,
        )

    def scene_lines(self) -> list[str]:
        handle = self.handle_of.get
        present = [handle(i) for i in self.scene.present_ids if handle(i)]
        lines = [f"present: {', '.join(present)}"] if present else []
        for name, entity_id in (
            ("current location", self.scene.location_id),
            ("protagonist", self.scene.protagonist_id),
            ("companion", self.scene.companion_id),
        ):
            if handle(entity_id):
                lines.append(f"{name}: {handle(entity_id)}")
        return lines

    def messages(
        self,
        chosen: list[Candidate],
        resolved: list[MentionDecision],
        purpose: Purpose,
        *,
        mentions: list[str] | None = None,
    ) -> tuple[str, str, dict]:
        schema = decision_schema([format_handle(c.handle) for c in chosen])
        mode = self.session.provider_for(purpose).structured_output_mode
        system = build_identity_system_prompt(
            self.lexicon, strong=purpose is Purpose.IDENTITY_STRONG
        )
        lines = list(dict.fromkeys(f'"{d.surface}" = {d.handle}' for d in resolved))
        user = build_identity_user_prompt(
            self.text,
            [self.card(c) for c in chosen],
            lines,
            self.scene_lines(),
            mentions=mentions,
            schema=schema if mode is StructuredOutputMode.TEXT else None,
        )
        return system, user, schema


def _names_another(
    d: MentionDecision, candidates: list[Candidate], normalizer: Normalizer
) -> bool:
    """The link would merge: its surface is a name of another candidate."""
    if d.decision not in (MATCH, ALIAS) or d.entity_id is None:
        return False
    norm = normalizer.norm(d.surface)
    linked = {d.entity_id, d.redirected_from}
    return any(
        c.entity_id not in linked and norm in {a.alias_norm for a in c.aliases}
        for c in candidates
    )


def _risky(d: MentionDecision, candidates: list[Candidate], normalizer) -> bool:
    if d.ignored or d.deterministic:
        return False
    if d.decision == UNSURE or (d.decision == ALIAS and d.alias_kind == TRUE_NAME):
        return True
    return _names_another(d, candidates, normalizer)


def _theirs(
    risky: list[MentionDecision],
    prompt: _Prompt,
    normalizer: Normalizer,
    config: IdentityConfig,
) -> list[Candidate]:
    """The candidates the strong model sees: those the risky mentions link to, those
    whose names are close to theirs, and the entities in the scene."""
    linked = {d.entity_id for d in risky} | {d.redirected_from for d in risky}
    norms = [normalizer.norm(d.surface) for d in risky]

    def close(c: Candidate) -> bool:
        names = {normalizer.norm(c.label), *(a.alias_norm for a in c.aliases)}
        return any(name_similarity(n, a) >= config.s_word for n in norms for a in names)

    return [
        c
        for c in prompt.candidates
        if c.entity_id in linked or _in_scene(c, prompt.scene) or close(c)
    ]


def _settle(
    decided: list[MentionDecision],
    risky: list[int],
    answers: list[MentionDecision],
    normalizer: Normalizer,
) -> list[MentionDecision]:
    """The strong model's answers in place of the risky decisions (one answer per
    mention, matched by surface then by the words before it). A risky decision left
    unanswered is never applied: it becomes UNSURE."""
    pending: dict[str, list[MentionDecision]] = {}
    for a in answers:
        pending.setdefault(normalizer.fold(a.surface).strip(), []).append(a)
    out = list(decided)
    for i in risky:
        d = decided[i]
        options = pending.get(normalizer.fold(d.surface).strip(), [])
        same = [a for a in options if a.before == d.before] or options
        if same:
            answer = same[0]
            options.remove(answer)
            out[i] = replace(answer, escalated=True)
        elif d.decision == UNSURE:
            out[i] = replace(d, escalated=True)
        else:
            out[i] = replace(_downgrade(d, UNCONFIRMED), escalated=True)
    return out


def _linked(
    decisions: list[MentionDecision], candidates: list[Candidate]
) -> list[UUID]:
    by_handle = {format_handle(c.handle): c.entity_id for c in candidates}
    return sorted(
        {by_handle[d.handle] for d in decisions if d.handle in by_handle}, key=str
    )


def _debug(label: str, decisions: list[MentionDecision]) -> None:
    if get_settings().log_prompts:
        logger.debug(
            f"[IDENTITY] {label}: "
            + "; ".join(f"{d.surface!r} {d.decision} {d.handle}" for d in decisions)
        )


async def decide_turn(
    session: LLMSession,
    conn,
    text: str,
    candidates: CandidateSet,
    scene: SceneContext,
    *,
    thresholds: IdentityConfig,
    normalizer: Normalizer,
    lexicon: Lexicon,
) -> TurnDecisions:
    """The identity decisions of a turn's narration (spec §4.5.5)."""
    config = thresholds
    usage: dict = {}
    pre = prepass(text, candidates, normalizer=normalizer, config=config)
    prompt = _Prompt(text, candidates, scene, lexicon, session)
    system, user, schema = prompt.messages(prompt.candidates, pre, Purpose.IDENTITY)
    first = await _attempt(
        session, Purpose.IDENTITY, system, user, schema, config, usage
    )
    if first is None:  # one retry (§4.5.5)
        first = await _attempt(
            session, Purpose.IDENTITY, system, user, schema, config, usage
        )
    if first is None:
        logger.warning(
            f"[IDENTITY] decision failed twice: prepass only ({len(pre)} mentions)"
        )
        return TurnDecisions(pre, escalated=False, fallback=True, usage=usage)

    taken = {normalizer.fold(d.surface).strip() for d in pre}
    model = [d for d in first if normalizer.fold(d.surface).strip() not in taken]
    redirects = await entities.follow_merges(
        conn, _linked([*pre, *model], prompt.candidates)
    )

    def checked(decisions: list[MentionDecision]) -> list[MentionDecision]:
        return verify(
            decisions,
            candidates,
            text,
            scene,
            normalizer=normalizer,
            config=config,
            redirects=redirects,
        )

    decided = checked([*pre, *model])
    _debug("first pass", decided)
    risky = [
        i for i, d in enumerate(decided) if _risky(d, prompt.candidates, normalizer)
    ]
    if not risky:
        return TurnDecisions(decided, escalated=False, fallback=False, usage=usage)

    chosen = _theirs([decided[i] for i in risky], prompt, normalizer, config)
    mentions = [
        f'"{decided[i].surface}"'
        + (f' (after "{decided[i].before}")' if decided[i].before else "")
        for i in risky
    ]
    system, user, schema = prompt.messages(
        chosen, [], Purpose.IDENTITY_STRONG, mentions=mentions
    )
    answers = await _attempt(
        session, Purpose.IDENTITY_STRONG, system, user, schema, config, usage
    )
    if answers:
        redirects |= await entities.follow_merges(
            conn, _linked(answers, prompt.candidates)
        )
    decided = checked(_settle(decided, risky, answers or [], normalizer))
    _debug("escalation", decided)
    return TurnDecisions(decided, escalated=True, fallback=False, usage=usage)
