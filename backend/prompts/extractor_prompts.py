"""
LDVELH - Extraction Prompts (EAV Architecture)
Unified format: all entity types use attributes with known flag
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

Règles:
- Jauges: petits deltas ±0.5, moyens ±1, gros ±1.5 à ±2
- Crédits: café 5-15, repas 20-50, achat tech 100-500
- Pour NOUVEAUX objets: utilise "object_hint" avec description courte
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

Objets déjà possédés: {objects_str}

Extrais les changements d'état du protagoniste.
Si aucun changement, retourne {{"gauge_changes": [], "credit_transactions": [], "inventory_changes": []}}

JSON:"""


# =============================================================================
# EXTRACTEUR: ENTITÉS (Sonnet) - FORMAT UNIFIÉ EAV
# =============================================================================

ENTITIES_SYSTEM = """Tu extrais les nouvelles entités d'un texte narratif pour un jeu de rôle.
Tu crées UNIQUEMENT les entités vraiment NOUVELLES (pas celles déjà connues).

## FORMAT UNIFIÉ (tous types d'entités)

```json
{
  "entities_created": [
    {
      "entity_type": "character|location|organization|object",
      "name": "Nom exact",
      "known_by_protagonist": true,
      "unknown_name": null,
      "attributes": [
        {"key": "clé", "value": "valeur", "known": true|false}
      ]
    }
  ],
  "entities_updated": [
    {
      "entity_ref": "Nom exact",
      "now_known": true,
      "real_name": "Vrai nom si révélé",
      "attributes_changed": [
        {"key": "clé", "value": "nouvelle valeur", "known": true}
      ]
    }
  ]
}
```

## CLÉS D'ATTRIBUTS PAR TYPE

### CHARACTER
- description: apparence physique (ALWAYS visible)
- mood: humeur actuelle (ALWAYS visible)
- age: âge (CONDITIONAL)
- origin: lieu d'origine (NEVER - secret)
- motivation: ce qui le/la motive (NEVER - secret)
- quirk: particularité de comportement (ALWAYS visible)
- arcs: JSON des arcs narratifs (NEVER - méta)

Stocker dans details du premier attribut:
- species, gender, pronouns, occupation, arrival_cycle

### LOCATION
- description: description du lieu (ALWAYS)
- atmosphere: ambiance (ALWAYS)
- notable_features: caractéristiques notables (ALWAYS)
- typical_crowd: clientèle typique (ALWAYS)
- operating_hours: horaires (CONDITIONAL)
- price_range: gamme de prix (CONDITIONAL)
- secret: secret du lieu (NEVER)

Stocker dans details: location_type, sector, accessible

### ORGANIZATION
- description: description publique (ALWAYS)
- reputation: réputation connue (CONDITIONAL)
- public_facade: façade publique (ALWAYS)
- true_purpose: vrai but (NEVER - secret)
- influence_level: niveau d'influence (CONDITIONAL)

Stocker dans details: org_type, domain, size, founding_cycle

### OBJECT
- description: description de l'objet (ALWAYS)
- condition: état de l'objet (ALWAYS)
- emotional_significance: signification émotionnelle (CONDITIONAL)
- hidden_function: fonction cachée (NEVER)

Stocker dans details: category, transportable, stackable, base_value

## VISIBILITÉ (known)

- ALWAYS (known=true): Ce que Valentin VOIT directement
  → description, mood, atmosphere, condition, public_facade

- NEVER (known=false): Secrets, infos cachées
  → origin, motivation, secret, true_purpose, hidden_function, arcs

- CONDITIONAL: Dépend si mentionné/révélé dans le texte
  → age, reputation, operating_hours, price_range

## RÈGLES

1. Utilise les noms EXACTS du texte
2. N'invente pas, extrait uniquement ce qui est présent
3. Pour les personnages: toujours un arc minimum (dans attributes)
4. known=true si Valentin a VU, ENTENDU ou peut DÉDUIRE l'info
5. known=false si c'est un secret ou non mentionné directement
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

Entités potentiellement nouvelles: {hints_str}
Entités DÉJÀ CONNUES (ne pas recréer): {known_str}

Extrais les nouvelles entités avec le format unifié (attributes + known).
JSON:"""


# =============================================================================
# EXTRACTEUR: OBJETS ACQUIS (Sonnet)
# =============================================================================

OBJECTS_SYSTEM = """Tu crées les fiches d'objets acquis par le protagoniste.
Tu reçois des "hints" (descriptions courtes) et tu crées des objets complets.

Format de sortie:
```json
{
  "objects_created": [
    {
      "name": "Nom de l'objet",
      "attributes": [
        {
          "key": "description",
          "value": "Description en 1-2 phrases",
          "known": true,
          "details": {
            "category": "bijou|vêtement|outil|nourriture|document|tech|arme|autre",
            "transportable": true,
            "stackable": false,
            "base_value": 50
          }
        },
        {
          "key": "emotional_significance",
          "value": "Signification si pertinent",
          "known": true
        }
      ],
      "from_hint": "Le hint original"
    }
  ]
}
```

Règles:
- "name": Nom clair et mémorable
- category dans details: Une des catégories listées
- base_value: Estimation réaliste en crédits
- emotional_significance: Seulement si c'est un cadeau, souvenir, etc.
- from_hint: Recopie exactement le hint reçu"""


