"""Dry-run report of the identity migration (spec §5.1, §5.2, #152): what the migration and
its backfill will do to the existing games, to read before the deploy (dev, then prod).

Read only: the session is put in `default_transaction_read_only` and every query is a
SELECT. It reads the database as it is before the migration (registry ids apart from the
domain ids, `characters.unknown_name`, `objects.canonical_name`) or after it (before the
backfill), and computes in Python what the SQL steps will do, with the pack of each game's
language (the configured default for a game without one, as the backfill gives it). The
classification of the unknown characters is the backfill's own function
(services/identity/classify.py), so the verdicts printed are the ones it will apply.

Sections: Ré-identification, Orphelins, Classification des PNJ inconnus, Secrets proposés,
Faits secrets, Mentions abandonnées, Doublons suspects, Collisions normalisées. Nothing is
ever merged: the suspected duplicates are for `merge_entities` on explicit agreement.

Usage (from backend/):
  DATABASE_URL=postgresql://… python -m scripts.identity_migration_report [--game ID] \
      --out report.md      (or --database-url, visible in ps)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

SECTIONS = (
    "Ré-identification",
    "Orphelins",
    "Classification des PNJ inconnus",
    "Secrets proposés",
    "Faits secrets",
    "Mentions abandonnées",
    "Doublons suspects",
    "Collisions normalisées",
)
DOMAIN_TABLES = {
    "character": "characters",
    "location": "locations",
    "organization": "organizations",
    "object": "objects",
    "protagonist": "protagonists",
    "companion": "companions",
}
# The registry's referencing columns (3.1 of the migration), for the edges an orphan has.
EDGE_COLUMNS = (
    ("relations", "source_id"),
    ("relations", "target_id"),
    ("fact_participants", "entity_id"),
    ("arc_participants", "entity_id"),
    ("chronology_participants", "entity_id"),
    ("event_participants", "entity_id"),
    ("inventory", "owner_id"),
    ("narrative_arcs", "owner_id"),
)
RESERVED_REFS = ("PROTAGONIST", "COMPANION")
_WORDS = re.compile(r"[^\W_]+")


@dataclass
class Entity:
    id: UUID
    type: str
    name: str  # the label: a character's provisional true name or descriptor, suffix apart
    created_at: datetime | None
    # A character's descriptor (unknown_name before the migration).
    seen: str | None = None
    known: bool = True
    mandatory: bool = False
    occupation: str | None = None
    workplace_id: UUID | None = None
    canonical: str | None = None
    label_suffix: str | None = None
    has_true_name: bool = True
    former: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.label_suffix})" if self.label_suffix else self.name


@dataclass
class GameReport:
    game_id: UUID
    title: str
    language: str
    reidentified: int = 0
    registered: list[tuple[str, str]] = field(default_factory=list)
    orphans: list[tuple[str, str, int, str | None]] = field(default_factory=list)
    classification: list[tuple[UUID, str, str | None, object]] = field(
        default_factory=list
    )
    secrets: list[str] = field(default_factory=list)
    secret_facts: list[tuple[int, str]] = field(default_factory=list)
    mentions_kept: int = 0
    mentions_dropped: Counter = field(default_factory=Counter)
    duplicates: list[tuple[str, str, str, str]] = field(default_factory=list)
    collisions: list[tuple[str, str, str, str]] = field(default_factory=list)


def _trigrams(text: str) -> set[str]:
    grams = set()
    for word in _WORDS.findall(text.lower()):
        padded = f"  {word} "
        grams |= {padded[i : i + 3] for i in range(len(padded) - 2)}
    return grams


def trigram_similarity(a: str, b: str) -> float:
    """pg_trgm's similarity(): shared trigrams over all trigrams of the words of a and b
    (each word padded with two spaces before and one after)."""
    left, right = _trigrams(a), _trigrams(b)
    if not left or not right:
        return 0.0
    shared = len(left & right)
    return shared / (len(left) + len(right) - shared)


def word_similarity(a: str, b: str) -> float:
    """pg_trgm's word_similarity(a, b), on word boundaries: the best similarity of a with a
    run of consecutive words of b (« Coopérative » in « Coopérative Agronomique »: 1)."""
    words = _WORDS.findall(b.lower())
    return max(
        (
            trigram_similarity(a, " ".join(words[i:j]))
            for i in range(len(words))
            for j in range(i + 1, len(words) + 1)
        ),
        default=0.0,
    )


async def _columns(conn, table: str) -> set[str]:
    rows = await conn.fetch(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1""",
        table,
    )
    return {r["column_name"] for r in rows}


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


