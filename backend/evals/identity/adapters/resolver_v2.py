"""Adapter of the resolver v2 (services/identity/resolution.py) for the identity eval (#154).

Each scene runs in a scratch game of the evaluation database, inside a transaction that is
rolled back: `world_loader.load_world` rebuilds the scene's world and past messages,
`scene_context` its SceneContext, the narration is stored as the turn's assistant message,
then the turn is resolved by the app's own code, in the order IdentityService.resolve_turn
runs it (block, decide, apply), so that the candidates and the decisions can be read:
- blocking on the narration (SQL);
- the decision cascade with the given LLMSession (prepass, the small model, at most one
  escalation to the strong one); `tier="cheap"` turns the escalation off
  (IdentityConfig.escalation), the small model's decisions stand;
- the application in the turn's transaction (stubs, aliases, reveals, mentions).

Decisions are mapped to the eval's by span: the linked decisions (MATCH, ALIAS, NEW) take
the spans the app writes (services.identity.mentions.place), the UNSURE and SKIP ones the
spans still free. A link names the world id of its entity. A NEW names the entity the app
created for it: its first span is the NEW (id `new:<scene id>:<start>`), its other spans
MATCH that id; a NEW the app folded into a world entity is a MATCH to it (that is what was
written); a NEW the app refused to create (ambiguous label) has no id.

Candidates: of a run, the turn's ranked candidates (what the model saw), for every gold
and decision start; for C@10 (`candidates`), each gold mention's own ranking
(evals/identity/blocking.py), on a scratch game too. Usage per scene: calls, tokens and
cost of each stage (`identity_*`, `identity_strong_*`), their totals, `escalated` and
`fallback` (0/1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from domain.identity import (
    DECISIONS,
    MentionDecision,
    MentionRow,
    TurnDecisions,
    TurnRef,
)
from evals.identity.blocking import candidates_by_mention
from evals.identity.corpus import Scene
from evals.identity.run import Decision, RunResult
from evals.identity.world_loader import load_world, scene_context, turn_key
from llm.session import LLMSession
from repos import messages
from services.identity.mentions import place
from services.identity.normalize import Normalizer
from services.identity.service import IdentityService

MATCH, ALIAS, NEW, UNSURE, SKIP = DECISIONS
LINKING = (MATCH, ALIAS, NEW)
TIERS = ("cascade", "cheap")
ASSISTANT = "assistant"
EVAL_USER = "identity-eval@invalid"
USAGE_TOTALS = ("calls", "input_tokens", "output_tokens", "cost_usd")


@asynccontextmanager
async def scratch_game(pool, language: str) -> AsyncIterator[tuple[object, UUID]]:
    """(connection, game id) of a throwaway game: everything written is rolled back."""
    async with pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            user_id = await conn.fetchval(
                "INSERT INTO users (email, password_hash) VALUES ($1, '') RETURNING id",
                EVAL_USER,
            )
            game_id = await conn.fetchval(
                "INSERT INTO games (user_id, language) VALUES ($1, $2) RETURNING id",
                user_id,
                language,
            )
            yield conn, game_id
        finally:
            await transaction.rollback()


def _current_turn(ids: dict[str, UUID]) -> int:
    """The scene's turn: the one after the last past turn `load_world` stored."""
    turn = 1
    while turn_key(turn) in ids:
        turn += 1
    return turn


async def _narration_turn(conn, game_id: UUID, ids: dict, narration: str) -> TurnRef:
    turn = _current_turn(ids)
    conversation = await messages.insert_conversation(conn, game_id, turn)
    message_id = await messages.insert_message(
        conn, game_id, conversation, ASSISTANT, narration, turn
    )
    return TurnRef(turn_id=None, message_id=message_id, cycle=turn)


def _overlaps(span: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in taken)


def placed(
    text: str, decisions: list[MentionDecision], normalizer: Normalizer
) -> list[tuple[int, int, MentionDecision]]:
    """(start, end, decision) of every span, in text order: the linked decisions first,
    as the app places them, then the UNSURE and SKIP ones on the spans left free."""
    live = [d for d in decisions if not d.ignored]
    linked = place(text, [(d, None) for d in live if d.decision in LINKING], normalizer)
    taken = [(s, e) for s, e, _, _ in linked]
    rest = place(
        text, [(d, None) for d in live if d.decision not in LINKING], normalizer
    )
    spans = [*linked, *(p for p in rest if not _overlaps((p[0], p[1]), taken))]
    return sorted(((s, e, d) for s, e, d, _ in spans), key=lambda p: p[0])


