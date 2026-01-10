"""
LDVELH - Prompts d'extraction spécialisés
Chaque extracteur a son propre prompt optimisé
"""

from schema.narration import NarrationHints

# =============================================================================
# EXTRACTEUR: RÉSUMÉ (Haiku)
# =============================================================================

SUMMARY_SYSTEM = """Tu résumes des textes narratifs de jeu de rôle en une à trois phrase(s) concise(s).
Réponds UNIQUEMENT en JSON: {"segment_summary": "..."}"""


def build_summary_prompt(narrative_text: str) -> str:
    return f"""Résume ce texte en UNE phrase (max 150 caractères).
Capture: qui, quoi, où, événement(s) principal(aux).

Texte:
{narrative_text}

JSON:"""


# =============================================================================
# EXTRACTEUR: ÉTAT PROTAGONISTE (Haiku)
# Jauges, crédits, signaux d'inventaire (pas de création d'objet)
# =============================================================================

PROTAGONIST_STATE_SYSTEM = """Tu extrais les changements d'état du protagoniste depuis un texte narratif.
Réponds UNIQUEMENT en JSON. Omets les champs sans changement.

Format:
```json
{
  "gauge_changes": [
    {"gauge": "energy|morale|health", "delta": -0.5, "reason": "..."}
  ],
  "credit_transactions": [
    {"amount": -15, "description": "..."}
  ],
  "inventory_changes": [
    {
      "action": "acquire|lose|use",
      "object_ref": "Nom exact si objet connu",
      "object_hint": "Description SI nouvel objet acquis",
      "quantity_delta": 1,
      "reason": "..."
    }
  ]
}
```

Règles IMPORTANTES:
- Jauges: petits deltas ±0.5, moyens ±1, gros ±1.5 à ±2
- Crédits: café 5-15, repas 20-50, achat tech 100-500
- Pour NOUVEAUX objets acquis: utilise "object_hint" avec une description textuelle courte
- Pour objets EXISTANTS: utilise "object_ref" avec le nom exact
- N'invente rien, extrais uniquement ce qui est explicite"""


def build_protagonist_state_prompt(
    narrative_text: str, known_objects: list[str] | None = None
) -> str:
    objects_str = ", ".join(known_objects[:20]) if known_objects else "Aucun connu"

    return f"""Texte narratif:
```
{narrative_text}
```

Objets déjà possédés par le protagoniste: {objects_str}

Extrais les changements d'état du protagoniste.
- Pour un objet NOUVEAU: {{"action": "acquire", "object_hint": "description de l'objet"}}
- Pour un objet EXISTANT: {{"action": "lose|use", "object_ref": "Nom exact"}}

Si aucun changement, retourne {{"gauge_changes": [], "credit_transactions": [], "inventory_changes": []}}

JSON:"""


# =============================================================================
# EXTRACTEUR: ENTITÉS (Sonnet)
# PNJ, lieux, organisations
# =============================================================================

ENTITIES_SYSTEM = """Tu extrais les nouvelles entités d'un texte narratif pour un jeu de rôle.
Tu crées UNIQUEMENT les entités vraiment NOUVELLES (pas celles déjà connues).

Format de sortie:
```json
{
  "entities_created": [
    {
      "entity_type": "character|location|organization",
      "name": "Nom exact",
      "character_data": {
        "species": "human",
        "gender": "homme|femme|autre",
        "pronouns": "il|elle|iel",
        "physical_description": "...",
        "personality_traits": ["trait1", "trait2"],
        "occupation": "métier",
        "station_arrival_cycle": -100,
        "arcs": [{
          "domain": "professional|personal|romantic|social",
          "title": "...",
          "situation": "...",
          "desire": "...",
          "obstacle": "...",
          "potential_evolution": "...",
          "intensity": 3
        }]
      },
      "location_data": {
        "location_type": "...",
        "description": "...",
        "atmosphere": "..."
      },
      "organization_data": {
        "org_type": "...",
        "domain": "...",
        "description": "..."
      }
    }
  ],
  "entities_updated": [
    {
      "entity_ref": "Nom exact",
      "attributes_changed": [{"key": "...", "value": "..."}]
    }
  ]
}
```

Règles:
- Utilise les noms EXACTS du texte
- N'invente pas, extrait uniquement ce qui est présent
- Pour les personnages: toujours au moins 1 arc à inventer
"""