async def _games(conn, game: UUID | None):
    language = "gm.language" if "language" in await _columns(conn, "games") else "NULL"
    return await conn.fetch(
        f"""SELECT gm.id, gm.name, gr.slug AS genre, {language} AS language
              FROM games AS gm LEFT JOIN genres AS gr ON gr.id = gm.genre_id
             WHERE $1::uuid IS NULL OR gm.id = $1
             ORDER BY gm.created_at, gm.id""",
        game,
    )


async def _entities(conn, game_id: UUID) -> list[Entity]:
    """The domain rows of a game, as the migration's first steps leave them."""
    char_cols = await _columns(conn, "characters")
    seen = "unknown_name" if "unknown_name" in char_cols else "descriptor"
    true_name = "true_name" if "true_name" in char_cols else "name"
    suffix = "label_suffix" if "label_suffix" in char_cols else "NULL"
    canonical = (
        "canonical_name"
        if "canonical_name" in await _columns(conn, "objects")
        else "NULL"
    )
    entities = [
        Entity(
            id=r["id"],
            type="character",
            name=r["base"],
            created_at=r["created_at"],
            seen=r["seen"],
            known=bool(r["known_by_protagonist"]),
            mandatory=bool(r["is_mandatory"]),
            occupation=r["occupation"],
            workplace_id=r["workplace_id"],
            label_suffix=r["suffix"],
            has_true_name=r["true_name"] is not None,
        )
        for r in await conn.fetch(
            f"""SELECT id, created_at, {seen} AS seen, {true_name} AS true_name,
                       COALESCE({true_name}, {seen}) AS base, {suffix} AS suffix,
                       known_by_protagonist, is_mandatory, occupation, workplace_id
                  FROM characters WHERE game_id = $1""",
            game_id,
        )
    ]
    for entity_type, table in DOMAIN_TABLES.items():
        if entity_type == "character":
            continue
        extra = canonical if entity_type == "object" else "NULL"
        entities += [
            Entity(
                id=r["id"],
                type=entity_type,
                name=r["name"],
                created_at=r["created_at"],
                canonical=r["canonical"],
            )
            for r in await conn.fetch(
                f"""SELECT id, name, created_at, {extra} AS canonical
                      FROM {table} WHERE game_id = $1""",
                game_id,
            )
        ]
    return sorted(entities, key=lambda e: (e.created_at or datetime.min, e.name, e.id))


async def _edges(conn, game_id: UUID) -> Counter:
    union = " UNION ALL ".join(
        f"SELECT {column} AS id FROM {table}" for table, column in EDGE_COLUMNS
    )
    rows = await conn.fetch(
        f"""SELECT edge.id, count(*) AS n FROM ({union}) AS edge
             WHERE edge.id IN (SELECT id FROM entity_registry WHERE game_id = $1)
             GROUP BY edge.id""",
        game_id,
    )
    return Counter({r["id"]: r["n"] for r in rows})


def _alias_norms(entity: Entity, norm) -> set[str]:
    forms = [entity.label, entity.canonical, *entity.former]
    if entity.type == "character":
        forms += [entity.name if entity.has_true_name else None, entity.seen]
    return {norm(f) for f in forms if f and f.strip()}


def _resolve(entities: list[Entity], ref: str, entity_type: str, norm) -> Entity | None:
    """find_entity on the names and aliases the migration gives (labels and aliases
    together, two candidates or more: None)."""
    of_type = [e for e in entities if e.type == entity_type]
    if ref.strip().upper() in RESERVED_REFS and ref.strip().lower() == entity_type:
        return of_type[0] if len(of_type) == 1 else None
    key = norm(ref)
    found = [e for e in of_type if key in _alias_norms(e, norm)]
    return found[0] if len(found) == 1 else None


def _reidentify(report: GameReport, entities, registry) -> list:
    """Step 1: pairs registry rows with domain rows (by id, else by type and label); the
    registry rows left are the orphans, the domain rows left get a registry row."""
    by_id = {e.id: e for e in entities}
    by_label = {(e.type, e.label): e for e in entities}
    registry_ids = {r["id"] for r in registry}
    matched, orphans = set(), []
    for row in registry:
        entity = by_id.get(row["id"])
        if entity is not None and entity.type == row["entity_type"]:
            matched.add(entity.id)
            continue
        entity = by_label.get((row["entity_type"], row["name"]))
        if entity is not None and entity.id not in registry_ids | matched:
            matched.add(entity.id)
            report.reidentified += 1
        else:
            orphans.append(row)
    report.registered = [(e.type, e.label) for e in entities if e.id not in matched]
    return orphans


def _orphans(report: GameReport, orphans, entities, edges: Counter, norm) -> None:
    for row in orphans:
        target = _resolve(entities, row["name"], row["entity_type"], norm)
        report.orphans.append(
            (
                row["entity_type"],
                row["name"],
                edges[row["id"]],
                target.label if target else None,
            )
        )