def to_decisions(
    scene: Scene,
    decisions: list[MentionDecision],
    rows: list[MentionRow],
    world_of: dict[UUID, str],
    normalizer: Normalizer,
) -> list[Decision]:
    """The eval decisions of the turn (see the module docstring)."""
    written = {(r.start_pos, r.end_pos): r.entity_id for r in rows}
    born: dict[UUID, str] = {}  # entity created by the turn -> its eval id
    out = []
    for start, end, d in placed(scene.narration, decisions, normalizer):
        surface = scene.narration[start:end]
        entity = written.get((start, end)) or d.entity_id
        known = world_of.get(entity) or born.get(entity)
        if d.decision in (MATCH, ALIAS):
            alias_kind = d.alias_kind if d.decision == ALIAS else None
            target = known or f"unknown:{entity}"
            out.append(
                Decision(surface, start, d.decision, target, alias_kind, None,
                         d.deterministic, d.escalated)
            )  # fmt: skip
        elif d.decision == NEW and known is not None:  # folded, or a repeat
            out.append(
                Decision(surface, start, MATCH, known, None, None, False, d.escalated)
            )
        elif d.decision == NEW:
            new_id = None
            if entity is not None:
                new_id = born[entity] = f"new:{scene.id}:{start}"
            out.append(
                Decision(surface, start, NEW, new_id, None, d.new_type, False,
                         d.escalated)
            )  # fmt: skip
        else:
            out.append(
                Decision(surface, start, d.decision, None, None, None,
                         d.deterministic, d.escalated)
            )  # fmt: skip
    return out


def usage_of(decided: TurnDecisions) -> dict:
    """Calls, tokens and cost of each stage and in all, `escalated` and `fallback`."""
    usage: dict = {key: 0 for key in USAGE_TOTALS}
    for purpose, entry in decided.usage.items():
        for key in USAGE_TOTALS:
            value = entry.get(key) or 0
            usage[f"{purpose}_{key}"] = value
            usage[key] += value
    usage["escalated"] = int(decided.escalated)
    usage["fallback"] = int(decided.fallback)
    return usage


class ResolverV2Adapter:
    name = "v2"
    sequence_note = ""
    candidates_note = ""
    needs_db = True

    def __init__(self, pool, *, tier: str = "cascade") -> None:
        if tier not in TIERS:
            raise ValueError(f"tier: one of {TIERS}, got {tier!r}")
        self.pool, self.tier = pool, tier

    def begin_sequence(self) -> None:
        """Every scene runs on its own scratch game: nothing carries over."""

    async def candidates(self, scene: Scene) -> dict[int, list[str | None]]:
        async with scratch_game(self.pool, scene.language) as (conn, game_id):
            ids = await load_world(
                conn, game_id, scene.world, scene.history, turn=scene.turn
            )
            by_mention, _ = await candidates_by_mention(conn, game_id, scene, ids)
        return by_mention

    async def _service(self, conn, game_id: UUID) -> IdentityService:
        identity = await IdentityService.for_game(conn, game_id)
        if self.tier == "cheap":
            identity.config = identity.config.model_copy(update={"escalation": False})
        return identity

    async def run_scene(
        self, scene: Scene, *, session: LLMSession | None, pool=None
    ) -> RunResult:
        if session is None:
            raise ValueError("the resolver v2 needs a session")
        async with scratch_game(self.pool, scene.language) as (conn, game_id):
            ids = await load_world(
                conn, game_id, scene.world, scene.history, turn=scene.turn
            )
            context = scene_context(scene, ids)
            turn = await _narration_turn(conn, game_id, ids, scene.narration)
            identity = await self._service(conn, game_id)
            found = await identity.block(conn, scene.narration, context)
            decided = await identity.decide(
                conn, session, scene.narration, context, found
            )
            applied = await identity.apply_resolution(
                conn, turn, scene.narration, context, decided
            )
        world_of = {ids[e.id]: e.id for e in scene.world if e.id in ids}
        decisions = to_decisions(
            scene,
            decided.decisions.decisions,
            applied.mentions,
            world_of,
            identity.normalizer,
        )
        ranked = [world_of.get(c.entity_id) for c in found.ranked()]
        candidates = {m.start: ranked for m in scene.gold}
        candidates.update({d.start: ranked for d in decisions})
        return RunResult(scene.id, decisions, candidates, usage_of(decided.decisions))