def build_entities_prompt(
    narrative_text: str, new_entities_hints: list[str], known_entities: list[str]
) -> str:
    known_str = ", ".join(known_entities[:50]) if known_entities else "Aucune"
    hints_str = ", ".join(new_entities_hints) if new_entities_hints else "Non spécifié"

    return f"""Texte narratif:
```
{narrative_text}
```

Entités potentiellement nouvelles (indices du narrateur): {hints_str}
Entités DÉJÀ CONNUES (ne pas recréer): {known_str}
Extrais uniquement PNJ, lieux, organisations.

JSON:"""


# =============================================================================
# EXTRACTEUR: OBJETS ACQUIS (Sonnet)
# Crée les objets à partir des hints d'inventaire
# =============================================================================

OBJECTS_SYSTEM = """Tu crées les fiches d'objets acquis par le protagoniste dans un jeu de rôle.
Tu reçois des "hints" (descriptions courtes) et tu crées des objets complets et cohérents.

Format de sortie:
```json
{
  "objects_created": [
    {
      "name": "Nom de l'objet",
      "category": "bijou|vêtement|outil|nourriture|document|tech|arme|autre",
      "description": "Description en 1-2 phrases",
      "transportable": true,
      "stackable": false,
      "base_value": 50,
      "emotional_significance": "Signification émotionnelle si pertinent, sinon null",
      "from_hint": "Le hint original"
    }
  ]
}
```

Règles:
- "name": Nom clair et mémorable (pas trop générique)
- "category": Une des catégories listées
- "base_value": Estimation réaliste en crédits (0 si sans valeur marchande)
- "emotional_significance": Remplis si c'est un cadeau, souvenir, objet personnel
- "from_hint": Recopie exactement le hint reçu"""


def build_objects_prompt(
    narrative_text: str,
    object_hints: list[str],
) -> str:
    hints_formatted = "\n".join(f"- {hint}" for hint in object_hints)

    return f"""Texte narratif (pour contexte):
```
{narrative_text}
```

Objets à créer (hints):
{hints_formatted}

Crée une fiche complète pour chaque objet.
JSON:"""


# =============================================================================
# EXTRACTEUR: FAITS (Haiku)
# =============================================================================