def _collisions(report: GameReport, entities: list[Entity], norm) -> None:
    """Step c of identity_legacy_normalise: of the entities of a type sharing a norm, the
    oldest keeps its name, the others get " (2)", " (3)"..."""
    groups: dict[tuple[str, str], list[Entity]] = {}
    for entity in entities:  # oldest first
        groups.setdefault((entity.type, norm(entity.label)), []).append(entity)
    for (entity_type, _), group in groups.items():
        for rank, entity in enumerate(group[1:], start=2):
            taken = {norm(e.label) for e in entities if e.type == entity_type}
            suffix = rank
            while norm(f"{entity.label} ({suffix})") in taken:
                suffix += 1
            before = entity.label
            if entity.type == "character":
                entity.label_suffix = str(suffix)
            else:
                entity.former.append(entity.name)
                entity.name = f"{entity.name} ({suffix})"
            report.collisions.append(
                (entity_type, group[0].label, before, entity.label)
            )


def _mentions(report: GameReport, messages, entities, norm) -> None:
    for message in messages:
        spans = _json(message["narrator_context"])
        for span in spans if isinstance(spans, list) else []:
            if not (
                isinstance(span, list)
                and len(span) >= 4
                and all(isinstance(v, int | float) for v in span[:2])
                and all(isinstance(v, str) for v in span[2:4])
            ):
                continue
            if _resolve(entities, span[2], span[3], norm):
                report.mentions_kept += 1
            else:
                report.mentions_dropped[(span[2], span[3])] += 1


def _classify(report: GameReport, entities: list[Entity], normalizer, lexicon) -> None:
    from services.identity.classify import LegacyCharacter, plan_classification

    characters = [e for e in entities if e.type == "character"]
    plan = plan_classification(
        [
            LegacyCharacter(
                id=e.id,
                name=e.name,
                descriptor=e.seen,
                settled=e.known or not e.has_true_name,
                label_suffix=e.label_suffix,
                label_norm=normalizer.norm(e.label),
            )
            for e in characters
        ],
        normalizer,
        lexicon,
    )
    by_id = {e.id: e for e in characters}
    mandatory = {e.id for e in characters if e.mandatory}
    for character, verdict, write in plan:
        report.classification.append(
            (character.id, character.name, character.descriptor, verdict)
        )
        if write:
            entity = by_id[character.id]
            entity.former.append(entity.name)
            entity.name, entity.has_true_name = verdict.descriptor, False
            entity.label_suffix = write.label_suffix
            if write.label_suffix != character.label_suffix:
                report.collisions.append(
                    ("character", None, character.name, entity.label)
                )
        # The migration marks a mandatory unknown character's true name secret.
        if verdict.kind == "true_name" and character.id in mandatory:
            report.secrets.append(character.name)


def _duplicate_reason(
    left: Entity, right: Entity, norm, threshold: float
) -> str | None:
    """Why two entities of a type may be one (spec §5.2 step 6), or None: names alike
    (similarity, or one name inside the other), the same occupation at the same place, or
    a character's descriptor that names the other's occupation."""
    a, b = norm(left.name), norm(right.name)
    score = max(trigram_similarity(a, b), word_similarity(a, b), word_similarity(b, a))
    if score >= threshold:
        return f"noms proches ({score:.2f})"
    if left.type != "character":
        return None
    jobs = norm(left.occupation or ""), norm(right.occupation or "")
    if (
        all(jobs)
        and left.workplace_id
        and left.workplace_id == right.workplace_id
        and word_similarity(min(jobs, key=len), max(jobs, key=len)) >= threshold
    ):
        return "même métier, même lieu"
    for described, other, job in ((left, right, jobs[1]), (right, left, jobs[0])):
        if (
            not described.has_true_name
            and job
            and word_similarity(norm(described.name), job) >= threshold
        ):
            return f"descripteur ≈ métier de {other.name}"
    return None


def _duplicates(
    report: GameReport, entities: list[Entity], norm, threshold: float
) -> None:
    for i, left in enumerate(entities):
        for right in entities[i + 1 :]:
            if left.type == right.type and (
                why := _duplicate_reason(left, right, norm, threshold)
            ):
                report.duplicates.append((left.type, left.name, right.name, why))


