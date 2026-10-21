"""Value types and failures of the identity service (spec §4.4, §4.11).

A failure never carries story text in its message: a reference or a name is story text
(never logged above DEBUG), so `str()` of these exceptions names only types, tables, ids
and codes. `write_item` catches every IdentityFailure, records its `code` in stats.errors
and writes an identity_events row of that kind with its `payload()`, after rolling the
item back (so the row survives).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class AliasSpec:
    text: str
    kind: str
    known: bool
    secret: bool = False


@dataclass(frozen=True)
class NewEntitySpec:
    """An entity to create. `kind`: its label is a proper name (a character's true name,
    another entity's name) or a descriptor (what the protagonist sees). `known`: the
    protagonist knows the name; for a descriptor character it applies to the aliases only
    (a descriptor is always known) and known_by_protagonist is always false, since the
    character has no true name to know yet. `secret`: the entity is guarded by the Director (every
    alias made at its creation is secret). `descriptor`: what the protagonist sees of a
    character whose label is its true name (its `descriptor` column; characters only).
    `fields`: other columns of its domain row."""

    entity_type: str
    label: str
    kind: Literal["proper_name", "descriptor"]
    known: bool = True
    secret: bool = False
    descriptor: str | None = None
    fields: dict = field(default_factory=dict)
    aliases: list[AliasSpec] = field(default_factory=list)


@dataclass(frozen=True)
class EntityRef:
    ref: str
    entity_type: str


@dataclass(frozen=True)
class FactRef:
    ref: str


@dataclass(frozen=True)
class RevealOutcome:
    """What a reveal did (spec §4.7). `applied`: a true name set; `known_only`: the
    protagonist now knows (or already knew) the name the entity has; `noop`: nothing to
    reveal, or no entity resolved; `conflict`: the narration's name replaced another one;
    `merged`: the name was another entity's, the two were merged into `merged_into` (the
    live entity, possibly `entity_id` itself); `merge_refused`: the same, but a guard
    refused the merge. `entity_id`: the entity the reference named (None: unresolved)."""

    kind: Literal[
        "applied", "known_only", "noop", "conflict", "merged", "merge_refused"
    ]
    entity_id: UUID | None
    merged_into: UUID | None = None


@dataclass(frozen=True)
class MergeOutcome:
    """A merge: its entity_merges id, or the code of the guard that refused it."""

    merge_id: UUID | None
    refused: str | None


@dataclass(frozen=True)
class ResolvedRef:
    """A resolved entity: its id, its E<n> handle, what the player may read for it and its
    type."""

    entity_id: UUID
    handle: int
    label: str
    # Informative (an untyped reference tells its type): not part of the identity.
    entity_type: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class MentionRow:
    """A span of a message that names an entity (entity_mentions): offsets in the raw
    text, the surface found there, the linked entity and how it was decided (match,
    alias, new, deterministic)."""

    start_pos: int
    end_pos: int
    surface: str
    entity_id: UUID
    decision: str
    evidence: str | None = None
    entity_type: str | None = None  # set on read
    label: str | None = None  # display_for_player, set on read


@dataclass(frozen=True)
class SceneContext:
    """What the resolver knows of the scene of a turn (spec §4.5.1): the context generator
    of the blocking reads it. `reveal_refs` and `planned_npc_handles` are references as
    the narrator and the Director give them (handle, id or name); `open_disclosure_ids`
    are the entities whose secret aliases an open disclosure lets through."""

    location_id: UUID | None
    present_ids: list[UUID]
    recent_message_ids: list[UUID]
    reveal_refs: list[str]
    planned_npc_handles: list[str]
    open_disclosure_ids: list[UUID]
    protagonist_id: UUID | None
    companion_id: UUID | None


@dataclass(frozen=True)
class CandidateAlias:
    """An alias as a candidate card shows it (never a secret one without an open
    disclosure)."""

    alias: str
    alias_norm: str
    kind: str
    known: bool
    secret: bool


@dataclass(frozen=True)
class Candidate:
    """A candidate entity and its card (spec §4.5.2). `score`: the best similarity of a
    lexical generator (0 for a context-only candidate); `sources`: the generators that
    found it."""

    entity_id: UUID
    handle: int
    entity_type: str
    label: str
    aliases: list[CandidateAlias]
    occupation: str | None
    usual_location: str | None
    last_seen_turn: int | None
    description_line: str | None
    score: float
    sources: set[str] = field(compare=False)
    carried: bool = False  # an object the protagonist carries (its inventory)


@dataclass(frozen=True)
class CandidateSet:
    """Candidates of a turn: `turn`, found in the text (at most `max_candidates`, best
    score first); `context`, the scene's entities not already in `turn`; `exact`, the
    normalised forms of the text that name exactly one entity."""

    turn: list[Candidate]
    context: list[Candidate]
    exact: dict[str, Candidate]

    def ranked(self) -> list[Candidate]:
        """Every candidate once: the turn's, then the context's."""
        return [*self.turn, *self.context]


# The listwise decision of the resolver v2 (spec §4.5.3): its verdicts, the alias kinds
# of entity_aliases, the types a mention may create and the kinds of a new label. The
# spec's per-mention `category` (the gold corpus's names, never defined to the model) is
# not asked (ruling R40).
DECISIONS = ("MATCH", "ALIAS", "NEW", "UNSURE", "SKIP")
ALIAS_KINDS = (
    "true_name",
    "descriptor",
    "short",
    "title",
    "former_name",
    "nickname",
    "label",
)
NEW_ENTITY_TYPES = ("character", "location", "organization", "object")
NEW_KINDS = ("proper_name", "descriptor")


@dataclass(frozen=True)
class MentionDecision:
    """One mention of a turn and what the resolver decided for it (spec §4.5.3-§4.5.4).

    The first fields are the model's output (`handle`: an E<n> of the turn's candidates);
    the code fills the others. `entity_id`: the linked entity (MATCH, ALIAS), merges
    followed (`redirected_from`: the tombstone the handle named). `verified`: every check
    passed unchanged; `rejection`: the code of the check that downgraded it (also its
    identity_events kind); `rejected_handle` and `rejected_entity_id`: what the refused
    decision named, kept for that event. `ignored`: its surface is not in the text, nothing applies.
    `same_as`: index, in the turn's list, of the NEW this one repeats. `probable_duplicate`:
    a candidate of the same type with a close name (the NEW is still created).
    `deterministic`: decided by the prepass; `escalated`: decided by the strong model.
    `revealed_name`: the stored name a prepass ALIAS true_name discloses (the unknown name
    the exact form belongs to), revealed in place of the surface."""

    surface: str
    decision: str
    before: str = ""
    handle: str | None = None
    alias_kind: str | None = None
    new_type: str | None = None
    new_kind: str | None = None
    evidence: str = ""
    talks_to: tuple[str, ...] = ()
    entity_id: UUID | None = None
    verified: bool = False
    rejection: str | None = None
    ignored: bool = False
    same_as: int | None = None
    probable_duplicate: UUID | None = None
    redirected_from: UUID | None = None
    rejected_handle: str | None = None
    rejected_entity_id: UUID | None = None
    deterministic: bool = False
    escalated: bool = False
    revealed_name: str | None = None
    # Offset in the text of the occurrence a prepass decision decided (None for a model
    # decision, which may name several occurrences): it takes that span only.
    start: int | None = None


@dataclass(frozen=True)
class TurnDecisions:
    """The decisions of a turn. `escalated`: the strong model was called; `fallback`: the
    model failed, only the prepass applies. `usage`: per purpose, calls, tokens and cost.
    `overruled`: the model's decisions dropped because they fell on an occurrence the
    prepass decided and named something else (another handle, a NEW, an abstention)."""

    decisions: list[MentionDecision]
    escalated: bool
    fallback: bool
    usage: dict
    overruled: int = 0

    def events(self) -> list[tuple[str, UUID | None, dict]]:
        """identity_events rows to record, as (kind, entity_id, payload): codes, handles
        and counts only, never story text."""
        rows = []
        for d in self.decisions:
            if d.rejection is not None:
                payload = {
                    "decision": d.decision,
                    "handle": d.handle,
                    "rejected_handle": d.rejected_handle,
                }
                rows.append((d.rejection, d.entity_id or d.rejected_entity_id, payload))
            if d.probable_duplicate is not None:
                rows.append(
                    (
                        "probable_duplicate",
                        d.probable_duplicate,
                        {"new_type": d.new_type},
                    )
                )
            if d.redirected_from is not None:
                rows.append(
                    (
                        "tombstone_redirected",
                        d.entity_id,
                        {"from": str(d.redirected_from)},
                    )
                )
            if d.decision == "UNSURE" and d.rejection is None and not d.ignored:
                rows.append(("uncertain", None, {}))
        if self.fallback:
            rows.append(("resolver_fallback", None, {"prepass": len(self.decisions)}))
        if self.escalated:
            escalated = sum(1 for d in self.decisions if d.escalated)
            rows.append(("escalation", None, {"mentions": escalated}))
        return rows


@dataclass(frozen=True)
class TurnRef:
    """The turn a resolution belongs to: its id (None outside a journaled turn), its
    narrator message and its cycle."""

    turn_id: UUID | None
    message_id: UUID
    cycle: int


@dataclass(frozen=True)
class SceneEntity:
    """An entity of the scene as the extractors see it (spec §4.5.6): its handle E<n>,
    its type, what the player may read for it, whether the protagonist knows its name,
    and whether this turn created it."""

    handle: str
    entity_type: str
    label: str
    known: bool
    is_new: bool


@dataclass(frozen=True)
class TurnResolution:
    """What the resolver v2 applied for a turn (spec §4.5.6): the mentions written, the
    entities created (id and scene line), the aliases learned, the reveals applied, the
    scene the extractors receive, the entity types worth an extraction (created, or
    linked while still a bare stub), and the cascade's outcome. `usage`: per purpose,
    calls, tokens and cost of the decision; `linked`: the (decision, entity) pairs the
    mentions were written from (an evaluation reads which decision took each span);
    `overruled`: see TurnDecisions."""

    mentions: list[MentionRow]
    created: list[tuple[UUID, SceneEntity]]
    aliases_added: int
    reveals: list[RevealOutcome]
    scene_entities: list[SceneEntity]
    new_types: set[str]
    escalated: bool
    fallback: bool
    deterministic: int = 0
    unsure: int = 0
    usage: dict = field(default_factory=dict)
    linked: list[tuple[MentionDecision, UUID]] = field(default_factory=list)
    overruled: int = 0

    def stats(self) -> dict:
        """Counts of the resolution, for the extraction result and the logs."""
        return {
            "mentions": len(self.mentions),
            "deterministic": self.deterministic,
            "escalated": self.escalated,
            "fallback": self.fallback,
            "unsure": self.unsure,
            "overruled": self.overruled,
            "created": len(self.created),
            "aliases": self.aliases_added,
            "reveals": len(self.reveals),
        }

    def cost_usd(self) -> float:
        return sum(entry.get("cost_usd") or 0 for entry in self.usage.values())


class IdentityFailure(Exception):
    """An identity write refused or impossible; `write_item` counts it under `code`."""

    code = "identity_failure"

    def __init__(self, message: str, game_id: UUID | None):
        super().__init__(message)
        self.game_id = game_id

    def payload(self) -> dict:
        """The identity_events payload: types, counts, ids and codes, never story text."""
        return {}

    def debug_detail(self) -> str | None:
        """Story text for a DEBUG log, if any."""
        return None


class IdentityWriteMiss(IdentityFailure):
    """A write by id found no row (UPDATE 0): the entity is gone or of another type."""

    code = "write_miss"

    def __init__(self, table: str, entity_id: UUID, game_id: UUID | None = None):
        super().__init__(f"no {table} row {entity_id}", game_id)
        self.table = table
        self.entity_id = entity_id

    def payload(self) -> dict:
        return {"table": self.table, "entity_id": str(self.entity_id)}


class RefUnresolved(IdentityFailure):
    """A required reference names no entity of its type (`candidates` 0), or several
    (ambiguous: 2 or more). For a write target (live entities only), `removed` counts the
    entities removed from the world it names, so the event tells "a removed entity" from
    "an unknown name". `ref` is story text: it is kept on the exception for DEBUG logs
    only, never in its message."""

    code = "ref_dropped"

    def __init__(
        self,
        ref: str,
        entity_type: str,
        game_id: UUID | None = None,
        *,
        candidates: int = 0,
        removed: int = 0,
    ):
        super().__init__(f"unresolved {entity_type} reference", game_id)
        self.ref = ref
        self.entity_type = entity_type
        self.candidates = candidates
        self.removed = removed

    def payload(self) -> dict:
        payload = {"entity_type": self.entity_type, "candidates": self.candidates}
        if self.removed:
            payload["removed"] = self.removed
        return payload

    def debug_detail(self) -> str | None:
        return repr(self.ref)


class AmbiguousLabel(IdentityFailure):
    """A creation refused: only aliases of several entities hold the label, so it may name
    any of them (« dans le doute, on ne crée pas »). `label` is story text, DEBUG only.

    Nothing records it when it is raised: `write_item` writes its durable identity_events
    row (kind `create_ambiguous`, after rolling the item back). A caller that runs
    create_entity outside write_item must record that event itself."""

    code = "create_ambiguous"

    def __init__(
        self,
        label: str,
        entity_type: str,
        game_id: UUID | None = None,
        *,
        candidates: int,
        source: str,
    ):
        super().__init__(f"ambiguous {entity_type} label", game_id)
        self.label = label
        self.entity_type = entity_type
        self.candidates = candidates
        self.source = source

    def payload(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "candidates": self.candidates,
            "source": self.source,
        }

    def debug_detail(self) -> str | None:
        return repr(self.label)


class UpdateRefused(IdentityFailure):
    """An extracted update of an entity extractors never update (spec §4.10: the
    protagonist beyond its skills, the companion)."""

    code = "update_refused"

    def __init__(self, entity_type: str, game_id: UUID | None = None):
        super().__init__(f"{entity_type} is not updated by extractors", game_id)
        self.entity_type = entity_type

    def payload(self) -> dict:
        return {"entity_type": self.entity_type}
