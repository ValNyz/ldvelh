"""Free-text arc domains never break the narrator context (#12)."""

import pytest

from schema.narration import ArcSummary, NPCSummary
from services.context_builder import ContextBuilder


def _npc(name="Raj"):
    return NPCSummary(name=name, occupation="docker", relationship_level=None,
                      usual_location=None, known=True, traits=[])


@pytest.mark.parametrize("domain,expected", [
    ("politique", "politique"),
    ("Social", "social"),
    ("  Family ", "family"),
    (None, "personal"),
    ("", "personal"),
])
def test_enrich_npcs_accepts_any_domain(domain, expected):
    npc = _npc()
    arcs = [{"title": "Grève des dockers", "domain": domain, "description": "d", "intensity": 3,
             "participants": [{"name": "Raj"}]}]
    ContextBuilder.__new__(ContextBuilder)._enrich_npcs_with_arcs([npc], arcs)
    assert npc.active_arcs[0].domain == expected


def test_free_text_domain_renders_in_narrator_npc_section():
    from types import SimpleNamespace

    from prompts.narrator_prompt import _append_npc_section

    npc = _npc()
    npc.active_arcs = [ArcSummary(domain="politique", title="Grève", situation_brief="", intensity=3)]
    context = SimpleNamespace(npcs_present=[npc], npcs_relevant=[], all_npcs=[], requested_entity_details={})
    lines: list[str] = []
    _append_npc_section(lines, context)
    assert any("Arc [politique] Grève" in line for line in lines), lines


def test_director_prompt_lists_known_domains():
    from prompts.director_prompt import DIRECTOR_SYSTEM_PROMPT
    from schema.core import ArcDomain
    for d in ArcDomain:
        assert d.value in DIRECTOR_SYSTEM_PROMPT
