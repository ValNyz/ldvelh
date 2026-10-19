"""Closed word lists of a language, read from evals/identity/lexicon/<language>.yaml (#151).

The corpus code is language-agnostic: determiners, personal pronouns, the
indefinite/demonstrative pronouns of ANNOTATION § 4.1 and § 5.2 and the apostrophes come
from the lexicon of the scene's `language`. Words are stored with the first apostrophe
of the list; the other apostrophes of a text are folded into it before comparing.

Assumption of the lexicon format: a determiner is a separate word (followed by a space)
or one of `elided_determiners`, glued to the noun. A language that writes determiners
otherwise (clitics, suffixes) needs a new key here.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

LEXICON_DIR = Path(__file__).resolve().parent / "lexicon"
DEFAULT_LANGUAGE = "fr"


class Lexicon(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    apostrophes: tuple[str, ...]  # the first is the one the word lists use
    determiners: frozenset[str]
    elided_determiners: frozenset[str]
    personal_pronouns: frozenset[str]
    indefinite_pronouns: frozenset[str]
    unambiguous_pronouns: frozenset[str]

    @field_validator("apostrophes")
    @classmethod
    def _single_characters(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(len(a) != 1 for a in value):
            raise ValueError("apostrophes: a non-empty list of single characters")
        return value

    def fold(self, text: str) -> str:
        """Every apostrophe of `text` as the first one of the lexicon."""
        for other in self.apostrophes[1:]:
            text = text.replace(other, self.apostrophes[0])
        return text

    def key(self, surface: str) -> str:
        return self.fold(surface.strip()).casefold()

    def strip_determiner(self, text: str) -> str:
        """Drop one leading determiner, keep case and accents (apostrophes folded)."""
        text = self.fold(text.strip())
        lowered = text.casefold()
        for elided in self.elided_determiners:
            if lowered.startswith(elided):
                return text[len(elided) :].lstrip()
        head, _, rest = text.partition(" ")
        return rest.lstrip() if head.casefold() in self.determiners and rest else text

    @property
    def unambiguous_pronoun_re(self) -> re.Pattern[str] | None:
        """Whole-word occurrences of the unambiguous pronouns (None when there are none)."""
        return _pronoun_re(self.unambiguous_pronouns, self.apostrophes)


@lru_cache
def _pronoun_re(
    forms: frozenset[str], apostrophes: tuple[str, ...]
) -> re.Pattern[str] | None:
    if not forms:
        return None
    quotes = "".join(re.escape(a) for a in apostrophes)
    ordered = sorted(forms, key=len, reverse=True)
    body = "|".join(
        re.escape(f).replace(re.escape(apostrophes[0]), f"[{quotes}]") for f in ordered
    )
    return re.compile(rf"(?<![\w{quotes}-])({body})(?![\w-])", re.IGNORECASE)


_LEXICONS: dict[str, Lexicon] = {}


def has_lexicon(language: str) -> bool:
    return language in _LEXICONS or (LEXICON_DIR / f"{language}.yaml").is_file()


def load_lexicon(language: str) -> Lexicon:
    """The lexicon of `language` (cached); ValueError when there is none."""
    if language not in _LEXICONS:
        path = LEXICON_DIR / f"{language}.yaml"
        if not path.is_file():
            raise ValueError(f"no lexicon for language {language!r} ({path})")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        _LEXICONS[language] = Lexicon.model_validate(data)
    return _LEXICONS[language]
