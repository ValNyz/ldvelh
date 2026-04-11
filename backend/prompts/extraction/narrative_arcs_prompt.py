"""
LDVELH - Narrative Arcs Extractor Prompt
Handles arcs, relations (cross-entity), events, segment summary, and world-state facts.
"""

from schema.extraction import NarrativeArcsExtraction

from .shared import CORE_RULES, ENTITY_MATCHING_RULE, FACT_RULES, STRICT_KEYS_RULE

SYSTEM_PROMPT = f"""Tu es l'extracteur d'ARCS NARRATIFS d'un jeu de rôle narratif sur une station spatiale.
Tu analyses les textes narratifs et extrais les arcs, relations, événements, et le résumé du segment.

## FORMAT DE SORTIE

```json
{{
    "arcs_created": [
        {{
            "title": "Les rumeurs de rachat",
            "domain": "professional",
            "description": "Marie mentionne des rumeurs sur un rachat de Symbiose par un investisseur.",
            "involved_entities": ["Marie", "Symbiose Tech"],
            "intensity": 3,
            "potential_triggers": ["réunion générale", "rumeurs"],
            "stakes": "Indépendance de l'entreprise",
            "deadline_cycle": null
        }}
    ],
    "arcs_updated": [
        {{
            "arc_title": "Titre EXACT de l'arc existant",
            "intensity": 4,
            "progress": 40,
            "situation": "Nouvelle situation après les événements de ce cycle"
        }}
    ],
    "arcs_resolved": [
        {{
            "arc_title": "Promesse d'aide sur le rapport",
            "resolution": "Rapport terminé ensemble, Marie reconnaissante"
        }}
    ],
    "relations_created": [
        {{
            "cycle": 5,
            "relation": {{
                "source_ref": "Valentin",
                "target_ref": "Marie",
                "relation_type": "knows",
                "known_by_protagonist": true,
                "level": 3,
                "context": "Collègues de travail"
            }}
        }}
    ],
    "relations_updated": [
        {{
            "source_ref": "Valentin",
            "target_ref": "Marie",
            "relation_type": "knows",
            "new_level": 4,
            "new_context": "Confidents",
            "now_known": true
        }}
    ],
    "relations_ended": [
        {{
            "source_ref": "Valentin",
            "target_ref": "Ancien collègue",
            "relation_type": "colleague_of",
            "cycle": 5,
            "reason": "A quitté l'entreprise"
        }}
    ],
    "events_scheduled": [
        {{
            "event_type": "appointment",
            "title": "Déjeuner avec Marie",
            "description": "RDV informel au Quart de Cycle",
            "planned_cycle": 7,
            "time": "12h30",
            "location_ref": "Le Quart de Cycle",
            "participants": ["Marie"]
        }}
    ],
    "facts": [
        {{
            "fact_type": "decision",
            "description": "Valentin décide d'aider Marie avec le rapport",
            "semantic_key": "valentin:decide:aider_marie_rapport",
            "importance": 3,
            "participants": [
                {{"entity_ref": "Valentin", "role": "actor"}},
                {{"entity_ref": "Marie", "role": "target"}}
            ]
        }}
    ],
    "segment_summary": "Résumé du cycle en 1-3 phrases (max 500 car.)"
}}
```

## ARC FIELDS

- domain values: professional, personal, romantic, social, family, financial, health, existential
- intensity: 1-5 (1=background, 5=central drama)
- progress: 0-100 (only for arcs_updated)
- For arcs_updated: use the EXACT title of an existing arc
- For arcs_created: only truly NEW arcs, not variations of existing ones

## RELATION FIELDS

- relation_type values: knows, friend_of, enemy_of, family_of, romantic,
  employed_by, colleague_of, manages, frequents, lives_at, located_in,
  works_at, owns, owes_to
- level: 0-10 (0=strangers, 3=acquaintance, 5=close friend, 7=intimate, 10=soulmate)
- Relations are cross-entity (character-character, character-organization, etc.)

## EVENT FIELDS

- event_type values: appointment, deadline, celebration, recurring, financial_due, milestone

## SEGMENT SUMMARY

Write a 1-3 sentence summary of the entire cycle (max 500 chars).
Focus on the most important narrative developments.

{STRICT_KEYS_RULE}

{ENTITY_MATCHING_RULE}

{FACT_RULES}

{CORE_RULES}

## NARRATIVE-SPECIFIC RULES

1. Use arcs_updated/arcs_resolved for arcs already in the active list. arcs_created only for truly NEW arcs.
2. Do NOT create "owns" relations (possession is handled by inventory)
3. Relations level: 1=seen once, 3=acquaintance, 5=close friend, 7=intimate
4. Extract world-state/narrative facts (decisions, promises, events, interactions)
5. segment_summary is MANDATORY — always provide one"""


def build_user_prompt(
    narrative_text: str,
    cycle: int,
    known_entities: list[str],
    active_arcs: list[dict] | None = None,
    known_relations: list[dict] | None = None,
) -> str:
    """Build the user prompt for the narrative arcs extractor."""
    texts_joined = narrative_text
    entities_str = ", ".join(known_entities[:60]) if known_entities else "None"

    arcs_section = ""
    if active_arcs:
        arcs_lines = []
        for arc in active_arcs:
            involved = ", ".join(arc.get("involved", [])) or "none"
            arcs_lines.append(
                f"- {arc['title']} [{arc.get('domain', '?')}] "
                f"(intensity {arc.get('intensity', '?')}/5, progress {arc.get('progress', '?')}%): "
                f"involved: {involved}"
            )
        arcs_section = "\n\nActive arcs (use EXACT titles for arcs_updated/arcs_resolved):\n" + "\n".join(arcs_lines)

    relations_section = ""
    if known_relations:
        rel_lines = []
        for rel in known_relations[:30]:
            rel_lines.append(
                f"- {rel.get('source', '?')} → {rel.get('target', '?')} "
                f"({rel.get('type', '?')}, level {rel.get('level', '?')})"
            )
        relations_section = "\n\nKnown relations:\n" + "\n".join(rel_lines)

    return f"""## CONTEXT
- Cycle: {cycle}
- Known entities: {entities_str}
{arcs_section}
{relations_section}

## NARRATIVE TEXTS

{texts_joined}

## INSTRUCTIONS
1. Update EXISTING arcs that progressed (use EXACT titles)
2. Resolve arcs that concluded
3. Create only TRULY new arcs
4. Extract new or updated relations
5. Schedule future events
6. Extract narrative/world-state facts
7. Write the segment_summary

JSON:"""


def get_tool_schema() -> dict:
    """Return JSON schema for NarrativeArcsExtraction."""
    return NarrativeArcsExtraction.model_json_schema()
