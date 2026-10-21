"""The deterministic prepass of the resolver v2 (spec §4.5.5 step 1): no model call.

It links every run of words of the turn's text whose normalised form names exactly one
candidate (`CandidateSet.exact`), longest run first, left to right; an exact name the
protagonist does not know yet, written in full, is revealed (ALIAS true_name, ruling R36);
an unknown short form alone reveals nothing. Each decision carries the offset of its
occurrence (`start`), the only span it takes; a leading article or elision the matched
name does not hold stays out of that span. It leaves to the model a name the text
continues (a number, a capitalised word where case marks names), a name after a word
announcing another entity (pack `other_markers`), a short form that the text writes, or
that is stored, as a common noun, and a short form right after a capitalised word opening
the sentence (neither an article nor a title: the case tells nothing there); the last two
are returned as doubts, the model's TO CHECK lines.
"""

from __future__ import annotations

import re
from dataclasses import replace
from uuid import UUID

from config import IdentityConfig, get_identity_config
from domain.identity import DECISIONS, Candidate, CandidateSet, MentionDecision
from prompts.identity_prompt import format_handle
from services.identity.mentions import WORD
from services.identity.normalize import Normalizer

MATCH, ALIAS, _, UNSURE, _ = DECISIONS
TRUE_NAME = "true_name"
SHORT = "short"
# Stored kinds of a name (not a description nor a short form): unknown, it is the name the
# narration reveals.
UNKNOWN_NAME_KINDS = frozenset({TRUE_NAME, "label"})
# Characters read after a name for an ordinal marker and its number.
_AHEAD = 32


def _joins(normalizer: Normalizer) -> re.Pattern[str]:
    """What may stand between two words of one name: spaces, apostrophes, hyphens and the
    signs of the pack's ordinal markers (never a sentence break)."""
    signs = {
        ch
        for marker in normalizer.pack.ordinal_markers
        for ch in marker
        if not ch.isalnum() and not ch.isspace()
    }
    allowed = "".join(
        re.escape(ch) for ch in {*normalizer.pack.apostrophes, "-", *signs}
    )
    return re.compile(rf"[\s{allowed}]*")


def _capitalised(word: str) -> bool:
    return word[:1].isupper()