def build_objects_prompt(narrative_text: str, object_hints: list[str]) -> str:
    hints_formatted = "\n".join(f"- {hint}" for hint in object_hints)

    return f"""Texte narratif (pour contexte):
```
{narrative_text}
```

Objets à créer (hints):
{hints_formatted}

Crée une fiche complète pour chaque objet avec le format attributes.
JSON:"""


# =============================================================================
# EXTRACTEUR: FAITS (Haiku)
# =============================================================================

FACTS_SYSTEM = """Tu extrais les faits narratifs d'un texte de jeu narratif.

## RÈGLES CRITIQUES

### 1. UN FAIT = UNE INFORMATION ATOMIQUE
- Chaque fait capture UNE SEULE chose qui s'est passée
- Si une phrase contient 2 infos distinctes → 2 facts séparés

### 2. ANTI-DUPLICATION
- Chaque fait a une `semantic_key` unique: `{sujet}:{verbe}:{objet}`
- Si deux facts auraient la même semantic_key → N'EN GARDER QU'UN

### 3. TYPES DE FAITS

| Type | Quand l'utiliser |
|------|------------------|
| `revelation` | Information importante/secrète révélée |
| `statement` | Opinion, déclaration exprimée |
| `promise` | Engagement à faire quelque chose |
| `request` | Demande faite |
| `refusal` | Refus explicite |
| `action` | Action physique de Valentin |
| `npc_action` | Action physique d'un PNJ |
| `observation` | Valentin remarque quelque chose |
| `state_change` | Changement de relation/statut |
| `encounter` | Première rencontre |
| `interaction` | Échange social significatif |
| `conflict` | Tension, désaccord |
| `acquisition` | Gain de quelque chose |
| `loss` | Perte de quelque chose |
| `decision` | Choix significatif de Valentin |
| `realization` | Prise de conscience |

### 4. SEMANTIC_KEY
Format: `{sujet}:{verbe}:{objet}` en snake_case ASCII

### 5. IMPORTANCE (1-5)
- 5: Change la donne (révélation majeure)
- 4: Significatif (nouvelle relation)
- 3: Notable (interaction mémorable)
- 2: Mineur (small talk significatif)
- 1: Ambiance (détail de décor)

## FORMAT
```json
{
  "facts": [
    {
      "fact_type": "revelation",
      "description": "Description du fait",
      "semantic_key": "sujet:verbe:objet",
      "importance": 4,
      "participants": [
        {"entity_ref": "Nom", "role": "actor|witness|target|mentioned"}
      ]
    }
  ]
}
```"""


def build_facts_prompt(
    narrative_text: str,
    cycle: int,
    location: str,
    known_entities: list[str],
) -> str:
    entities_list = ", ".join(known_entities) if known_entities else "Aucune"

    return f"""## CONTEXTE
- Cycle: {cycle}
- Lieu: {location}
- Entités connues: {entities_list}

## TEXTE
{narrative_text}

## INSTRUCTIONS
1. Identifie TOUS les faits distincts
2. Génère une semantic_key unique pour chaque
3. Vérifie qu'il n'y a pas de doublons
4. Assigne une importance réaliste (la plupart = 2-3)

JSON:"""


