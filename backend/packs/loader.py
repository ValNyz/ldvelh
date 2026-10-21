"""Single loader of the language and genre packs (spec §4.12, D33-D36).

A language pack (`packs/lang/<lang>.yaml`) holds every word the identity code compares
with; a genre pack (`packs/genre/<slug>.yaml`) adds the words of a universe in its optional
`identity` section. Both are validated at load: a missing or unknown key is an error, and
the backend refuses to start (startup_checks). `sync_lang_packs` copies the parameters the
SQL side reads (`sql_params`) of every language pack into `lang_packs`, where `ldvelh_norm`
and `display_for_player` read them.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

PACKS_DIR = Path(__file__).resolve().parent
LANG_DIR = PACKS_DIR / "lang"
GENRE_DIR = PACKS_DIR / "genre"
NEUTRAL_GENRE = "_neutral"
# Pack file names (language codes, genre slugs); also keeps paths inside the pack folders.
SLUG = re.compile(r"^[a-z_][a-z0-9_-]*$")


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

    @field_validator("personal", "demonstrative", "indefinite")
    @classmethod
    def _non_empty(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return _check_entries(f"pronouns.{info.field_name}", value, one_word=False)


class LangExamples(_Strict):
    identity: list[Example]
    # Proposals of the extraction prompts (proposed_entities), in the game's language.
    extraction: list[Example]


def _check_entries(field: str, value: list[str], *, one_word: bool) -> list[str]:
    for entry in value:
        if not entry.strip():
            raise ValueError(f"{field}: empty entry")
        if one_word and len(entry.split()) > 1:
            # The code compares these with a single word: a longer entry would never match.
            raise ValueError(f"{field}: {entry!r} must be a single word")
    return value


_ONE_WORD_KEYS = (
    "articles",
    "elisions",
    "titles",
    "ordinal_markers",
    "other_markers",
    "plural_markers",
)
_PHRASE_KEYS = (
    "stop_words",
    "descriptor_heads",
    "reveal_cues",
    "source_cues",
    "negative_answers",
)


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
    negative_answers: list[str]
    plural_markers: list[str]
    ordinal_markers: list[str]
    other_markers: list[str]
    apostrophes: list[str]
    unknown_character_label: str
    unknown_entity_label: str
    tooltip_labels: dict[str, str]
    proper_name_uses_capitals: bool
    case_marks_names: bool
    min_distinctive_token_len: int
    prompt_examples: LangExamples

    @field_validator("apostrophes")
    @classmethod
    def _single_characters(cls, value: list[str]) -> list[str]:
        if not value or any(len(a) != 1 for a in value):
            raise ValueError("apostrophes: a non-empty list of single characters")
        return value

    @field_validator(*_ONE_WORD_KEYS)
    @classmethod
    def _single_words(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return _check_entries(info.field_name, value, one_word=True)

    @field_validator(*_PHRASE_KEYS)
    @classmethod
    def _non_empty(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return _check_entries(info.field_name, value, one_word=False)

    @field_validator("tooltip_labels")
    @classmethod
    def _labels(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not k.strip() or not v.strip() for k, v in value.items()):
            raise ValueError("tooltip_labels: a non-empty mapping of non-empty labels")
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

    @field_validator("titles_extra")
    @classmethod
    def _single_words(cls, value: list[str]) -> list[str]:
        return _check_entries("identity.titles_extra", value, one_word=True)


class GenrePack(_Strict):
    slug: str
    # The species a tooltip does not print (the usual one of the genre); None: the
    # identity config's default_species.
    default_species: str | None = None
    identity: GenreIdentity = GenreIdentity()


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pack_path(directory: Path, name: str) -> Path | None:
    path = directory / f"{name}.yaml"
    return path if SLUG.match(name) and path.is_file() else None


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


def misnamed_packs() -> list[str]:
    """Pack files whose name is not a valid slug: they could never be loaded."""
    return sorted(
        f"{p.parent.name}/{p.name}"
        for directory in (LANG_DIR, GENRE_DIR)
        for p in directory.glob("*.yaml")
        if not SLUG.match(p.stem)
    )


@lru_cache
def all_negative_answers() -> frozenset[str]:
    """The negative answers of every language pack, lower case: for parsers that read model
    output without a game (hence without a language) at hand."""
    return frozenset(
        a.strip().lower()
        for lang in available_langs()
        for a in load_lang(lang).negative_answers
    )


def norm_params(pack: LangPack) -> dict[str, list[str] | bool]:
    """The parameters of ldvelh_norm (see sql_params for all the SQL side reads). Entries are
    given folded (steps 1-2 of the normalisation), without duplicates, longest first, so
    that the SQL function compares them as they are instead of folding them on each call;
    `folded` marks them so, and ldvelh_norm raises without it."""
    from services.identity.normalize import Normalizer

    normalizer = Normalizer(pack)
    return {
        "articles": normalizer.folded_entries(pack.articles),
        "elisions": normalizer.folded_entries(pack.elisions),
        "ordinal_markers": normalizer.folded_entries(pack.ordinal_markers),
        "apostrophes": pack.apostrophes,
        # ldvelh_norm refuses params without this mark: unfolded entries would never match.
        "folded": True,
    }


def sql_params(pack: LangPack) -> dict[str, list[str] | bool | str]:
    """What lang_packs holds for the SQL side: the parameters of ldvelh_norm and the label
    display_for_player shows for a character with neither a known name nor a descriptor."""
    return {
        **norm_params(pack),
        "unknown_character_label": pack.unknown_character_label,
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
            json.dumps(sql_params(pack)),
        )
    return len(langs)