class _Runs:
    """The words of a text and what stands around a run of them, for the prepass."""

    def __init__(self, text: str, normalizer: Normalizer, reach: int) -> None:
        self.text, self.normalizer, self.reach = text, normalizer, reach
        self.words = list(WORD.finditer(text))
        self.joins = _joins(normalizer)
        # Between two words of one phrase around a name: spaces, apostrophes, hyphens;
        # never a sign that may end a sentence (an ordinal sign such as a dot).
        quotes = "".join(re.escape(ch) for ch in normalizer.pack.apostrophes)
        self.tight = re.compile(rf"[\s{quotes}-]*")
        pack = normalizer.pack
        self.articles = set(normalizer.folded_entries([*pack.articles, *pack.elisions]))
        self.titles = set(normalizer.folded_entries(pack.titles))
        self.others = set(normalizer.folded_entries(pack.other_markers))
        self.capitals = pack.case_marks_names

    def adjacent(self, left: int, right: int) -> bool:
        """Words `left` and `right` sit in one phrase: only spaces, apostrophes or hyphens
        between them (the continuation and "another" rules read no further)."""
        gap = self.text[self.words[left].end() : self.words[right].start()]
        return bool(self.tight.fullmatch(gap))

    def joined(self, left: int, right: int) -> bool:
        """Words `left` and `right` (= left + 1) are one run: nothing but joins between."""
        gap = self.text[self.words[left].end() : self.words[right].start()]
        return bool(self.joins.fullmatch(gap))

    def folded(self, i: int) -> str:
        return self.normalizer.fold(self.words[i].group()).strip()

    def continued(self, first: int, end: int) -> bool:
        """The name in words [first, end) is part of a longer one the text writes: a
        number right after it (or after an ordinal marker of the pack: « Quai n°9 »),
        or (where letter case marks names) a capitalised word right after it (past
        articles), or before it in mid-sentence (a title aside)."""
        stop = self.words[end - 1].end()
        tail = self.text[stop : stop + _AHEAD]
        if self.normalizer.opens_with_number(tail):
            return True  # an ordinal marker of the pack, then a number
        after = end
        while after < len(self.words) and self.adjacent(after - 1, after):
            word = self.words[after].group()
            if word[:1].isdigit():
                return True
            if not self.capitals:
                break
            if self.folded(after) not in self.articles:
                if _capitalised(word):
                    return True
                break
            after += 1
        return self.capitals and self._capitalised_before(first)

    def _name_before(self, first: int) -> int | None:
        """The word right before the run, in the same phrase, when it is capitalised and
        neither an article nor a title of the pack (None otherwise)."""
        before = first - 1
        if before < 0 or not self.adjacent(before, first):
            return None
        folded = self.folded(before)
        if (
            not _capitalised(self.words[before].group())
            or folded in self.titles
            or folded in self.articles
        ):
            return None
        return before

    def _opens_sentence(self, i: int) -> bool:
        """Word `i` starts the text or a phrase (nothing tight links it to the one before)."""
        return i == 0 or not self.adjacent(i - 1, i)

    def _capitalised_before(self, first: int) -> bool:
        before = self._name_before(first)
        return before is not None and not self._opens_sentence(before)

    def short_after_opening_name(self, first: int, c: Candidate, norm: str) -> bool:
        """Where letter case marks names, a short form right after a capitalised word that
        opens the sentence (« Elara Voss entre ») may be the end of another name, or
        follow a capitalised adverb: the case says nothing at a sentence start, so the
        model decides it (a doubt, never a link)."""
        alias = _matched(c, norm)
        if not self.capitals or alias is None or alias.kind != SHORT:
            return False
        before = self._name_before(first)
        return before is not None and self._opens_sentence(before)

    def name_start(self, first: int, end: int, c: Candidate, norm: str) -> int:
        """The first word of the decided name in words [first, end): a leading article or
        elision that the matched name does not hold is left out of its span (it stays
        among the words before)."""
        if end <= first + 1 or _holds_article(c, norm, self.normalizer):
            return first
        rest = self.text[self.words[first + 1].start() : self.words[end - 1].end()]
        return first + 1 if self.normalizer.norm(rest) == norm else first

    def common_use(self, surface: str, c: Candidate, norm: str) -> bool:
        """A short form maybe written as a common noun. Where letter case marks names
        (the pack's case_marks_names), a capitalised stored short form (a word of a name
        or of a label) the text writes in lower case is not used as a name, and a short
        form stored in lower case is a common word; where case marks nothing, a short form
        can never be told from a common noun. Either way it never links alone."""
        alias = _matched(c, norm)
        if alias is None or alias.kind != SHORT:
            return False
        if not self.capitals or not any(_capitalised(w) for w in alias.alias.split()):
            # Without case, or stored in lower case (a common word of a label, never a
            # name): nothing shows a name use.
            return True
        # The stored words against the written ones from the end: a leading determiner
        # (capitalised at a sentence start) is never compared.
        stored, written = alias.alias.split(), surface.split()
        return any(
            _capitalised(a) and b[:1].islower()
            for a, b in zip(reversed(stored), reversed(written))
        )

    def announced_other(self, first: int) -> bool:
        """One of the `reach` words before the run announces another entity of its kind."""
        reach = range(max(0, first - self.reach), first)
        return any(
            self.folded(i) in self.others
            and all(self.adjacent(j, j + 1) for j in range(i, first))
            for i in reach
        )


def _matched(c: Candidate, norm: str):
    """The alias of `c` an exact form matches (None: none of its aliases)."""
    return next((a for a in c.aliases if a.alias_norm == norm), None)


def _holds_article(c: Candidate, norm: str, normalizer: Normalizer) -> bool:
    """A stored name of `c` with the normalised form `norm` starts with an article or an
    elision (« la clé d'os »): the written one keeps its own."""
    names = [a.alias for a in c.aliases if a.alias_norm == norm]
    if normalizer.norm(c.label) == norm:
        names.append(c.label)
    return any(normalizer.key(name) != norm for name in names)


