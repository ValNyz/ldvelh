"""L, the secret-leak check of the resolver v2 (#154, spec § 3.4 bis, ANNOTATION § 7.3).

A secret name of a scene is a name its gold knowledge marks secret (`kind: name`,
`state: secret`) or an alias the world flags secret (the alias or its whole entity),
unless an open name disclosure of the scene lets it through, or the world already shows it:
a name that is a whole word of a known, non-secret name of another entity (a place named
after a person whose identity is the secret) discloses nothing. The resolver leaks it when
a candidate card shows it (the app never shows a secret alias without an open
disclosure, even one the narration contains), or when the rest of a request or a
model's output holds it while the narration does not (an echo of the text the resolver
reads is not its leak; a narrator leak is judged elsewhere).

Names are compared as whole words, case- and accent-insensitively (the pack folding of
the scene's language). The count is the number of (scene, secret name) pairs leaked: the
names themselves are never printed.
"""

from __future__ import annotations

from functools import lru_cache

from config import get_identity_config
from evals.identity.corpus import Scene
from packs.loader import load_lang
from services.identity.mentions import find_spans
from services.identity.normalize import Normalizer

SECRET = "secret"
NAME = "name"


@lru_cache
def _normalizer(language: str) -> Normalizer:
    return Normalizer(load_lang(language), get_identity_config())


def secret_names(scene: Scene) -> list[str]:
    """Every undisclosed secret name of `scene` (see the module doc)."""
    disclosed = {d.handle for d in scene.scene.open_disclosures if d.kind == NAME}
    names = [
        k.text
        for k in scene.gold_knowledge
        if k.kind == NAME and k.state == SECRET and k.ref not in disclosed
    ]
    owner = {
        k.text: k.ref
        for k in scene.gold_knowledge
        if k.kind == NAME and k.state == SECRET
    }
    for entity in scene.world:
        if entity.id in disclosed:
            continue
        for a in entity.aliases:
            if a.secret or entity.secret:
                names.append(a.text)
                owner.setdefault(a.text, entity.id)
    normalizer = _normalizer(scene.language)
    return [
        name
        for name in dict.fromkeys(n for n in names if n.strip())
        if not _shown_elsewhere(scene, name, owner.get(name), normalizer)
    ]


def _shown_elsewhere(scene: Scene, name: str, holder: str | None, normalizer) -> bool:
    """`name` is a word of a name the protagonist knows of another, non-secret entity."""
    shown = [
        a.text
        for e in scene.world
        if e.id != holder and not e.secret
        for a in e.aliases
        if a.known and not a.secret
    ]
    return _in(name, shown, normalizer)


def _in(name: str, texts: list[str], normalizer: Normalizer) -> bool:
    return any(find_spans(text, name, normalizer) for text in texts)


def leak_count(scene: Scene, cards: list[str], texts: list[str]) -> int:
    """How many secret names of `scene` a card shows, or the other request text and
    the outputs hold while the narration does not."""
    normalizer = _normalizer(scene.language)
    narration = [scene.narration]
    return sum(
        _in(name, cards, normalizer)
        or (not _in(name, narration, normalizer) and _in(name, texts, normalizer))
        for name in secret_names(scene)
    )
