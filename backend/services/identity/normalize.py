r"""Python mirror of the SQL `ldvelh_norm(text, params)` and the name heuristics (spec §4.2-4.3).

`Normalizer(pack).norm` returns what `ldvelh_norm(text, norm_params(pack))` returns; the
parity test compares both on every pack. Steps, in this order on both sides:

1. lower case (character by character), then the `unaccent` dictionary of PostgreSQL
   (`unaccent.rules`, copied from the postgres:18 image: language-independent folding);
2. every Unicode space as a plain space, every pack apostrophe as `'`;
3. an ordinal marker of the pack dropped before a number (whole word);
4. every character other than a letter, a digit, a space, `'` or `-` replaced by a space;
5. `-` kept only between two letters (a space otherwise); spaces collapsed;
6. one leading elision (prefix) or article (whole word) of the pack dropped;
7. apostrophes removed, spaces collapsed.

Pack entries go through steps 1-2 before being compared. No word of any language here.

Parity scope: letters and digits are Python's `\w` on one side and the database ctype's
`[[:alnum:]]` (glibc) on the other. They agree on Latin, Greek and Cyrillic letters and on
decimal digits; they differ on a few symbols that are neither, such as superscript digits
(`²`) and enclosed letters (`Ⓐ`), which no name of a game is expected to hold.
"""

from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from config import IdentityConfig, get_identity_config

if TYPE_CHECKING:
    from packs.loader import LangPack
    from services.identity.lexicon import Lexicon

_UNACCENT_RULES = Path(__file__).with_name("unaccent.rules")
APOSTROPHE = "'"
# Unicode spaces folded into " " (step 2); the SQL function lists the same characters.
_SPACES = re.compile(
    "[\t\n\v\f\r\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"
)
_PUNCTUATION = re.compile(r"[^\w '-]|_")  # SQL: [^[:alnum:] '-]
_LOOSE_HYPHEN = re.compile(r"(?<![^\W\d_])-|-(?![^\W\d_])")  # SQL: [[:alpha:]] around
_RUNS_OF_SPACES = re.compile(" +")


def _parse_unaccent_rules(path: Path) -> dict[str, str]:
    """`source target` lines as PostgreSQL's unaccent reads them (quoted targets, "" escape)."""
    rules = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        target = parts[1].strip() if len(parts) > 1 else ""
        if target.startswith('"'):
            end = re.match(r'"((?:[^"]|"")*)"', target)
            target = end.group(1).replace('""', '"') if end else target
        else:
            target = target.split(None, 1)[0] if target else ""
        rules[parts[0]] = target
    return rules


_RULES = _parse_unaccent_rules(_UNACCENT_RULES)
_LONGEST_SOURCE = max(map(len, _RULES))


def unaccent(text: str) -> str:
    """PostgreSQL `unaccent('unaccent', text)`: longest rule source first, else the character."""
    out, i = [], 0
    while i < len(text):
        for size in range(min(_LONGEST_SOURCE, len(text) - i), 0, -1):
            target = _RULES.get(text[i : i + size])
            if target is not None:
                out.append(target)
                i += size
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _collapse(text: str) -> str:
    return _RUNS_OF_SPACES.sub(" ", text).strip(" ")


