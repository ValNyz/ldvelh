"""L, the secret-leak check of the resolver v2 (#154, spec § 3.4 bis, ANNOTATION § 7.3).

A secret name of a scene is a name its gold knowledge marks secret (`kind: name`,
`state: secret`) or an alias the world flags secret (the alias or its whole entity),
unless an open name disclosure of the scene lets it through. Inside a known, non-secret
name of another entity (a place named after the person whose identity is the secret) the
word discloses nothing: those spans are masked before searching, and the card of such an
entity (the line whose label holds that name, with the forms the app derives from it) is
left out; everywhere else
the name counts, on its holder's own card first of all. The resolver leaks it when
a candidate card shows it (the app never shows a secret alias without an open
disclosure, even one the narration contains), or when the rest of a request or a
model's output holds it while the narration does not (an echo of the text the resolver
reads is not its leak; a narrator leak is judged elsewhere).

Names are compared as whole words, case- and accent-insensitively (the pack folding of
the scene's language). The count is the number of (scene, secret name) pairs leaked: the
names themselves are never printed.
"""

from __future__ import annotations

import re
from functools import lru_cache

from config import get_identity_config
from evals.identity.corpus import Scene
from packs.loader import load_lang
from services.identity.mentions import find_spans
from services.identity.normalize import Normalizer

_QUOTED = re.compile(r'"([^"]*)"')
SECRET = "secret"
NAME = "name"


@lru_cache
def _normalizer(language: str) -> Normalizer:
    return Normalizer(load_lang(language), get_identity_config())


def _secret_owners(scene: Scene) -> dict[str, str | None]:
    """Each undisclosed secret name of `scene` and the world id that holds it."""
    disclosed = {d.handle for d in scene.scene.open_disclosures if d.kind == NAME}
    owners: dict[str, str | None] = {
        k.text: k.ref
        for k in scene.gold_knowledge
        if k.kind == NAME and k.state == SECRET and k.ref not in disclosed
    }
    for entity in scene.world:
        if entity.id in disclosed:
            continue
        for a in entity.aliases:
            if a.secret or entity.secret:
                owners.setdefault(a.text, entity.id)
    return {name: owner for name, owner in owners.items() if name.strip()}


def secret_names(scene: Scene) -> list[str]:
    """Every undisclosed secret name of `scene` (see the module doc)."""
    return list(_secret_owners(scene))


def _others_known(scene: Scene, holder: str | None) -> list[str]:
    """The known, non-secret names of the entities other than `holder`."""
    return [
        a.text
        for e in scene.world
        if e.id != holder and not e.secret
        for a in e.aliases
        if a.known and not a.secret
    ]


def _masked(text: str, names: list[str], normalizer: Normalizer) -> str:
    """`text` with every span of `names` blanked: a secret word inside another entity's
    known name (a place named after the secret person) discloses nothing there."""
    chars = list(text)
    for name in names:
        for start, end in find_spans(text, name, normalizer):
            chars[start:end] = " " * (end - start)
    return "".join(chars)


def _in(name: str, texts: list[str], normalizer: Normalizer) -> bool:
    return any(find_spans(text, name, normalizer) for text in texts)


def leak_count(scene: Scene, cards: list[str], texts: list[str]) -> int:
    """How many secret names of `scene` a card shows, or the other request text and
    the outputs hold while the narration does not. The spans of the other entities'
    known names are masked first (on a card, only those longer than the secret name);
    the holder's own names never are."""
    normalizer = _normalizer(scene.language)
    count = 0
    for name, holder in _secret_owners(scene).items():
        others = _others_known(scene, holder)
        # Another entity's known names that hold the word: its card line (the name and
        # the forms the app derives from it) discloses nothing.
        bearers = [n for n in others if find_spans(n, name, normalizer)]
        # On a card, only a longer name holding the word is masked: another entity's
        # name equal to the secret one never hides it on its holder's own card.
        longer = [
            n for n in bearers if len(normalizer.norm(n)) > len(normalizer.norm(name))
        ]

        def seen(texts: list[str], masks: list[str]) -> bool:
            return _in(name, [_masked(t, masks, normalizer) for t in texts], normalizer)

        own_cards = [
            c for c in cards if not _in_any(bearers, _card_label(c), normalizer)
        ]
        count += seen(own_cards, longer) or (
            not seen([scene.narration], others) and seen(texts, others)
        )
    return count


def _card_label(line: str) -> str:
    """The label of a card line: its first quoted string (after the handle and type)."""
    match = _QUOTED.search(line)
    return match.group(1) if match else ""


def _in_any(names: list[str], text: str, normalizer: Normalizer) -> bool:
    return any(find_spans(text, n, normalizer) for n in names)
