"""The « carried by the protagonist » flag of the corpus worlds (#154, ruling R39).

The app knows what the protagonist carries from its inventory (inventory.owner_id NULL;
NPC possessions are not kept), and the resolver's cards show it. The corpus worlds hold
it as `carried: true` on an object, set by one rule over the scene's own inputs, never by
the gold of the scene's narration:

an object is carried when one of its own names (world aliases) or one of the history's
linked mentions of it starts with a second-person possessive of the scene's language
(the narration addresses the protagonist, so « ton terminal » is the protagonist's).

History mentions are inputs of a scene (the world loader stores them as the previous
messages' mentions), not the gold the scene is scored on. `scripts/identity_corpus_carried.py`
writes the flag; tests/identity/test_corpus.py checks every world against the rule.
"""

from __future__ import annotations

from evals.identity.corpus import Scene
from evals.identity.lexicon import load_lexicon
from evals.identity.scorer import LINKS

OBJECT = "object"


def _possessed(lexicon, surface: str) -> bool:
    head = lexicon.fold(surface.strip()).split(" ", 1)[0].casefold()
    return head in lexicon.second_person_possessives


def carried_objects(scene: Scene) -> set[str]:
    """The world ids of the objects the protagonist carries in `scene` (see above)."""
    lexicon = load_lexicon(scene.language)
    if not lexicon.second_person_possessives:
        raise ValueError(
            f"no second_person_possessives in the {scene.language!r} evaluation lexicon:"
            " the carried rule cannot run"
        )
    objects = {e.id for e in scene.world if e.type == OBJECT}
    carried = {
        e.id
        for e in scene.world
        if e.id in objects and any(_possessed(lexicon, a.text) for a in e.aliases)
    }
    for message in scene.history:
        for m in message.mentions:
            parsed = m.parsed
            if parsed.decision in LINKS and parsed.entity_id in objects:
                if _possessed(lexicon, m.surface):
                    carried.add(parsed.entity_id)
    return carried