class Normalizer:
    """Normalisation and name heuristics of one language pack."""

    def __init__(self, pack: LangPack, config: IdentityConfig | None = None):
        self.pack = pack
        self.config = config or get_identity_config()

    # --- ldvelh_norm mirror -------------------------------------------------------------

    def fold(self, text: str) -> str:
        """Steps 1-2: lower case, unaccent, plain spaces, one apostrophe. Lower case goes
        character by character, like the database (no context rule such as a final sigma)."""
        lowered = "".join(c.lower() for c in text)
        folded = _SPACES.sub(" ", unaccent(lowered))
        for apostrophe in self.pack.apostrophes:
            folded = folded.replace(apostrophe, APOSTROPHE)
        return folded

    def folded_entries(self, entries: list[str]) -> list[str]:
        """Pack entries after steps 1-2, without duplicates, longest first."""
        folded = {self.fold(e).strip(" ") for e in entries} - {""}
        return sorted(folded, key=lambda e: (-len(e), e))

    @cached_property
    def _elisions(self) -> list[str]:
        return self.folded_entries(self.pack.elisions)

    @cached_property
    def _articles(self) -> frozenset[str]:
        return frozenset(self.folded_entries(self.pack.articles))

    @cached_property
    def _ordinal(self) -> re.Pattern[str] | None:
        markers = self.folded_entries(self.pack.ordinal_markers)
        if not markers:
            return None
        body = "|".join(re.escape(m) for m in markers)
        return re.compile(rf"(^|[\W_])({body}) *(?=[0-9])")

    def _clean(self, text: str) -> str:
        """Steps 1-5: the folded text, apostrophes still in."""
        cleaned = self.fold(text)
        if self._ordinal is not None:
            cleaned = self._ordinal.sub(r"\1", cleaned)
        cleaned = _PUNCTUATION.sub(" ", cleaned)
        cleaned = _LOOSE_HYPHEN.sub(" ", cleaned)
        return _collapse(cleaned)

    def _strip_head(self, cleaned: str) -> str:
        """Step 6: one leading elision or article, when something follows it."""
        for elision in self._elisions:
            if len(cleaned) > len(elision) and cleaned.startswith(elision):
                return cleaned[len(elision) :].lstrip(" ")
        head, _, rest = cleaned.partition(" ")
        return rest if rest and head in self._articles else cleaned

    @staticmethod
    def _finish(cleaned: str) -> str:
        """Step 7."""
        return _collapse(cleaned.replace(APOSTROPHE, ""))

    def norm(self, text: str) -> str:
        """Same output as the SQL `ldvelh_norm(text, norm_params(pack))`."""
        return self._finish(self._strip_head(self._clean(text)))

    def key(self, text: str) -> str:
        """`norm` without dropping a leading article: how pack words are compared."""
        return self._finish(self._clean(text))

    # --- words of a name ----------------------------------------------------------------

    def drop_elided(self, word: str, elided: frozenset[str]) -> str:
        """`word` without a glued elided word of `elided` (« d'Ombelle » → « Ombelle »), case
        kept; `elided` holds folded entries ending with an apostrophe."""
        cut = next((i for i, c in enumerate(word) if c in self.pack.apostrophes), None)
        if cut is None or cut == len(word) - 1:
            return word
        prefix = self.fold(word[: cut + 1]).strip(" ")
        return word[cut + 1 :] if prefix in elided else word

    def tokens(
        self, text: str, lexicon: Lexicon, *, min_len: int | None = None
    ) -> list[str]:
        """Normalised words of `text` of at least `min_len` characters (default: the
        config's `token_min_len`) to block on, elided words split off, articles, stop
        words and titles left out."""
        shortest = self.config.token_min_len if min_len is None else min_len
        words = (
            self._finish(self.drop_elided(w, lexicon.elided))
            for w in self._clean(text).split(" ")
        )
        return [
            t
            for t in words
            if len(t) >= shortest
            and t not in lexicon.stop_words
            and t not in lexicon.titles
            and t not in lexicon.articles
        ]

    def looks_like_proper_name(self, text: str, lexicon: Lexicon) -> bool:
        """A name rather than a description: no leading determiner, a first word that is not
        a descriptor head and, in a script with letter case, a capital after the first word."""
        cleaned = self._clean(text)
        if not cleaned or self._strip_head(cleaned) != cleaned:
            return False
        if self._finish(cleaned.split(" ")[0]) in lexicon.descriptor_heads:
            return False
        words = text.split()
        if self.pack.proper_name_uses_capitals and len(words) > 1:
            return any(_initial(w).isupper() for w in words[1:])
        return True

    def strip_title(self, text: str, lexicon: Lexicon) -> str:
        """`text` without its leading titles (language and genre), one word kept at least.
        A leading article goes with the titles (« Le Pater Ondrev » → « Ondrev »); without a
        title, `text` is returned as it is."""
        words = text.split()
        if words and self.key(words[0]) in lexicon.articles and len(words) > 1:
            rest = words[1:]
        elif (
            words
            and (unglued := self.drop_elided(words[0], lexicon.elisions)) != words[0]
        ):
            rest = [unglued, *words[1:]]
        else:
            rest = words
        stripped = False
        while len(rest) > 1 and self.key(rest[0]) in lexicon.titles:
            rest.pop(0)
            stripped = True
        return " ".join(rest) if stripped else " ".join(words)


def _initial(word: str) -> str:
    """First letter of a word, leading punctuation skipped."""
    return next((c for c in word if c.isalpha()), "")
