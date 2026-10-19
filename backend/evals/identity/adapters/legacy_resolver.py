"""Adapter of the current resolver (services/extraction/resolver.py) for the baseline (#151).

Disposable: removed with the legacy resolver in PR 5. The resolver is driven exactly as
the extraction orchestrator drives it: MESSAGE 1 is the previous narration,
`scene.history[-1]`, annotated with its reviewed links (`[= <world label>]`, the
canonical names the app would have stored); a scene without history gets the
orchestrator's first-turn reference built from the world entities; with no reference
at all the app skips the resolver, so the scene gets no decision. MESSAGE 2 is the
narration.

Its output is mapped to decisions:

- each mention string is located in the narration like `build_span_annotations` does
  (every case-insensitive occurrence; one span keeps its first mapping); of the spans
  sharing a start the longest is kept, and a span nested in a longer one of the same
  canonical is dropped (one decision per mention);
- `existing[].canonical` -> MATCH to the world entity whose label has the same
  normalised form (lexicon of the scene's language: determiner stripped, case folded),
  preferring an entity of the resolver's type; an unknown canonical is a MATCH to the
  id `unknown:<canonical>`, always wrong. The legacy resolver never records an alias;
- `new[]` -> NEW at the first occurrence of the entity, with a synthetic system id;
  its later occurrences are MATCHes to that id (the app creates one entity per
  suggested name). Within a sequence a name created by an earlier turn is matched,
  before the world labels, to the entity the system created.

Candidates (C@10) are the entities annotated in MESSAGE 1: the current blocking, a
horizon of one message.

Sequences are an approximation of the app (`SEQUENCE_NOTE`, printed in the report
header): MESSAGE 1 of each turn is the turn's gold history annotated with world labels,
not the system's own annotations of its previous turn; only the names the system
created in earlier turns carry over (above).

Disposable code: `request_options` reads the provider's private `_request_options`
(the exact wire options) and falls back to the bare model and sampling options.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from evals.identity.corpus import Scene, WorldEntity
from evals.identity.lexicon import Lexicon, load_lexicon
from evals.identity.run import Decision, RunResult
from llm.session import LLMSession
from services.extraction.orchestrator import _build_first_turn_reference
from services.extraction.resolver import (
    MentionMapping,
    ResolutionMap,
    build_span_annotations,
    resolve_entities,
)
from services.llm_providers import CompletionResult, LLMProvider, LLMUsage

GAME_ID = UUID(int=0)  # the resolver takes a game id it does not use
# The entity_type filter of the orchestrator's first-turn reference query.
REGISTRY_TYPES = ("character", "location", "organization")
# World types the resolver's own type vocabulary calls `character`.
CHARACTER_TYPES = ("protagonist", "companion")
SEQUENCE_NOTE = (
    "Sequences: MESSAGE 1 of each turn is the gold history annotated with world "
    "labels, not the system's own annotations of its previous turn."
)
EMPTY_RESOLUTION = '{"existing": [], "new": []}'  # the capture's quiet reply
USAGE_COUNTERS = (
    "cost_usd",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


# --- MESSAGE 1 --------------------------------------------------------------


@dataclass(frozen=True)
class Reference:
    text: str
    annotations: list[list]
    candidates: list[str]  # world ids annotated in `text`, in order of appearance


class _WorldConnection:
    """Answers the first-turn reference query from the scene's world."""

    def __init__(self, scene: Scene) -> None:
        self._world = scene.world

    async def fetch(self, _query: str, _game_id: UUID) -> list[dict]:
        rows = [
            {"name": e.label, "entity_type": e.type}
            for e in self._world
            if e.type in REGISTRY_TYPES
        ]
        return sorted(rows, key=lambda r: (r["entity_type"], r["name"]))


class _WorldPool:
    def __init__(self, scene: Scene) -> None:
        self._connection = _WorldConnection(scene)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_WorldConnection]:
        yield self._connection


async def reference(scene: Scene) -> Reference:
    """MESSAGE 1 of the resolver for `scene`, its annotations and the candidates."""
    world = {e.id: e for e in scene.world}
    if scene.history:
        last = scene.history[-1]
        linked = [
            (m, world[m.parsed.entity_id])
            for m in last.mentions
            if m.parsed.decision == "MATCH"
        ]
        annotations = [
            [m.start, m.start + len(m.surface), e.label, e.type] for m, e in linked
        ]
        return Reference(last.text, annotations, _unique([e.id for _, e in linked]))
    text, annotations = await _build_first_turn_reference(_WorldPool(scene), GAME_ID)
    by_label = {e.label: e.id for e in scene.world}
    ids = [by_label[a[2]] for a in annotations or []]
    return Reference(text, annotations or [], _unique(ids))


