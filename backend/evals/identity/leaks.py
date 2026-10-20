"""L, the secret-leak check of the resolver v2 (#154, spec § 3.4 bis, ANNOTATION § 7.3).

A secret name of a scene is a name its gold knowledge marks secret (`kind: name`,
`state: secret`) or an alias the world flags secret (the alias or its whole entity),
unless an open name disclosure of the scene lets it through. The resolver leaks it when
it appears in what it sends to a model (the candidate cards, the scene lines) or in a
model's output. A secret name the narration itself contains is left out: the text the
resolver reads already holds it, so an echo of it is not the resolver's leak (a narrator
leak is judged elsewhere).

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
    """The secret names of `scene` the narration does not contain (see the module doc)."""
    disclosed = {d.handle for d in scene.scene.open_disclosures if d.kind == NAME}
    names = [
        k.text
        for k in scene.gold_knowledge
        if k.kind == NAME and k.state == SECRET and k.ref not in disclosed
    ]
    for entity in scene.world:
        if entity.id in disclosed:
            continue
        names += [a.text for a in entity.aliases if a.secret or entity.secret]
    normalizer = _normalizer(scene.language)
    return [
        name
        for name in dict.fromkeys(n for n in names if n.strip())
        if not find_spans(scene.narration, name, normalizer)
    ]


def leak_count(scene: Scene, texts: list[str]) -> int:
    """How many secret names of `scene` appear in `texts` (requests and outputs)."""
    normalizer = _normalizer(scene.language)
    return sum(
        any(find_spans(text, name, normalizer) for text in texts)
        for name in secret_names(scene)
    )
