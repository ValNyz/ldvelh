"""Closed word lists of a language, read from evals/identity/lexicon/<language>.yaml (#151).

The corpus code is language-agnostic: determiners, personal pronouns and the
indefinite/demonstrative pronouns of ANNOTATION § 4.1 and § 5.2 come from the lexicon of
the scene's `language`. Words are stored with a straight apostrophe; the typographic
apostrophe of a text is folded into it before comparing.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

LEXICON_DIR = Path(__file__).resolve().parent / "lexicon"
DEFAULT_LANGUAGE = "fr"
APOSTROPHES = "'’"


def fold_apostrophes(text: str) -> str:
    return text.replace(APOSTROPHES[1], APOSTROPHES[0])


class Lexicon(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    determiners: frozenset[str]
    elided_determiners: frozenset[str]
    personal_pronouns: frozenset[str]
    indefinite_pronouns: frozenset[str]
    unambiguous_pronouns: frozenset[str]

    def key(self, surface: str) -> str:
        return fold_apostrophes(surface.strip()).casefold()

    def strip_determiner(self, text: str) -> str:
        """Drop one leading determiner, keep case and accents (apostrophes folded)."""
        text = fold_apostrophes(text.strip())
        lowered = text.casefold()
        for elided in self.elided_determiners:
            if lowered.startswith(elided):
                return text[len(elided) :].lstrip()
        head, _, rest = text.partition(" ")
        return rest.lstrip() if head.casefold() in self.determiners and rest else text

    @property
    def unambiguous_pronoun_re(self) -> re.Pattern[str] | None:
        """Whole-word occurrences of the unambiguous pronouns (None when there are none)."""
        return _pronoun_re(self.unambiguous_pronouns)


@lru_cache
def _pronoun_re(forms: frozenset[str]) -> re.Pattern[str] | None:
    if not forms:
        return None
    quote = f"[{APOSTROPHES}]"
    ordered = sorted(forms, key=len, reverse=True)
    body = "|".join(re.escape(f).replace(APOSTROPHES[0], quote) for f in ordered)
    return re.compile(rf"(?<![\w{APOSTROPHES}-])({body})(?![\w-])", re.IGNORECASE)


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