FACTS_SYSTEM = """Tu es un extracteur de faits narratifs. Tu analyses un texte de jeu narratif et extrais les FAITS DISTINCTS qui s'y produisent.

## RÈGLES CRITIQUES

### 1. UN FAIT = UNE INFORMATION ATOMIQUE
- Chaque fait doit capturer UNE SEULE chose qui s'est passée
- Si une phrase contient 2 informations distinctes → 2 facts séparés
- Ne PAS résumer plusieurs événements en un seul fact

### 2. ANTI-DUPLICATION (CRITIQUE)
- Chaque fait a une `semantic_key` unique: `{sujet}:{verbe}:{objet}`
- Si deux facts auraient la même semantic_key → N'EN GARDER QU'UN
- Reformuler ≠ nouveau fait. "X révèle Y" et "X dit que Y" = MÊME FAIT

### 3. TYPES DE FAITS (choisir le plus spécifique)

| Type | Quand l'utiliser | Exemple |
|------|------------------|---------|
| `revelation` | Information importante/secrète révélée | "X révèle qu'il a un passé criminel" |
| `statement` | Opinion, déclaration, réflexion exprimée | "X pense que le progrès est une illusion" |
| `promise` | Engagement à faire quelque chose | "X promet d'aider à trouver Y" |
| `request` | Demande faite | "X demande à Valentin de l'aider" |
| `refusal` | Refus explicite | "X refuse de parler de son passé" |
| `question` | Question significative (pas rhétorique) | "X demande d'où vient Valentin" |
| `action` | Action physique de Valentin | "Valentin fouille le bureau" |
| `npc_action` | Action physique d'un PNJ | "X quitte la pièce brusquement" |
| `observation` | Valentin remarque quelque chose | "Valentin remarque une cicatrice sur X" |
| `state_change` | Changement de relation/statut/humeur | "L'atmosphère devient tendue" |
| `encounter` | Première rencontre | "Valentin rencontre X pour la première fois" |
| `interaction` | Échange social significatif | "X et Valentin partagent un moment de complicité" |
| `conflict` | Tension, désaccord | "X se montre hostile envers Valentin" |
| `flashback` | Info sur le passé | "X mentionne avoir travaillé ici il y a 10 ans" |
| `acquisition` | Gain de quelque chose | "Valentin obtient le code d'accès" |
| `loss` | Perte de quelque chose | "Valentin perd son badge" |
| `decision` | Choix significatif de Valentin | "Valentin décide de faire confiance à X" |
| `realization` | Prise de conscience | "Valentin comprend que X lui a menti" |

### 4. SEMANTIC_KEY
Format OBLIGATOIRE: `{sujet}:{verbe}:{objet}` en snake_case ASCII (pas d'accents)
- `morrigan:revele:disparition_createur`
- `valentin:rencontre:elena`
- `atmosphere:devient:tendue`
- `valentin:obtient:code_acces`

### 5. IMPORTANCE (1-5)
- 5: Change la donne (révélation majeure, mort, trahison)
- 4: Significatif (nouvelle relation, info importante)
- 3: Notable (interaction mémorable, décision)
- 2: Mineur (small talk significatif, observation)
- 1: Ambiance (atmosphère, détail de décor)

### 6. CE QU'IL NE FAUT PAS EXTRAIRE
- Small talk sans substance
- Descriptions purement visuelles sans implication
- Répétitions d'informations déjà connues
- Actions triviales (marcher, s'asseoir) sauf si significatives

## FORMAT DE SORTIE
```json
{
  "facts": [
    {
      "fact_type": "revelation",
      "description": "Le créateur de Morrigan a disparu il y a 4 ans sans laisser de trace ni message",
      "semantic_key": "morrigan:revele:disparition_createur",
      "importance": 4,
      "participants": [
        {"entity_ref": "Morrigan", "role": "actor"},
        {"entity_ref": "Valentin", "role": "witness"}
      ]
    }
  ]
}
```
"""


def build_facts_prompt(
    narrative_text: str,
    cycle: int,
    location: str,
    known_entities: list[str],
) -> str:
    entities_list = ", ".join(known_entities) if known_entities else "Aucune"

    return f"""## CONTEXTE
- Cycle actuel: {cycle}
- Lieu: {location}
- Entités connues: {entities_list}

## TEXTE À ANALYSER
{narrative_text}

## INSTRUCTIONS
1. Identifie TOUS les faits distincts dans ce texte
2. Pour chaque fait, détermine le type le plus spécifique
3. Génère une semantic_key unique (sujet:verbe:objet)
4. VÉRIFIE qu'il n'y a pas de doublons (même semantic_key)
5. Assigne une importance réaliste (la plupart = 2-3)

Retourne UNIQUEMENT le JSON, sans commentaire."""


# =============================================================================
# EXTRACTEUR: RELATIONS (Haiku)
# Relations interpersonnelles UNIQUEMENT (pas owns)
# =============================================================================

RELATIONS_SYSTEM = """Tu extrais les relations INTERPERSONNELLES d'un texte narratif.

Format:
```json
{
  "relations_created": [
    {
      "cycle": 5,
      "relation": {
        "source_ref": "Nom exact",
        "target_ref": "Nom exact",
        "relation_type": "knows|friend_of|enemy_of|romantic|employed_by|colleague_of|frequents|lives_at|works_at",
        "social": {"level": 3, "context": "..."},
        "professional": {"role": "employee|manager|colleague", "context": "..."},
        "spatial": {"frequency": "daily|weekly|occasional"}
      }
    }
  ],
  "relations_updated": [
    {
      "source_ref": "Nom exact",
      "target_ref": "Nom exact",
      "relation_type": "knows",
      "new_level": 4,
      "new_context": "..."
    }
  ]
}
```

Types de relations:
- Social: knows, friend_of, enemy_of, family_of, romantic
- Pro: employed_by, colleague_of, manages
- Spatial: frequents, lives_at, located_in, works_at

Règles:
- Niveaux sociaux: 1=connu de vue, 3=connaissance, 5=ami proche, 7=intime
- Utilise les noms EXACTS"""


