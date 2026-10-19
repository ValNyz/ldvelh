"""Identity gold corpus: Pydantic models, YAML loaders and semantic validation (#151).

The annotation rules live in tests/fixtures/identity/ANNOTATION.md. Loading checks the
shape (unknown keys, negative offsets and malformed `expected` strings are rejected);
`validate_scene` and `validate_sequence` check what the shape cannot: offsets, ids, the
mechanical category rules (evals/identity/categories.py), reveals and knowledge flags.
"""

import itertools
from pathlib import Path
from typing import Literal, NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from evals.identity.categories import category_error

EntityType = Literal[
    "character", "location", "organization", "object", "protagonist", "companion", "arc"
]
Category = Literal[
    "EASY", "PART", "DESC", "GAP", "REVEAL", "NEW", "XTYPE", "SKIP", "PC"
]
AliasKind = Literal[
    "true_name", "descriptor", "short", "title", "former_name", "nickname", "label"
]

HARD_CATEGORIES = ("PART", "DESC", "GAP", "REVEAL", "NEW", "XTYPE")
ALIAS_KINDS = frozenset(AliasKind.__args__)
NEW_TYPES = frozenset(
    {"character", "location", "organization", "object"}
)  # arcs are never created by a mention
# Alias kinds that name an entity: an unknown one must be listed in gold_knowledge.
KNOWLEDGE_NAME_KINDS = frozenset({"true_name", "label"})


class Expected(NamedTuple):
    decision: Literal["MATCH", "ALIAS", "NEW", "SKIP"]
    entity_id: str | None
    alias_kind: str | None
    new_type: str | None


def parse_expected(text: str) -> Expected:
    """`MATCH <id>` | `ALIAS <id> <kind>` | `NEW <type>` | `SKIP`; raises ValueError otherwise."""
    parts = text.split()
    match parts:
        case ["MATCH", entity_id]:
            return Expected("MATCH", entity_id, None, None)
        case ["ALIAS", entity_id, kind] if kind in ALIAS_KINDS:
            return Expected("ALIAS", entity_id, kind, None)
        case ["NEW", new_type] if new_type in NEW_TYPES:
            return Expected("NEW", None, None, new_type)
        case ["SKIP"]:
            return Expected("SKIP", None, None, None)
    raise ValueError(
        f"malformed expected {text!r} (MATCH <id> | ALIAS <id> <kind> | NEW <type> | SKIP)"
    )


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Alias(_Strict):
    text: str
    kind: AliasKind
    known: bool
    secret: bool = False


class WorldEntity(_Strict):
    id: str
    type: EntityType
    label: str
    true_name: str | None = None
    descriptor: str | None = None
    aliases: list[Alias] = []
    known: bool
    secret: bool = False
    occupation: str | None = (
        None  # gold value, no knowledge state: an unknown attribute is a gold_knowledge fact
    )
    location: str | None = None
    last_seen_turn: int | None = None


class GoldMention(_Strict):
    surface: str
    start: int = Field(ge=0)
    category: Category
    expected: str
    accept_also: list[str] = []
    trap: bool = (
        False  # NEW trap: a similar world entity of the same type is another one
    )
    pov_error: bool = (
        False  # real scene: unknown name first given in the narrative voice
    )

    @field_validator("expected")
    @classmethod
    def _expected_is_well_formed(cls, value: str) -> str:
        parse_expected(value)
        return value

    @field_validator("accept_also")
    @classmethod
    def _accept_also_is_well_formed(cls, values: list[str]) -> list[str]:
        for value in values:
            parse_expected(value)
        return values

    @property
    def parsed(self) -> Expected:
        return parse_expected(self.expected)


class HistoryMessage(_Strict):
    text: str
    mentions: list[GoldMention] = []


class NarratorReveal(_Strict):
    ref: str  # as the narrator emitted it: handle, id or textual reference
    real_name: str | None = None


class Disclosure(_Strict):
    handle: str
    kind: Literal["name", "fact"]
    condition: str | None = None


class SceneInfo(_Strict):
    location: str
    present: list[str]
    reveals: list[NarratorReveal]
    planned_npcs: list[str]
    secrets: list[str]
    open_disclosures: list[Disclosure]


class RevealEffect(_Strict):
    ref: str
    real_name: str | None = None


class Merge(_Strict):
    keep: str
    drop: str


class ForbiddenMerge(_Strict):
    a: str
    b: str


class GoldEffects(_Strict):
    reveals: list[RevealEffect]
    merges: list[Merge]
    forbidden_merges: list[ForbiddenMerge]


class KnowledgeItem(_Strict):
    ref: str
    kind: Literal["name", "fact"]
    state: Literal["unknown", "secret"]
    text: str


class Scene(_Strict):
    id: str
    genre: str
    source: Literal["real", "synthetic", "issue"]
    turn: int | None = None
    world: list[WorldEntity]
    history: list[HistoryMessage]
    scene: SceneInfo
    narration: str
    gold: list[GoldMention]
    gold_effects: GoldEffects
    gold_knowledge: list[KnowledgeItem]


