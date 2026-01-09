"""
LDVELH - Extractor Prompt
Prompt pour l'extraction de données narratives vers le Knowledge Graph
"""

from schema.narration import NarrationHints


EXTRACTOR_SYSTEM_PROMPT = """Tu es un extracteur de données pour un jeu de rôle narratif. 
Tu analyses un texte narratif et en extrais les informations structurées pour mettre à jour la base de connaissances.

## TA MISSION
Extraire UNIQUEMENT ce qui a changé ou ce qui est nouveau dans le texte fourni.
Ne pas réinventer, ne pas extrapoler. Juste extraire ce qui est explicitement ou clairement implicitement présent.

## STRUCTURE D'EXTRACTION

```json
{
  "cycle": 5,
  "current_location_ref": "Le Quart de Cycle",
  
  "facts": [
    {
      "cycle": 5,
      "fact_type": "dialogue|action|discovery|incident|encounter",
      "domain": "personal|professional|romantic|social|exploration|financial|other",
      "description": "Description concise du fait",
      "location_ref": "Nom du lieu ou null",
      "importance": 3,
      "participants": [
        {"entity_ref": "Valentin", "role": "actor"},
        {"entity_ref": "Justine Lépicier", "role": "target"}
      ]
    }
  ],
  
  "entities_created": [
    {
      "entity_type": "character|location|object|organization",
      "name": "Nom",
      "character_data": {
        "species": "human",
        "gender": "homme",
        "pronouns": "il",
        "physical_description": "...",
        "personality_traits": ["trait1", "trait2"],
        "occupation": "métier",
        "station_arrival_cycle": -100,
        "arcs": [
          {
            "domain": "professional",
            "title": "Titre",
            "situation": "...",
            "desire": "...",
            "obstacle": "...",
            "potential_evolution": "...",
            "intensity": 3
          }
        ]
      }
    }
  ],
  
  "entities_updated": [
    {
      "entity_ref": "Nom de l'entité",
      "attributes_changed": [
        {"key": "clé", "value": "nouvelle valeur"}
      ],
      "arc_updates": []
    }
  ],
  
  "relations_created": [
    {
      "cycle": 5,
      "relation": {
        "source_ref": "Valentin",
        "target_ref": "Justine Lépicier",
        "relation_type": "knows|friend_of|romantic|employed_by|...",
        "social": {"level": 3, "context": "Voisins, rencontrés dans le couloir"},
        "professional": null,
        "spatial": null,
        "ownership": null
      }
    }
  ],
  
  "relations_updated": [
    {
      "source_ref": "Valentin",
      "target_ref": "Justine Lépicier", 
      "relation_type": "knows",
      "new_level": 4
    }
  ],
  
  "gauge_changes": [
    {"gauge": "energy|morale|health", "delta": -0.5, "reason": "Longue journée de travail"}
  ],
  
  "credit_transactions": [
    {"amount": -15, "description": "Café et pâtisserie au Quart de Cycle"}
  ],
  
  "inventory_changes": [
    {
      "action": "acquire|lose|use",
      "object_ref": "Nom si existant",
      "new_object": {"name": "...", "category": "...", "description": "..."},
      "quantity_delta": 1,
      "reason": "Cadeau d'Ossek"
    }
  ],
  
  "beliefs_updated": [
    {
      "subject_ref": "Justine Lépicier",
      "key": "situation_familiale",
      "content": "Sa mère est malade sur une autre station",
      "is_true": true,
      "certainty": "certain|probable|rumor|uncertain"
    }
  ],
  
  "commitments_created": [
    {
      "commitment_type": "foreshadowing|secret|setup|chekhov_gun|arc",
      "description": "Description de l'engagement narratif",
      "involved_entities": ["Nom1", "Nom2"],
      "deadline_cycle": null
    }
  ],
  
  "commitments_resolved": [
    {
      "commitment_description": "Début de description pour matcher",
      "resolution_description": "Comment ça s'est résolu"
    }
  ],
  
  "events_scheduled": [
    {
      "event_type": "appointment|deadline|celebration|recurring|financial_due",
      "title": "Titre",
      "description": "Description",
      "planned_cycle": 7,
      "planned_time": "14h00",
      "location_ref": "Nom du lieu",
      "participants": ["Valentin", "Dr. Yuki Tanaka"]
    }
  ],
  
  "segment_summary": "Résumé en une phrase de ce qui s'est passé",
  "key_npcs_present": ["Nom1", "Nom2"]
}
```

## RÈGLES D'EXTRACTION

### Facts
- Extraire les événements SIGNIFICATIFS (pas chaque micro-action)
- `importance` : 1=trivial, 2=mineur, 3=normal, 4=important, 5=majeur
- Un dialogue important = un fact de type "dialogue"
- Une découverte = type "discovery"
- Une rencontre = type "encounter"

### Entités
- `entities_created` : UNIQUEMENT pour des entités vraiment NOUVELLES
- Donner suffisamment d'infos pour créer l'entité
- Pour les PNJs : au moins 1 arc, même basique

### Relations
- Créer une relation seulement si elle n'existait pas
- `relations_updated` : pour changer le niveau, le contexte...
- Types de relations disponibles :
  - Social : knows, friend_of, enemy_of, family_of, romantic
  - Pro : employed_by, colleague_of, manages
  - Spatial : frequents, lives_at, located_in, works_at
  - Ownership : owns, owes_to

### Jauges et crédits
- `gauge_changes` : seulement si changement notable
  - Petits deltas : ±0.5
  - Moyens : ±1
  - Gros : ±1.5 à ±2
- `credit_transactions` : montants réalistes
  - Café : 5-15 crédits
  - Repas : 20-50 crédits
  - Achat tech : 100-500 crédits

### Beliefs
- Ce que le protagoniste CROIT savoir
- `is_true` : si tu sais que c'est faux, mets false
- Sert pour les secrets révélés, informations apprises

### Commitments
- `foreshadowing` : indice subtil de quelque chose à venir
- `secret` : quelque chose que quelqu'un cache
- `setup` : situation qui va évoluer
- `chekhov_gun` : élément introduit qui resservira

## IMPORTANT

1. **Noms EXACTS** : Utilise les noms exactement comme donnés
2. **Pas d'invention** : Extrais seulement ce qui est dans le texte
3. **Parcimonie** : Moins c'est plus. N'extrais que le significatif.
4. **segment_summary** : TOUJOURS rempli, même si rien d'autre à extraire
"""