def _unique(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


# --- offline providers --------------------------------------------------------


class OfflineProvider(LLMProvider):
    """Records each completion request and answers with a fixed reply.

    It takes the provider name and model of `like` (the provider the app would use), so
    the session prices and logs the call as the app's.
    """

    def __init__(self, like: LLMProvider, reply: str = "") -> None:
        self._like = like
        self.reply = reply
        self.MODEL_MAIN = like.model_name("resolver")
        self.calls: list[dict] = []

    @property
    def provider_name(self) -> str:
        return self._like.provider_name

    @property
    def supports_cache_control(self) -> bool:
        return self._like.supports_cache_control

    def model_name(self, purpose: str) -> str:
        return self._like.model_name(purpose)

    async def stream(self, system_prompt, messages, temperature, max_tokens):
        raise NotImplementedError("the resolver makes no streamed call")
        yield  # pragma: no cover

    async def complete(self, system_prompt, messages, temperature, max_tokens):
        self.calls.append(
            {
                "system": system_prompt,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return CompletionResult(content=self.reply, usage=LLMUsage())


def request_options(provider: LLMProvider, *, max_tokens: int, temperature: float):
    """Model and sampling options the provider puts on the wire for one request."""
    build = getattr(provider, "_request_options", None)
    if build is None:
        return {
            "model": provider.model_name("resolver"),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    return build(max_tokens, temperature)


# --- output -> decisions ----------------------------------------------------


def _norm(lexicon: Lexicon, name: str) -> str:
    return lexicon.key(lexicon.strip_determiner(name))


def _resolver_type(entity: WorldEntity) -> str:
    return "character" if entity.type in CHARACTER_TYPES else entity.type


def _world_id(
    world: list[WorldEntity], lexicon: Lexicon, canonical: str, entity_type: str
) -> str | None:
    key = _norm(lexicon, canonical)
    found = [e for e in world if _norm(lexicon, e.label) == key]
    typed = [e for e in found if _resolver_type(e) == entity_type]
    chosen = (typed or found)[:1]
    return chosen[0].id if chosen else None


def spans(
    text: str, resolution: ResolutionMap
) -> list[tuple[int, int, MentionMapping]]:
    """One (start, end, mapping) per located mention, see the module doc."""
    found: dict[tuple[int, int], MentionMapping] = {}
    for mapping in resolution.mappings:
        for start, end, _, _ in build_span_annotations(text, ResolutionMap([mapping])):
            found.setdefault((start, end), mapping)
    longest: dict[int, tuple[int, MentionMapping]] = {}
    for (start, end), mapping in found.items():
        if start not in longest or end > longest[start][0]:
            longest[start] = (end, mapping)
    kept = sorted((s, e, m) for s, (e, m) in longest.items())

    def nested(span) -> bool:
        s, e, m = span
        return any(
            (os, oe) != (s, e) and os <= s and e <= oe and om.canonical == m.canonical
            for os, oe, om in kept
        )

    return [span for span in kept if not nested(span)]


@dataclass
class Mapper:
    """Turns resolver output into decisions; `created` spans the turns of a sequence."""

    created: dict[str, str] = field(default_factory=dict)  # normalised name -> id

    def decisions(self, scene: Scene, resolution: ResolutionMap) -> list[Decision]:
        lexicon = load_lexicon(scene.language)
        result = []
        for start, end, m in spans(scene.narration, resolution):
            surface = scene.narration[start:end]
            key = _norm(lexicon, m.canonical)
            if key in self.created:
                result.append(_link(surface, start, self.created[key]))
            elif m.is_new:
                self.created[key] = f"new:{scene.id}:{start}"
                result.append(
                    Decision(
                        surface, start, "NEW", self.created[key], None, m.entity_type
                    )
                )
            else:
                entity_id = _world_id(scene.world, lexicon, m.canonical, m.entity_type)
                result.append(
                    _link(surface, start, entity_id or f"unknown:{m.canonical}")
                )
        return result


def _link(surface: str, start: int, entity_id: str) -> Decision:
    return Decision(surface, start, "MATCH", entity_id, None, None)


def _usage(cost: dict | None, failed: bool) -> dict:
    usage = {k: (cost or {}).get(k, 0) for k in USAGE_COUNTERS}
    return {**usage, "calls": 1, "failed_calls": int(failed)}


# --- adapter ----------------------------------------------------------------


class LegacyResolverAdapter:
    name = "legacy"
    sequence_note = SEQUENCE_NOTE
    needs_db = False  # everything comes from the scene; the pool is never read

    def __init__(self) -> None:
        self._mapper = Mapper()

    def begin_sequence(self) -> None:
        self._mapper = Mapper()

    async def candidates(self, scene: Scene) -> dict[int, list[str]]:
        ref = await reference(scene)
        return {m.start: list(ref.candidates) for m in scene.gold}

    async def run_scene(
        self, scene: Scene, *, session: LLMSession | None, pool
    ) -> RunResult:
        ref = await reference(scene)
        if not ref.text:  # the orchestrator skips the resolver
            return RunResult(scene.id, [], {}, {})
        resolution, cost = await resolve_entities(
            pool, GAME_ID, ref.text, ref.annotations, scene.narration, session
        )
        decisions = self._mapper.decisions(scene, resolution) if resolution else []
        candidates = {m.start: list(ref.candidates) for m in scene.gold}
        candidates.update({d.start: list(ref.candidates) for d in decisions})
        return RunResult(scene.id, decisions, candidates, _usage(cost, not resolution))


async def build_request(scene: Scene, like: LLMProvider) -> dict | None:
    """The request the app would send for `scene` (None when it skips the resolver)."""
    ref = await reference(scene)
    if not ref.text:
        return None
    capture = OfflineProvider(like, reply=EMPTY_RESOLUTION)
    await resolve_entities(
        None,
        GAME_ID,
        ref.text,
        ref.annotations,
        scene.narration,
        LLMSession.from_provider(capture),
    )
    (call,) = capture.calls
    options = request_options(
        like, max_tokens=call["max_tokens"], temperature=call["temperature"]
    )
    return {
        "scene_id": scene.id,
        **options,
        "system": call["system"],
        "messages": call["messages"],
    }


def replay_session(like: LLMProvider, raw_output: str) -> LLMSession:
    """A session whose resolver call answers `raw_output`, parsed by the app's code."""
    return LLMSession.from_provider(OfflineProvider(like, reply=raw_output))


def dumps_request(request: dict) -> str:
    return json.dumps(request, ensure_ascii=False, indent=2) + "\n"