class Sequence(_Strict):
    id: str
    turns: list[Scene]
    gold_clusters: dict[str, list[str]]


class Split(_Strict):
    dev: list[str]
    test: list[str]


# --- loaders ---------------------------------------------------------------


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_scenes(root: Path, *, include_examples: bool = False) -> list[Scene]:
    """Scenes of `root/scenes/*.yaml`; `_*.yaml` examples only when asked."""
    paths = sorted((Path(root) / "scenes").glob("*.yaml"))
    return [
        Scene.model_validate(_read_yaml(p))
        for p in paths
        if include_examples or not p.name.startswith("_")
    ]


def load_sequences(root: Path) -> list[Sequence]:
    paths = sorted((Path(root) / "sequences").glob("*.yaml"))
    return [Sequence.model_validate(_read_yaml(p)) for p in paths]


def load_split(root: Path) -> Split:
    return Split.model_validate(_read_yaml(Path(root) / "split.yaml"))


# --- validation ------------------------------------------------------------


def _offset_errors(where: str, text: str, mentions: list[GoldMention]) -> list[str]:
    errors = []
    for m in mentions:
        if text[m.start : m.start + len(m.surface)] != m.surface:
            found = text.find(m.surface)
            hint = (
                f"; first found at {found}" if found >= 0 else "; absent from the text"
            )
            errors.append(
                f"{where}: surface {m.surface!r} not at start {m.start}{hint}"
            )
    starts = [m.start for m in mentions]
    for start in sorted({s for s in starts if starts.count(s) > 1}):
        errors.append(f"{where}: several mentions at the same start {start}")
    spans = sorted((m.start, m.start + len(m.surface), m.surface) for m in mentions)
    for (s1, e1, a), (s2, e2, b) in itertools.pairwise(spans):
        if s2 < e1 and e2 > e1:
            errors.append(
                f"{where}: mentions {a!r}@{s1} and {b!r}@{s2} overlap without nesting"
            )
    return errors


def _mention_errors(
    scene: Scene, where: str, m: GoldMention, ids: set[str], *, history: bool
) -> list[str]:
    label = f"{where}: {m.surface!r}@{m.start}"
    errors = []
    for text in [m.expected, *m.accept_also]:
        entity_id = parse_expected(text).entity_id
        if entity_id is not None and entity_id not in ids:
            errors.append(f"{label}: id {entity_id!r} of {text!r} is not in the world")
    if history and m.parsed.decision not in ("MATCH", "SKIP"):
        return [*errors, f"{label}: history mentions are MATCH or SKIP"]
    rule = category_error(scene, m, history=history)
    if rule:
        errors.append(f"{label}: {rule}")
    if m.trap and m.category != "NEW":
        errors.append(f"{label}: trap is only meaningful on a NEW mention")
    if m.pov_error and (m.category != "REVEAL" or scene.source != "real" or history):
        errors.append(
            f"{label}: pov_error is only set on the REVEAL of a real narration"
        )
    return errors


def _reveal_errors(scene: Scene, world: dict[str, WorldEntity]) -> list[str]:
    revealed = {r.ref for r in scene.gold_effects.reveals}
    errors = []
    for m in scene.gold:
        if m.category != "REVEAL":
            continue
        label = f"gold: REVEAL {m.surface!r}@{m.start}"
        expected = m.parsed
        entity = world.get(expected.entity_id or "")
        if expected.decision != "ALIAS" or expected.alias_kind != "true_name":
            errors.append(f"{label} needs expected ALIAS <id> true_name")
        elif expected.entity_id not in revealed:
            errors.append(
                f"{label} has no gold_effects.reveals entry for {expected.entity_id!r}"
            )
        elif entity is not None and entity.known:
            errors.append(
                f"{label}: {entity.id!r} is already known to the PC (known: true)"
            )
    return errors


def _effect_errors(scene: Scene, ids: set[str]) -> list[str]:
    effects = scene.gold_effects
    refs = [("reveals", "ref", r.ref) for r in effects.reveals]
    refs += [
        ("merges", key, getattr(m, key))
        for m in effects.merges
        for key in ("keep", "drop")
    ]
    refs += [
        ("forbidden_merges", key, getattr(f, key))
        for f in effects.forbidden_merges
        for key in ("a", "b")
    ]
    return [
        f"gold_effects.{name}: {key} {ref!r} is not in the world"
        for name, key, ref in refs
        if ref not in ids
    ]


def _scene_info_errors(scene: Scene, ids: set[str]) -> list[str]:
    info = scene.scene
    refs = [("present", r) for r in info.present] + [
        ("planned_npcs", r) for r in info.planned_npcs
    ]
    refs += [("secrets", r) for r in info.secrets]
    refs += [("open_disclosures", d.handle) for d in info.open_disclosures]
    if info.location:
        refs.append(("location", info.location))
    return [
        f"scene.{field}: {ref!r} is not in the world"
        for field, ref in refs
        if ref not in ids
    ]