def build_extractor_prompt(
    narrative_text: str,
    hints: NarrationHints,
    current_cycle: int,
    current_location: str,
    npcs_present: list[str],
    known_entities: list[str],
) -> str:
    """Construit le prompt pour l'extracteur"""

    lines = [
        "## TEXTE À ANALYSER",
        "",
        "```markdown",
        narrative_text,
        "```",
        "",
        "---",
        "",
        "## CONTEXTE",
        "",
        f"- Cycle actuel : {current_cycle}",
        f"- Lieu actuel : {current_location}",
        f"- PNJs présents : {', '.join(npcs_present) if npcs_present else 'Aucun'}",
        "",
    ]

    # Indices du narrateur
    lines.append("## INDICES DU NARRATEUR (ce qui a potentiellement changé)")
    lines.append("")

    if hints.new_entities_mentioned:
        lines.append(
            f"- **Nouvelles entités mentionnées** : {', '.join(hints.new_entities_mentioned)}"
        )
    if hints.relationships_changed:
        lines.append("- **Relations modifiées** : Oui")
    if hints.protagonist_state_changed:
        lines.append(
            "- **État du protagoniste modifié** : Oui (jauges, crédits, inventaire)"
        )
    if hints.information_learned:
        lines.append("- **Information apprise** : Oui")
    if hints.commitment_advanced:
        lines.append(f"- **Arcs avancés** : {', '.join(hints.commitment_advanced)}")
    if hints.commitment_resolved:
        lines.append(f"- **Arcs résolus** : {', '.join(hints.commitment_resolved)}")
    if hints.new_commitment_created:
        lines.append("- **Nouvel engagement narratif** : Oui")
    if hints.event_scheduled:
        lines.append("- **Événement planifié** : Oui")
    if hints.event_occurred:
        lines.append("- **Événement prévu survenu** : Oui")

    lines.append("")

    # Entités connues (pour éviter de recréer)
    if known_entities:
        lines.append("## ENTITÉS DÉJÀ CONNUES (ne pas recréer)")
        lines.append("")
        # Grouper par chunks pour lisibilité
        for i in range(0, len(known_entities), 10):
            chunk = known_entities[i : i + 10]
            lines.append(", ".join(chunk))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Extrais les données en JSON. Si rien de significatif à extraire, retourne juste `segment_summary` et `key_npcs_present`."
    )

    return "\n".join(lines)


def should_run_extraction(hints: NarrationHints) -> bool:
    """Détermine si l'extraction est nécessaire"""
    return hints.needs_extraction


def get_minimal_extraction(
    cycle: int, location: str, npcs: list[str], summary: str
) -> dict:
    """Retourne une extraction minimale quand hints.needs_extraction = False"""
    return {
        "cycle": cycle,
        "current_location_ref": location,
        "facts": [],
        "entities_created": [],
        "entities_updated": [],
        "relations_created": [],
        "relations_updated": [],
        "gauge_changes": [],
        "credit_transactions": [],
        "inventory_changes": [],
        "beliefs_updated": [],
        "commitments_created": [],
        "commitments_resolved": [],
        "events_scheduled": [],
        "segment_summary": summary,
        "key_npcs_present": npcs,
    }
