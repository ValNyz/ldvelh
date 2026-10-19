"""Single loader of the language and genre packs (spec §4.12, D33-D36).

A language pack (`packs/lang/<lang>.yaml`) holds every word the identity code compares
with; a genre pack (`packs/genre/<slug>.yaml`) adds the words of a universe in its optional
`identity` section. Both are validated at load: a missing or unknown key is an error, and
the backend refuses to start (startup_checks). `sync_lang_packs` copies the normalisation
parameters of every language pack into `lang_packs`, where `ldvelh_norm` reads them.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

PACKS_DIR = Path(__file__).resolve().parent
LANG_DIR = PACKS_DIR / "lang"
GENRE_DIR = PACKS_DIR / "genre"
NEUTRAL_GENRE = "_neutral"
_SLUG = re.compile(r"^[a-z_][a-z0-9_-]*$")


class PackNotFound(LookupError):
    """No pack file for this language or genre."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Example(_Strict):
    input: str
    output: str


class Pronouns(_Strict):
    personal: list[str]
    demonstrative: list[str]
    indefinite: list[str]


class LangExamples(_Strict):
    identity: list[Example]


class LangPack(_Strict):
    lang: str
    version: str
    articles: list[str]
    elisions: list[str]
    pronouns: Pronouns
    stop_words: list[str]
    titles: list[str]
    descriptor_heads: list[str]
    reveal_cues: list[str]
    source_cues: list[str]
    plural_markers: list[str]
    ordinal_markers: list[str]
    apostrophes: list[str]
    proper_name_uses_capitals: bool
    min_distinctive_token_len: int
    prompt_examples: LangExamples

    @field_validator("apostrophes")
    @classmethod
    def _single_characters(cls, value: list[str]) -> list[str]:
        if not value or any(len(a) != 1 for a in value):
            raise ValueError("apostrophes: a non-empty list of single characters")
        return value

    @field_validator("min_distinctive_token_len")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("min_distinctive_token_len must be at least 1")
        return value


class GenreIdentity(_Strict):
    titles_extra: list[str] = []
    entity_type_vocab: dict[str, list[str]] = {}
    prompt_examples: dict[str, list[Example]] = {}


class GenrePack(_Strict):
    slug: str
    identity: GenreIdentity = GenreIdentity()


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pack_path(directory: Path, name: str) -> Path | None:
    path = directory / f"{name}.yaml"
    return path if _SLUG.match(name) and path.is_file() else None


@lru_cache
def load_lang(lang: str) -> LangPack:
    """The validated pack of `lang` (cached); PackNotFound when there is none."""
    path = _pack_path(LANG_DIR, lang)
    if path is None:
        raise PackNotFound(f"no language pack {lang!r}")
    pack = LangPack.model_validate(_read(path))
    if pack.lang != lang:
        raise ValueError(f"{path.name}: lang is {pack.lang!r}, expected {lang!r}")
    return pack


@lru_cache
def load_genre(slug: str | None) -> GenrePack:
    """The validated pack of genre `slug`; the neutral pack when it has none."""
    path = _pack_path(GENRE_DIR, slug) if slug else None
    if path is None:
        path = GENRE_DIR / f"{NEUTRAL_GENRE}.yaml"
    return GenrePack.model_validate(_read(path))


def available_langs() -> list[str]:
    return sorted(p.stem for p in LANG_DIR.glob("*.yaml"))


def available_genres() -> list[str]:
    return sorted(p.stem for p in GENRE_DIR.glob("*.yaml"))


def norm_params(pack: LangPack) -> dict[str, list[str]]:
    """The parameters of ldvelh_norm: the only pack keys the SQL side reads."""
    return {
        "articles": pack.articles,
        "elisions": pack.elisions,
        "ordinal_markers": pack.ordinal_markers,
        "apostrophes": pack.apostrophes,
    }


async def sync_lang_packs(conn) -> int:
    """Upsert every language pack into lang_packs; the number of packs written."""
    langs = available_langs()
    for lang in langs:
        pack = load_lang(lang)
        # Sent as text: the connection may or may not have a jsonb codec.
        await conn.execute(
            """INSERT INTO lang_packs (lang, version, params) VALUES ($1, $2, $3::text::jsonb)
               ON CONFLICT (lang) DO UPDATE
               SET version = EXCLUDED.version, params = EXCLUDED.params, loaded_at = now()""",
            lang,
            pack.version,
            json.dumps(norm_params(pack)),
        )
    return len(langs)