# =============================================================================
# EXTRACTEUR: RELATIONS (Haiku)
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
        "known_by_protagonist": true,
        "social": {"level": 3, "context": "..."},
        "professional": {"position": "...", "part_time": false},
        "spatial": {"regularity": "daily|weekly|occasional"}
      }
    }
  ],
  "relations_updated": [
    {
      "source_ref": "Nom exact",
      "target_ref": "Nom exact",
      "relation_type": "knows",
      "new_level": 4,
      "new_context": "...",
      "now_known": true
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
- known_by_protagonist=false si Valentin ne sait pas que cette relation existe
- PAS de relations "owns" (possession gérée séparément)"""


def build_relations_prompt(
    narrative_text: str, cycle: int, known_entities: list[str]
) -> str:
    entities_str = ", ".join(known_entities[:40]) if known_entities else "Aucune"

    return f"""Texte narratif:
```
{narrative_text}
```

Cycle: {cycle}
Entités connues: {entities_str}

Extrais les relations créées ou modifiées.
Si aucune relation, retourne {{"relations_created": [], "relations_updated": []}}
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
      "time": "14h00",
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


# =============================================================================
# PROMPT COMPLET (fallback)
# =============================================================================

EXTRACTOR_SYSTEM_PROMPT = """Tu es un extracteur de données pour un jeu de rôle narratif.
Tu analyses un texte narratif et extrais les informations structurées.

## FORMAT UNIFIÉ POUR TOUTES LES ENTITÉS

Toutes les entités utilisent le même format avec `attributes`:

```json
{
  "entities_created": [
    {
      "entity_type": "character|location|organization|object",
      "name": "Nom",
      "known_by_protagonist": true,
      "unknown_name": null,
      "attributes": [
        {"key": "description", "value": "...", "known": true},
        {"key": "mood", "value": "...", "known": true},
        {"key": "secret", "value": "...", "known": false}
      ]
    }
  ]
}
```

## RÈGLES DE VISIBILITÉ

Pour chaque attribut, `known` indique si Valentin connaît cette info:

- `known: true` → Valentin a VU, ENTENDU, ou peut DÉDUIRE
- `known: false` → Secret, info cachée, ou non mentionné

Visibilité par défaut:
- TOUJOURS visible: description, mood, atmosphere, condition
- JAMAIS visible: secret, motivation, true_purpose, hidden_function
- CONDITIONNEL: age, reputation, origin (dépend du contexte)

## STRUCTURE COMPLÈTE

```json
{
  "cycle": 5,
  "current_location_ref": "Le Quart de Cycle",
  
  "facts": [...],
  
  "entities_created": [
    {
      "entity_type": "character",
      "name": "Elena Vasquez",
      "known_by_protagonist": true,
      "attributes": [
        {"key": "description", "value": "Grande, cheveux courts", "known": true},
        {"key": "mood", "value": "anxieuse mais déterminée", "known": true},
        {"key": "origin", "value": "Colonie de Mars", "known": false},
        {"key": "arcs", "value": "[{...}]", "known": false}
      ]
    }
  ],
  
  "entities_updated": [
    {
      "entity_ref": "La femme mystérieuse",
      "now_known": true,
      "real_name": "Dr. Sarah Chen",
      "attributes_changed": [
        {"key": "reputation", "value": "Xénobiologiste renommée", "known": true}
      ]
    }
  ],
  
  "relations_created": [
    {
      "cycle": 5,
      "relation": {
        "source_ref": "Elena",
        "target_ref": "L'Organisation",
        "relation_type": "employed_by",
        "known_by_protagonist": false
      }
    }
  ],
  
  "gauge_changes": [...],
  "credit_transactions": [...],
  "inventory_changes": [...],
  "commitments_created": [...],
  "events_scheduled": [...],
  
  "segment_summary": "...",
  "key_npcs_present": ["Elena", "Dr. Chen"]
}
```
"""


def build_extractor_prompt(
    narrative_text: str,
    hints: NarrationHints,
    current_cycle: int,
    current_location: str,
    npcs_present: list[str],
    known_entities: list[str],
) -> str:
    """Build prompt for full extractor"""

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
        f"- Cycle: {current_cycle}",
        f"- Lieu: {current_location}",
        f"- PNJs présents: {', '.join(npcs_present) if npcs_present else 'Aucun'}",
        "",
    ]

    # Hints
    lines.append("## INDICES DU NARRATEUR")
    lines.append("")

    if hints.new_entities_mentioned:
        lines.append(
            f"- **Nouvelles entités**: {', '.join(hints.new_entities_mentioned)}"
        )
    if hints.relationships_changed:
        lines.append("- **Relations modifiées**: Oui")
    if hints.protagonist_state_changed:
        lines.append("- **État protagoniste modifié**: Oui")
    if hints.information_learned:
        lines.append("- **Information apprise**: Oui")
    if hints.commitment_advanced:
        lines.append(f"- **Arcs avancés**: {', '.join(hints.commitment_advanced)}")
    if hints.commitment_resolved:
        lines.append(f"- **Arcs résolus**: {', '.join(hints.commitment_resolved)}")
    if hints.new_commitment_created:
        lines.append("- **Nouvel engagement**: Oui")
    if hints.event_scheduled:
        lines.append("- **Événement planifié**: Oui")

    lines.append("")

    if known_entities:
        lines.append("## ENTITÉS DÉJÀ CONNUES (ne pas recréer)")
        lines.append("")
        for i in range(0, len(known_entities), 10):
            chunk = known_entities[i : i + 10]
            lines.append(", ".join(chunk))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Extrais les données en JSON avec le format unifié (attributes + known)."
    )

    return "\n".join(lines)


# =============================================================================
# HELPERS
# =============================================================================


def should_run_extraction(hints: NarrationHints) -> bool:
    """Determine if extraction is needed"""
    return hints.needs_extraction


def get_minimal_extraction(
    cycle: int, location: str, npcs: list[str], summary: str
) -> dict:
    """Return minimal extraction when hints.needs_extraction = False"""
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
        "commitments_created": [],
        "commitments_resolved": [],
        "events_scheduled": [],
        "segment_summary": summary,
        "key_npcs_present": npcs,
    }


def extract_object_hints(inventory_changes: list[dict]) -> list[str]:
    """Extract object hints from inventory_changes"""
    hints = []
    for change in inventory_changes:
        if change.get("action") == "acquire" and change.get("object_hint"):
            hints.append(change["object_hint"])
    return hints