def _unknown_alias(c: Candidate, norm: str):
    """The alias of `c` an exact form matches when the protagonist does not know it."""
    alias = _matched(c, norm)
    return alias if alias is not None and not alias.known else None


def _exact(
    surface: str,
    before: str,
    c: Candidate,
    norm: str,
    revealed: set[UUID],
    start: int,
) -> MentionDecision:
    """The prepass decision on the exact form of `c` at `start`: MATCH; for a name the
    protagonist does not know, written in full (a true name, a label), ALIAS true_name
    that reveals that very name; after it, an unknown short form of the same entity is an
    ALIAS short. An unknown short form alone reveals nothing (the full name was never
    read): a plain MATCH."""
    base = MentionDecision(
        surface=surface,
        decision=MATCH,
        before=before,
        handle=format_handle(c.handle),
        entity_id=c.entity_id,
        verified=True,
        deterministic=True,
        start=start,
    )
    alias = _unknown_alias(c, norm)
    if alias is None:
        return base
    if alias.kind in UNKNOWN_NAME_KINDS:
        revealed.add(c.entity_id)
        return replace(
            base, decision=ALIAS, alias_kind=TRUE_NAME, revealed_name=alias.alias
        )
    if alias.kind == SHORT and c.entity_id in revealed:
        return replace(base, decision=ALIAS, alias_kind=SHORT)
    return base


def _decision(
    runs: _Runs,
    i: int,
    end: int,
    c: Candidate,
    norm: str,
    revealed: set[UUID],
    config: IdentityConfig,
) -> MentionDecision:
    """The prepass decision on words [i, end), its span without a leading article the
    matched name does not hold."""
    words = runs.words
    first = runs.name_start(i, end, c, norm)
    surface = runs.text[words[first].start() : words[end - 1].end()]
    before = " ".join(
        w.group() for w in words[max(0, first - config.before_words) : first]
    )
    return _exact(surface, before, c, norm, revealed, words[first].start())


def scan(
    text: str,
    candidates: CandidateSet,
    *,
    normalizer: Normalizer,
    config: IdentityConfig | None = None,
) -> tuple[list[MentionDecision], list[MentionDecision]]:
    """(the prepass decisions, the doubts): a doubt is an exact short form the prepass
    leaves because the text writes it as a common noun; the model is asked to decide it
    (TO CHECK), so that it is not left out."""
    if not candidates.exact:
        return [], []
    config = config or get_identity_config()
    longest = max(len(norm.split()) for norm in candidates.exact)
    # A name's words, plus as many glued or leading words (article, elision, ordinal).
    reach = longest + longest + 1
    runs = _Runs(text, normalizer, config.other_marker_reach)
    words = runs.words
    found: list[MentionDecision] = []
    doubts: list[MentionDecision] = []
    revealed: set[UUID] = set()
    i = 0
    while i < len(words):
        hit = None
        for last in range(i, min(len(words), i + reach)):
            if last > i and not runs.joined(last - 1, last):
                break
            surface = text[words[i].start() : words[last].end()]
            norm = normalizer.norm(surface)
            c = candidates.exact.get(norm)
            if c is not None:
                hit = (last + 1, surface, c, norm)
        if hit is None:
            i += 1
            continue
        end, surface, c, norm = hit
        start = max(0, i - config.before_words)
        if runs.continued(i, end) or runs.announced_other(i):
            pass  # likely another entity: the model decides it unprompted
        elif runs.common_use(surface, c, norm) or runs.short_after_opening_name(
            i, c, norm
        ):
            # Shown to the model as written: the words before, punctuation included.
            written = " ".join(text[words[start].start() : words[i].start()].split())
            doubt = MentionDecision(
                surface,
                UNSURE,
                written,
                handle=format_handle(c.handle),
                start=words[i].start(),
            )
            doubts.append(doubt)
        else:
            found.append(_decision(runs, i, end, c, norm, revealed, config))
        i = end
    return found, doubts
