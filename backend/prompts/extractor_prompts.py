"""
LDVELH - Extraction Prompts (Dedicated Tables Architecture)
Format direct : colonnes dédiées par type d'entité, pas d'attributes EAV
"""

from schema.narration import NarrationHints
from prompts.examples import (
    EXTRACTION_ENTITIES_EXAMPLE,
    EXTRACTION_OBJECTS_EXAMPLE,
    EXTRACTION_FACTS_EXAMPLE,
    EXTRACTION_RELATIONS_EXAMPLE,
    EXTRACTION_ARCS_EXAMPLE,
)

# =============================================================================
# INSTRUCTION COMMUNE — CLÉS STRICTES
# =============================================================================

_STRICT_KEYS = """
## CONTRAINTE STRICTE SUR LES CLÉS JSON

Tu DOIS utiliser EXACTEMENT les clés JSON listées dans le format ci-dessus.
- N'ajoute AUCUNE clé supplémentaire
- N'invente PAS de variantes (ex: "type" au lieu de "fact_type")
- N'imbrique PAS de données dans des sous-objets non prévus
- Si une information n'a pas de clé prévue, ignore-la"""


# =============================================================================
# BATCH EXTRACTION (end-of-cycle, single LLM call)
# =============================================================================

BATCH_EXTRACTION_SYSTEM = f"""Tu extrais TOUTES les données narratives d'un cycle complet de jeu de rôle.
Tu reçois la concaténation de tous les textes narratifs d'un cycle et tu extrais en une seule passe :
entités, faits, relations, arcs narratifs, objets, et résumé.

## FORMAT DE SORTIE

```json
{{
    "segment_summary": "Résumé du cycle en 1-3 phrases (max 300 car.)",
    "entities_created": [{EXTRACTION_ENTITIES_EXAMPLE["entities_created"][0]}],
    "entities_updated": [],
    "objects_created": [{EXTRACTION_OBJECTS_EXAMPLE["objects_created"][0]}],
    "facts": [{EXTRACTION_FACTS_EXAMPLE["facts"][0]}],
    "relations_created": [{EXTRACTION_RELATIONS_EXAMPLE["relations_created"][0]}],
    "relations_updated": [],
    "arcs_created": [{EXTRACTION_ARCS_EXAMPLE["arcs_created"][0]}],
    "arcs_updated": [],
    "arcs_resolved": [],
    "events_scheduled": [],
    "ambient_updates": []
}}
```

## CLÉS AUTORISÉES

### Racine
segment_summary, entities_created, entities_updated, objects_created,
facts, relations_created, relations_updated, arcs_created, arcs_updated,
arcs_resolved, events_scheduled, ambient_updates

### entities_created[]
Obligatoires: "entity_type" (character|location|organization), "name" (string)
Optionnels: "known_by_protagonist" (bool), "unknown_name" (string|null), "data" (dict)

data — CHARACTER: description, mood, age, origin, species, gender,
  pronouns, occupation, traits (liste), romantic_potential (bool),
  workplace_ref (string), residence_ref (string)

data — LOCATION: location_type, sector, description, atmosphere,
  accessible (bool), notable_features (liste), typical_crowd,
  operating_hours, price_range, parent_location_ref (string)

data — ORGANIZATION: org_type, domain, size, description, reputation,
  headquarters_ref (string), founding_cycle (int)

### entities_updated[]
Obligatoire: "entity_ref" (string)
Optionnels: "now_known" (bool), "real_name" (string), "changes" (dict)
"changes" utilise les MÊMES clés que "data" selon le type d'entité.

### objects_created[]
"name" (string), "category" (string), "description" (string),
  "transportable" (bool), "stackable" (bool), "base_value" (int|null),
  "quantity" (int), "from_hint" (string)
Valeurs de "category": tech, weapon, clothing, food, document, tool, misc

### facts[]
"fact_type" (string), "description" (string),
  "semantic_key" (string format sujet:verbe:objet), "importance" (int 1-5),
  "participants" (liste)
participants[]: "entity_ref" (string), "role" (actor|witness|target|location)
Valeurs de "fact_type": revelation, statement, promise, request, refusal,
  action, npc_action, observation, state_change, encounter, interaction,
  conflict, acquisition, loss, decision, realization

### relations_created[]
"cycle" (int), "relation" (dict)
relation: "source_ref" (string), "target_ref" (string),
  "relation_type" (string), "known_by_protagonist" (bool),
  "level" (int 0-10), "context" (string)
Valeurs de "relation_type": knows, friend_of, enemy_of, family_of, romantic,
  employed_by, colleague_of, manages, frequents, lives_at, located_in,
  works_at, owns, owes_to

### relations_updated[]
"source_ref" (string), "target_ref" (string), "relation_type" (string),
"new_level" (int 0-10), "new_context" (string), "now_known" (bool)

### arcs_created[]
"title" (string), "domain" (string), "description" (string),
"involved_entities" (liste de strings), "intensity" (int 1-5)
Optionnels: "potential_triggers" (liste), "stakes" (string), "deadline_cycle" (int)
Valeurs de "domain": professional, romantic, health, social, mystery, personal, political

### arcs_updated[]
"arc_title" (string — titre EXACT de l'arc existant)
Optionnels: "intensity" (int 1-5), "progress" (int 0-100), "situation" (string)

### arcs_resolved[]
"arc_title" (string), "resolution" (string)

### events_scheduled[]
"event_type" (string), "title" (string), "description" (string),
"planned_cycle" (int), "time" (string), "location_ref" (string),
"participants" (liste de strings)
Valeurs de "event_type": appointment, deadline, celebration, meeting, delivery

### ambient_updates[]
"entity_ref" (string — nom EXACT), "entity_type" (character|location|organization),
"ambient" (string max 200 car.)
L'ambient décrit l'effet VISIBLE des arcs en cours sur l'entité.
Ce qu'un observateur remarquerait : comportement, atmosphère, apparence.
OBLIGATOIRE : génère un ambient_updates pour chaque entité impliquée dans un arc actif.
Consulte la section "Arcs actifs avec participants" du contexte pour la liste exacte.

{_STRICT_KEYS}

## RÈGLES

1. Extrais UNIQUEMENT ce qui est EXPLICITE dans le texte
2. N'invente rien, ne déduis pas
3. Les jauges (énergie, moral, santé) et crédits sont déjà gérés par le narrateur — NE PAS les extraire
4. Idem pour l'inventaire basique — les inventory_hints sont déjà appliqués
5. Crée des objets COMPLETS uniquement pour les items acquis qui nécessitent une fiche détaillée
6. Utilise les noms EXACTS du texte pour les entités
7. Déduplique : une entité/fait ne doit apparaître qu'une fois
8. semantic_key des faits : format sujet:verbe:objet en snake_case ASCII
9. known_by_protagonist=true si Valentin a VU/ENTENDU le nom
10. Importance des faits : 5=change la donne, 4=significatif, 3=notable, 2=mineur, 1=ambiance
11. Relations level : 1=connu de vue, 3=connaissance, 5=ami proche, 7=intime
12. PAS de relations "owns" (possession gérée par l'inventaire)"""