def build_relations_prompt(
    narrative_text: str, cycle: int, known_entities: list[str]
) -> str:
    entities_str = ", ".join(known_entities[:40]) if known_entities else "Aucune"

    return f"""Texte narratif:
```
{narrative_text}
```

Contexte:
- Cycle actuel: {cycle}
- Entités connues: {entities_str}

Extrais les relations INTERPERSONNELLES créées ou modifiées.
RAPPEL: PAS de relations "owns" (possession).

Si aucune relation, retourne {{"relations_created": [], "relations_updated": []}}
JSON:"""


# =============================================================================
# EXTRACTEUR: CROYANCES (Haiku)
# =============================================================================

BELIEFS_SYSTEM = """Tu extrais ce que le protagoniste apprend ou croit savoir.

Format:
```json
{
  "beliefs_updated": [
    {
      "subject_ref": "Nom de l'entité concernée",
      "key": "clé courte (ex: situation_familiale, secret, metier)",
      "content": "Ce que le protagoniste croit",
      "is_true": true,
      "certainty": "certain|probable|rumor|uncertain"
    }
  ]
}
```

Règles:
- subject_ref: l'entité sur laquelle porte l'information
- is_true: false si tu sais que c'est un mensonge/erreur
- Sert pour secrets révélés, informations apprises, rumeurs"""


def build_beliefs_prompt(narrative_text: str, known_entities: list[str]) -> str:
    entities_str = ", ".join(known_entities[:40]) if known_entities else "Aucune"

    return f"""Texte narratif:
```
{narrative_text}
```

Entités connues: {entities_str}

Extrais les informations que le protagoniste a apprises.
Si rien appris, retourne {{"beliefs_updated": []}}
JSON:"""


# =============================================================================
# EXTRACTEUR: ENGAGEMENTS & ÉVÉNEMENTS (Sonnet)
# =============================================================================

COMMITMENTS_SYSTEM = """Tu extrais les engagements narratifs et événements planifiés.

Format:
```json
{
  "commitments_created": [
    {
      "commitment_type": "foreshadowing|secret|setup|chekhov_gun|arc",
      "description": "Description de l'engagement",
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
      "description": "...",
      "planned_cycle": 7,
      "planned_time": "14h00",
      "location_ref": "Nom du lieu",
      "participants": ["Nom1", "Nom2"]
    }
  ]
}
```

Types d'engagements:
- foreshadowing: indice subtil de quelque chose à venir
- secret: quelque chose que quelqu'un cache
- setup: situation qui va évoluer
- chekhov_gun: élément introduit qui resservira
- arc: progression d'un arc narratif"""


def build_commitments_prompt(
    narrative_text: str,
    known_entities: list[str],
    commitment_hints: list[str] | None = None,
) -> str:
    entities_str = ", ".join(known_entities[:40]) if known_entities else "Aucune"
    hints_str = ", ".join(commitment_hints) if commitment_hints else "Non spécifié"

    return f"""Texte narratif:
```
{narrative_text}
```

Entités connues: {entities_str}
Arcs avancés/résolus (indices): {hints_str}

Extrais les engagements narratifs et événements planifiés.
JSON:"""


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


# =============================================================================
# HELPERS
# =============================================================================


def should_run_extraction(hints: NarrationHints) -> bool:
    """Détermine si une extraction est nécessaire"""
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


def extract_object_hints(inventory_changes: list[dict]) -> list[str]:
    """Extrait les hints d'objets à créer depuis les inventory_changes"""
    hints = []
    for change in inventory_changes:
        if change.get("action") == "acquire" and change.get("object_hint"):
            hints.append(change["object_hint"])
    return hints