def unknown_names(entity: WorldEntity) -> dict[str, bool]:
    """Names of `entity` the PC does not know, mapped to their secret flag."""
    names = {a.text: a.secret or entity.secret for a in entity.aliases if not a.known}
    if not entity.known and entity.true_name:
        names.setdefault(entity.true_name, entity.secret)
    return names


def _required_names(entity: WorldEntity) -> set[str]:
    required = {
        a.text for a in entity.aliases if not a.known and a.kind in KNOWLEDGE_NAME_KINDS
    }
    if not entity.known and entity.true_name:
        required.add(entity.true_name)
    return required


def _knowledge_errors(scene: Scene, world: dict[str, WorldEntity]) -> list[str]:
    errors = []
    listed = [(i.ref, i.text) for i in scene.gold_knowledge if i.kind == "name"]
    for item in scene.gold_knowledge:
        entity = world.get(item.ref)
        if entity is None:
            errors.append(f"gold_knowledge: ref {item.ref!r} is not in the world")
            continue
        if item.kind != "name":
            continue
        unknown = unknown_names(entity)
        if item.text not in unknown:
            errors.append(
                f"gold_knowledge: name {item.text!r} is not an unknown name of {item.ref!r}"
            )
        elif unknown[item.text] != (item.state == "secret"):
            errors.append(
                f"gold_knowledge: name {item.text!r} of {item.ref!r} is "
                f"{'secret' if unknown[item.text] else 'not secret'} in the world, state says {item.state}"
            )
    for ref, text in sorted({k for k in listed if listed.count(k) > 1}):
        errors.append(
            f"gold_knowledge: name {text!r} of {ref!r} is listed more than once"
        )
    for entity in scene.world:
        for name in sorted(
            _required_names(entity) - {t for r, t in listed if r == entity.id}
        ):
            errors.append(
                f"gold_knowledge: unknown name {name!r} of {entity.id!r} is missing"
            )
    return errors


def _world_errors(scene: Scene) -> list[str]:
    seen, errors = set(), []
    for entity in scene.world:
        if entity.id in seen:
            errors.append(f"world: duplicate id {entity.id!r}")
        seen.add(entity.id)
    for entity in scene.world:
        if entity.location is not None and entity.location not in seen:
            errors.append(
                f"world: location {entity.location!r} of {entity.id!r} is not in the world"
            )
        if entity.secret and entity.id not in scene.scene.secrets:
            errors.append(
                f"world: secret entity {entity.id!r} is missing from scene.secrets"
            )
    return errors


def validate_scene(scene: Scene) -> list[str]:
    """Every semantic error of a scene, as readable lines (empty list = valid)."""
    world = {e.id: e for e in scene.world}
    ids = set(world)
    errors = _world_errors(scene)
    errors += _offset_errors("gold", scene.narration, scene.gold)
    for m in scene.gold:
        errors += _mention_errors(scene, "gold", m, ids, history=False)
    for i, message in enumerate(scene.history):
        where = f"history[{i}]"
        errors += _offset_errors(where, message.text, message.mentions)
        for m in message.mentions:
            errors += _mention_errors(scene, where, m, ids, history=True)
    errors += _reveal_errors(scene, world)
    errors += _effect_errors(scene, ids)
    errors += _scene_info_errors(scene, ids)
    errors += _knowledge_errors(scene, world)
    return errors


def _cluster_errors(sequence: Sequence) -> list[str]:
    mentions = {
        f"{t.id}:{m.start}": m
        for t in sequence.turns
        for m in t.gold
        if m.parsed.decision != "SKIP"
    }
    clustered = [
        (entity, key) for entity, keys in sequence.gold_clusters.items() for key in keys
    ]
    keys = [key for _, key in clustered]
    errors = []
    for entity, key in clustered:
        m = mentions.get(key)
        if m is None:
            errors.append(
                f"gold_clusters: {key!r} is not a linked gold mention of the sequence"
            )
        elif m.parsed.entity_id is not None and m.parsed.entity_id != entity:
            errors.append(
                f"gold_clusters: {key!r} is in cluster {entity!r} but its gold is {m.expected!r}"
            )
    for key in sorted({k for k in keys if keys.count(k) > 1}):
        errors.append(f"gold_clusters: {key!r} is in more than one cluster")
    for key in sorted(set(mentions) - set(keys)):
        errors.append(f"gold_clusters: linked mention {key!r} is in no cluster")
    return errors


def validate_sequence(sequence: Sequence) -> list[str]:
    """Scene errors of every turn (prefixed by the turn id) plus gold cluster coherence."""
    turn_ids = [t.id for t in sequence.turns]
    duplicates = sorted({i for i in turn_ids if turn_ids.count(i) > 1})
    if duplicates:
        return [f"duplicate turn id {i!r}" for i in duplicates]
    errors = [
        f"{turn.id}: {e}" for turn in sequence.turns for e in validate_scene(turn)
    ]
    return errors + _cluster_errors(sequence)