def build_batch_extraction_prompt(
    narrative_texts: list[str],
    cycle: int,
    known_entities: list[str],
    known_arc_titles: list[str] | None = None,
    inventory_hints: list[dict] | None = None,
    narrator_hints: list[dict] | None = None,
    stub_locations: list[str] | None = None,
    active_arc_details: list[dict] | None = None,
) -> str:
    """Build the user prompt for batch extraction."""
    texts_joined = "\n\n---\n\n".join(narrative_texts)
    entities_str = ", ".join(known_entities[:60]) if known_entities else "Aucune"
    arcs_str = ", ".join(known_arc_titles[:30]) if known_arc_titles else "Aucun"

    extras = ""
    if inventory_hints:
        items = [f"- {h.get('item_name', '?')} ({h.get('action', '?')})" for h in inventory_hints]
        extras += f"\n\nObjets acquis/perdus ce cycle (inventory_hints déjà appliqués):\n" + "\n".join(items)

    if narrator_hints:
        # Aggregate signals from all turns
        all_new_entities = []
        arcs_advanced = []
        arcs_resolved = []
        flags = {"relationships_changed": False, "information_learned": False,
                 "new_arc_created": False, "event_scheduled": False,
                 "protagonist_state_changed": False, "event_occurred": False}
        for h in narrator_hints:
            all_new_entities.extend(h.get("new_entities_mentioned", []))
            arcs_advanced.extend(h.get("arc_advanced", []))
            arcs_resolved.extend(h.get("arc_resolved", []))
            for flag in flags:
                if h.get(flag):
                    flags[flag] = True

        signals = []
        if all_new_entities:
            signals.append(f"- Nouvelles entités mentionnées: {', '.join(set(all_new_entities))}")
        if arcs_advanced:
            signals.append(f"- Arcs avancés: {', '.join(set(arcs_advanced))}")
        if arcs_resolved:
            signals.append(f"- Arcs résolus: {', '.join(set(arcs_resolved))}")
        if flags["relationships_changed"]:
            signals.append("- Relations modifiées")
        if flags["information_learned"]:
            signals.append("- Informations apprises")
        if flags["new_arc_created"]:
            signals.append("- Nouvel arc/engagement créé")
        if flags["event_scheduled"]:
            signals.append("- Événement planifié")
        if flags["protagonist_state_changed"]:
            signals.append("- Compétences/état du protagoniste modifié")
        if flags["event_occurred"]:
            signals.append("- Événement planifié survenu")

        if signals:
            extras += "\n\nSignaux du narrateur ce cycle:\n" + "\n".join(signals)

    if stub_locations:
        stubs_str = ", ".join(stub_locations)
        extras += (
            f"\n\nLieux à enrichir (stubs sans description, à compléter via entities_updated):\n"
            f"- {stubs_str}\n"
            f"Pour chaque stub: entity_ref = nom exact, changes = "
            f"{{description, location_type, sector, atmosphere}}"
        )

    if active_arc_details:
        extras += "\n\nArcs actifs avec participants (pour ambient_updates):\n"
        for arc in active_arc_details:
            parts = ", ".join(arc["participants"]) if arc["participants"] else "aucun"
            extras += f"- {arc['title']} [{arc['domain']}] (intensité {arc['intensity']}/5): {parts}\n"

    return f"""## CONTEXTE
- Cycle: {cycle}
- Entités connues: {entities_str}
- Arcs actifs: {arcs_str}
{extras}

## TEXTES NARRATIFS DU CYCLE

{texts_joined}

## INSTRUCTIONS
1. Extrais toutes les NOUVELLES entités (pas celles déjà connues)
2. Extrais tous les faits distincts avec semantic_key unique
3. Extrais les relations créées ou modifiées
4. Arcs: utilise arcs_updated/arcs_resolved pour les arcs DÉJÀ LISTÉS ci-dessus. N'utilise arcs_created QUE pour des arcs VRAIMENT nouveaux.
5. Crée les fiches d'objets NOUVEAUX acquis
6. Résume le cycle en 1-3 phrases
7. ambient_updates : pour chaque entité impliquée dans un arc actif (voir "Arcs actifs avec participants"), génère un ambient décrivant l'effet VISIBLE de l'arc (max 200 car.). Omets si l'arc n'affecte pas visiblement l'entité ce cycle.

JSON:"""


# =============================================================================
# HELPERS
# =============================================================================


def should_run_extraction(hints: NarrationHints) -> bool:
    """Determine if extraction is needed"""
    return hints.needs_extraction


def extract_object_hints(inventory_changes: list[dict]) -> list[str]:
    """Extract object hints from inventory_changes"""
    hints = []
    for change in inventory_changes:
        if change.get("action") == "acquire" and change.get("object_hint"):
            hints.append(change["object_hint"])
    return hints
