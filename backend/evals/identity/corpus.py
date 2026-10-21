"""Identity gold corpus: Pydantic models, YAML loaders and semantic validation (#151).

The annotation rules live in tests/fixtures/identity/ANNOTATION.md. Loading checks the
shape (unknown keys, negative offsets and malformed `expected` strings are rejected);
`validate_scene` and `validate_sequence` check what the shape cannot: offsets, ids, the
mechanical category rules (evals/identity/categories.py), reveals and knowledge flags.
"""

import hashlib
from pathlib import Path
from typing import Literal, NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from evals.identity.categories import (
    category_error,
    knows_no_name,
    lexicon_of,
    missing_pronoun_mentions,
)
from evals.identity.lexicon import DEFAULT_LANGUAGE, has_lexicon

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
    decision: Literal["MATCH", "ALIAS", "NEW", "SKIP", "SAME"]
    entity_id: str | None = None
    alias_kind: str | None = None
    new_type: str | None = None
    same_start: int | None = None  # SAME: start of the NEW mention of the entity


def parse_expected(text: str) -> Expected:
    """`MATCH <id>` | `ALIAS <id> <kind>` | `NEW <type>` | `SKIP` | `SAME <start>`.

    `SAME <start>` links a mention to the entity born at the NEW mention that starts at
    `<start>` earlier in the same narration (ANNOTATION § 4.3). Raises ValueError on
    anything else.
    """
    parts = text.split()
    match parts:
        case ["MATCH", entity_id]:
            return Expected("MATCH", entity_id)
        case ["ALIAS", entity_id, kind] if kind in ALIAS_KINDS:
            return Expected("ALIAS", entity_id, alias_kind=kind)
        case ["NEW", new_type] if new_type in NEW_TYPES:
            return Expected("NEW", new_type=new_type)
        case ["SKIP"]:
            return Expected("SKIP")
        case ["SAME", start] if start.isdigit():
            return Expected("SAME", same_start=int(start))
    raise ValueError(
        f"malformed expected {text!r} "
        "(MATCH <id> | ALIAS <id> <kind> | NEW <type> | SKIP | SAME <start>)"
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
    # An object the protagonist carries (its inventory, owner NULL); set by the rule of
    # evals/identity/carried.py, never by hand (ANNOTATION § 3.1).
    carried: bool = False

    @field_validator("carried")
    @classmethod
    def _carried_object(cls, value: bool, info) -> bool:
        if value and info.data.get("type") != "object":
            raise ValueError("carried: objects only")
        return value


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
    genre: str  # free label; the corpus needs at least two (ANNOTATION § 8)
    campaign: str  # scenes sharing a world or a history; the split keeps it whole
    language: str = DEFAULT_LANGUAGE  # selects evals/identity/lexicon/<language>.yaml
    source: Literal["real", "synthetic", "issue"]
    turn: int | None = None
    world: list[WorldEntity]
    history: list[HistoryMessage]
    scene: SceneInfo
    narration: str
    gold: list[GoldMention]
    gold_effects: GoldEffects
    gold_knowledge: list[KnowledgeItem]

    @field_validator("language")
    @classmethod
    def _language_has_a_lexicon(cls, value: str) -> str:
        if not has_lexicon(value):
            raise ValueError(f"no lexicon for language {value!r}")
        return value


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


def file_name_errors(root: Path) -> list[str]:
    """Measured scene files not named `<scene id>.yaml` (the fingerprint relies on it)."""
    errors = []
    for path in sorted((Path(root) / "scenes").glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        scene_id = (_read_yaml(path) or {}).get("id")
        if path.stem != scene_id:
            errors.append(
                f"scenes/{path.name}: scene id {scene_id!r} (file must be <id>.yaml)"
            )
    return errors


def fingerprint_test_split(root: Path) -> str:
    """sha256 of the test split's scene files, sorted by id (the content of TEST_SHA256).

    Each file is hashed with its id and byte length in front, so that renaming,
    moving a scene between dev and test or editing it all change the fingerprint.
    Line endings are normalised to LF first: a CRLF checkout keeps the same hash.
    """
    root = Path(root)
    digest = hashlib.sha256()
    for scene_id in sorted(load_split(root).test):
        raw = (root / "scenes" / f"{scene_id}.yaml").read_bytes()
        data = raw.replace(b"\r\n", b"\n")
        digest.update(f"{scene_id}\n{len(data)}\n".encode())
        digest.update(data)
    return digest.hexdigest()


# --- validation ------------------------------------------------------------


def _offset_errors(
    scene: Scene, where: str, text: str, mentions: list[GoldMention]
) -> list[str]:
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
    errors += _nesting_errors(where, mentions)
    missing = missing_pronoun_mentions(text, mentions, lexicon_of(scene))
    errors += [f"{where}: {e}" for e in missing]
    return errors


def _nesting_errors(where: str, mentions: list[GoldMention]) -> list[str]:
    """Sweep the spans with a stack of open ones: overlap without nesting, SKIP inside a SKIP."""
    errors: list[str] = []
    stack: list[GoldMention] = []
    for m in sorted(mentions, key=lambda m: (m.start, -len(m.surface))):
        while stack and stack[-1].start + len(stack[-1].surface) <= m.start:
            stack.pop()
        top = stack[-1] if stack else None
        if top is not None and top.start != m.start:  # same start is reported apart
            label = f"{where}: mentions {top.surface!r}@{top.start} and {m.surface!r}@{m.start}"
            if m.start + len(m.surface) > top.start + len(top.surface):
                errors.append(f"{label} overlap without nesting")
            elif top.category == "SKIP" and m.category == "SKIP":
                errors.append(f"{label}: a SKIP inside a SKIP (one mention)")
        stack.append(m)
    return errors


def _accept_also_errors(label: str, m: GoldMention, ids: set[str]) -> list[str]:
    """`accept_also` only widens the form on the gold entity (ANNOTATION § 4.3)."""
    if m.parsed.decision == "SAME" and m.accept_also:
        return [f"{label}: a SAME gold has no accept_also"]
    errors = []
    for text in m.accept_also:
        alternative = parse_expected(text)
        if alternative.decision == "SAME":
            errors.append(f"{label}: accept_also {text!r} cannot be SAME")
        elif alternative.decision in ("NEW", "SKIP"):
            errors.append(f"{label}: accept_also {text!r} must link the gold entity")
        elif (
            alternative.entity_id in ids and alternative.entity_id != m.parsed.entity_id
        ):
            errors.append(
                f"{label}: accept_also {text!r} names another entity than {m.expected!r}"
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
    errors += _accept_also_errors(label, m, ids)
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


def names_unknown_to_pc(entity: WorldEntity) -> dict[str, bool]:
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
        unknown = names_unknown_to_pc(entity)
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
        if entity.known and knows_no_name(entity):
            errors.append(
                f"world: {entity.id!r} has no name the PC knows (descriptor only): known must be false"
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
    errors += _offset_errors(scene, "gold", scene.narration, scene.gold)
    for m in scene.gold:
        errors += _mention_errors(scene, "gold", m, ids, history=False)
    for i, message in enumerate(scene.history):
        where = f"history[{i}]"
        errors += _offset_errors(scene, where, message.text, message.mentions)
        for m in message.mentions:
            errors += _mention_errors(scene, where, m, ids, history=True)
    errors += _reveal_errors(scene, world)
    errors += _effect_errors(scene, ids)
    errors += _scene_info_errors(scene, ids)
    errors += _knowledge_errors(scene, world)
    return errors


def _cluster_errors(sequence: Sequence) -> list[str]:
    mentions = {
        f"{t.id}:{m.start}": (t.id, m)
        for t in sequence.turns
        for m in t.gold
        if m.parsed.decision != "SKIP"
    }
    clustered = [
        (entity, key) for entity, keys in sequence.gold_clusters.items() for key in keys
    ]
    owner = {key: entity for entity, key in clustered}
    keys = [key for _, key in clustered]
    errors = []
    for entity, key in clustered:
        turn_id, m = mentions.get(key, (None, None))
        if m is None:
            errors.append(
                f"gold_clusters: {key!r} is not a linked gold mention of the sequence"
            )
        elif m.parsed.entity_id is not None and m.parsed.entity_id != entity:
            errors.append(
                f"gold_clusters: {key!r} is in cluster {entity!r} but its gold is {m.expected!r}"
            )
        elif m.parsed.decision == "SAME":
            born = f"{turn_id}:{m.parsed.same_start}"
            if owner.get(born) != entity:
                errors.append(
                    f"gold_clusters: {key!r} ({m.expected}) is not in the cluster of {born!r}"
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