async def build_report(conn, game: UUID | None = None) -> list[GameReport]:
    """What the migration and the backfill will do, game by game (read only)."""
    from config import get_identity_config
    from packs.loader import load_lang
    from services.identity.lexicon import for_game
    from services.identity.normalize import Normalizer

    config = get_identity_config()
    reports = []
    for row in await _games(conn, game):
        language = row["language"] or config.default_language
        normalizer = Normalizer(load_lang(language))
        lexicon = for_game(language, row["genre"])
        report = GameReport(row["id"], row["name"] or "", language)
        entities = await _entities(conn, row["id"])
        registry = await conn.fetch(
            "SELECT id, entity_type, name FROM entity_registry WHERE game_id = $1"
            " ORDER BY entity_type, name, id",
            row["id"],
        )
        orphans = _reidentify(report, entities, registry)
        _orphans(
            report, orphans, entities, await _edges(conn, row["id"]), normalizer.norm
        )
        _collisions(report, entities, normalizer.norm)
        messages = await conn.fetch(
            "SELECT narrator_context FROM messages WHERE game_id = $1"
            " AND narrator_context IS NOT NULL ORDER BY sequence",
            row["id"],
        )
        _mentions(report, messages, entities, normalizer.norm)
        _classify(report, entities, normalizer, lexicon)
        report.secret_facts = [
            (r["cycle"], r["description"])
            for r in await conn.fetch(
                "SELECT cycle, description FROM facts WHERE game_id = $1 AND type = 'secret'"
                " ORDER BY created_at",
                row["id"],
            )
        ]
        _duplicates(report, entities, normalizer.norm, config.probable_duplicate)
        reports.append(report)
    return reports


def _cell(text) -> str:
    return str(text if text is not None else "—").replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: list[list]) -> list[str]:
    if not rows:
        return ["Aucun.", ""]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return [*lines, ""]


def render(reports: list[GameReport]) -> str:
    """The report as Markdown: one block per game, the eight sections in each."""
    lines = ["# Rapport à blanc de la migration d'identité (#152)", ""]
    if not reports:
        lines.append("Aucune partie.")
    for r in reports:
        lines += [f"## Partie {r.title} (`{r.game_id}`), langue `{r.language}`", ""]
        lines += [f"### {SECTIONS[0]}", ""]
        lines += [
            f"{r.reidentified} ligne(s) de registre prennent l'id de leur ligne métier.",
            "",
        ]
        lines += _table(
            ["entité", "nouvelle ligne de registre"], [list(x) for x in r.registered]
        )
        lines += [f"### {SECTIONS[1]}", ""]
        lines += _table(
            ["entité", "nom", "arêtes", "devenir"],
            [
                [
                    t,
                    n,
                    e,
                    f"re-pointé vers {target}"
                    if target
                    else "supprimé (arêtes perdues)",
                ]
                for t, n, e, target in r.orphans
            ],
        )
        lines += [f"### {SECTIONS[2]}", ""]
        lines += _table(
            ["id", "name", "unknown_name", "verdict", "remarque"],
            [
                [
                    str(i),
                    n,
                    u,
                    "vrai nom"
                    if v.kind == "true_name"
                    else f"descripteur : {v.descriptor}",
                    "à vérifier" if v.to_check else "",
                ]
                for i, n, u, v in r.classification
            ],
        )
        lines += [
            f"### {SECTIONS[3]}",
            "",
            "Vrai nom marqué secret (PNJ obligatoire inconnu) : à confirmer ou lever.",
            "",
        ]
        lines += _table(["PNJ"], [[n] for n in r.secrets])
        lines += [f"### {SECTIONS[4]}", ""]
        lines += _table(["cycle", "fait"], [list(x) for x in r.secret_facts])
        lines += [
            f"### {SECTIONS[5]}",
            "",
            f"{r.mentions_kept} mention(s) reconstruite(s) ; abandonnées :",
            "",
        ]
        lines += _table(
            ["nom", "entité", "nombre"],
            [[n, t, c] for (n, t), c in r.mentions_dropped.most_common()],
        )
        lines += [f"### {SECTIONS[6]}", "", "Jamais fusionnés automatiquement.", ""]
        lines += _table(
            ["entité", "premier nom", "second nom", "motif"],
            [list(x) for x in r.duplicates],
        )
        lines += [f"### {SECTIONS[7]}", ""]
        lines += _table(
            ["entité", "gardée", "ancien libellé", "nouveau libellé"],
            [list(x) for x in r.collisions],
        )
    return "\n".join(lines).rstrip() + "\n"


async def _main(args: argparse.Namespace) -> int:
    import asyncpg

    conn = await asyncpg.connect(
        args.database_url, server_settings={"default_transaction_read_only": "on"}
    )
    try:
        async with conn.transaction(readonly=True):
            reports = await build_report(conn, args.game)
    finally:
        await conn.close()
    text = render(reports)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--game", type=UUID, help="only this game")
    parser.add_argument("--out", type=Path, help="Markdown file (default: stdout)")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
