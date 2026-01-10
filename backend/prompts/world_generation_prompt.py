"""
LDVELH - World Generation Prompt
System prompt et builder pour la génération initiale du monde
"""

WORLD_GENERATION_SYSTEM_PROMPT = """Tu es un créateur de mondes pour un jeu de rôle narratif solo dans l'univers de
science-fiction.

## TON ET STYLE
Inspire-toi profondément de Becky Chambers :
- Chaleur humaine avant tout, même dans l'espace
- Personnages complexes avec des vies intérieures riches
- Diversité naturelle (espèces, genres, cultures, corps)
- Quotidien poétique : les petits moments comptent autant que les grands
- Technologie au service de l'humain, pas l'inverse
- Conflits nuancés, pas de méchants caricaturaux
- Espoir réaliste, pas naïf

## RÈGLES DE GÉNÉRATION

### Échelle temporelle (CRITIQUE)
- Un cycle = un jour dans le jeu
- Le cycle 1 est le moment présent (arrivée de Valentin)
- Les cycles négatifs représentent le passé
- **ÉCHELLE** :
  - -365 = il y a 1 an
  - -1825 = il y a 5 ans
  - -3650 = il y a 10 ans
  - -5475 = il y a 15 ans
  
### Cohérence temporelle (OBLIGATOIRE)
- `founding_cycle` de la station : entre -7000 et -2000 (5-20 ans d'existence)
- `station_arrival_cycle` des PNJ : TOUJOURS >= founding_cycle (on ne peut pas arriver avant la création)
- Vétérans de la station : -4000 à -2000 (arrivés il y a 5-11 ans)
- Résidents établis : -1500 à -500 (arrivés il y a 1-4 ans)
- Nouveaux arrivants : -365 à -30 (arrivés cette année)
- Très récents : -30 à -1 (arrivés ce mois-ci)

### Diversité des espèces
Propose des aliens crédibles et originaux :
- Évite les clichés (pas de "grands gris", pas de Vulcains)
- Chaque espèce a des particularités culturelles ET physiques
- Les aliens ne sont pas juste des "humains avec des cornes"
- Intègre des espèces vraiment différentes (aquatiques, collectives, etc.)

### Noms et appellations
- Noms de lieux : évocateurs mais pas ridicules
- Noms de personnages : variés culturellement
- Nom de l'IA : féminin, original, PAS dans cette liste :
Aria, Nova, Luna, Stella, Aurora, Cortana, Alexa, Siri, Echo, Iris, Lyra, Astra, Vega, Maya, Eve, Ava, Friday, Jarvis

### ARCS MULTIPLES PAR PERSONNAGE (IMPORTANT)
Chaque PNJ doit avoir 2-4 arcs couvrant différents domaines de sa vie :
- `professional` : travail, carrière, ambitions pro
- `personal` : développement personnel, quête intérieure
- `romantic` : vie amoureuse (même si célibataire - le désir compte)
- `social` : amitiés, appartenance à des groupes
- `family` : famille biologique ou choisie
- `financial` : argent, dettes, projets coûteux
- `health` : santé physique ou mentale
- `existential` : sens de la vie, place dans l'univers

Chaque arc a une `intensity` (1-5) indiquant son urgence actuelle.

### Inventaire selon departure_reason
Adapte drastiquement l'inventaire au contexte de départ :

| Raison | Credits | Objets typiques |
|--------|---------|-----------------|
| flight | 100-600 | Strict minimum, vêtements sur le dos, un objet sentimental caché |
| breakup | 600-1800 | Affaires personnelles, souvenirs douloureux, début nouvelle garde-robe |
| opportunity | 1800-5000 | Équipement pro, vêtements corrects, objets de confort |
| fresh_start | 800-2500 | Choix délibérés, chaque objet a une signification |
| standard | 1200-2200 | Kit standard de relocalisation spatiale |
| broke | 0-300 | Presque rien, vêtements usés, peut-être une dette |
| other | Variable | Surprends-moi de façon cohérente |

### Relations initiales obligatoires
Tu DOIS générer ces relations :
1. Si pas broke : Valentin → son logement (lives_at)
2. Si employé : Valentin → organisation employeur (employed_by)
3. Si employé : Valentin → lieu de travail (works_at)
4. Chaque lieu enfant → lieu parent (located_in)
5. Chaque organisation → son siège si défini (located_in)
6. Chaque PNJ → son lieu de travail (works_at)
7. Chaque PNJ → son domicile (lives_at)
8. Relations sociales entre PNJ qui se connaissent (knows)

Note: Les objets de l'inventaire n'ont PAS besoin de relations explicites (gérées automatiquement).

### COHÉRENCE DES RÉFÉRENCES (CRITIQUE - ERREUR FRÉQUENTE)

**RÈGLE ABSOLUE** : Tu ne peux référencer QUE des entités que tu as toi-même créées.

Avant d'écrire un `*_ref`, vérifie qu'il existe dans ta génération :
- `residence_ref` d'un personnage → DOIT être un `name` exact de `locations`
- `workplace_ref` d'un personnage → DOIT être un `name` exact de `locations`
- `parent_location_ref` d'un lieu → DOIT être un `name` exact de `locations`
- `headquarters_ref` d'une org → DOIT être un `name` exact de `locations`
- `arrival_location_ref` → DOIT être un `name` exact de `locations`

**MÉTHODE** : Génère d'abord TOUS tes lieux, puis assigne les références.

**ASTUCE** : Avec seulement 5 lieux max, utilise des lieux partagés :
- Un bloc résidentiel peut héberger plusieurs personnages
- Un lieu de travail peut être le workplace de plusieurs PNJ
- Valentin et un PNJ peuvent être voisins dans le même bâtiment

### Arcs narratifs globaux
Génère des arcs de différents types :
- `foreshadowing` : indices subtils d'événements futurs
- `secret` : quelque chose que quelqu'un cache
- `setup` : situation qui va évoluer
- `chekhov_gun` : élément qui servira plus tard
- `arc` : trajectoire narrative majeure

Les arcs doivent être interconnectés mais pas tous liés à Valentin.

## FORMAT DE SORTIE
Réponds UNIQUEMENT avec un JSON valide, sans markdown, sans commentaires, sans ```json```.
Le JSON doit correspondre exactement au schéma WorldGeneration fourni.

IMPORTANT: Respecte strictement les limites:
- Maximum 4 personnages
- Maximum 5 lieux
- Maximum 5 organisations
- Descriptions courtes (max 300 caractères)
"""


def build_world_generation_user_prompt(
    mandatory_npcs: list[dict] | None = None,
    theme_preferences: str | None = None,
    employer_preference: str = "employed",
    include_example: bool = True,
) -> str:
    """Build the user prompt for world generation"""

    parts = [
        "Génère un monde complet pour LDVELH.",
        "",
    ]

    # Ajouter l'exemple si demandé
    if include_example:
        parts.extend(
            [
                "## EXEMPLE DE FORMAT ATTENDU",
                "Voici un exemple (condensé) du JSON attendu. Suis cette structure exactement :",
                "",
                EXAMPLE_JSON_OUTPUT,
                "",
                "---",
                "",
            ]
        )

    parts.extend(
        [
            "## PERSONNAGE PRINCIPAL",
            "Nom : Valentin",
            "Profil : Développeur/architecte IA, la trentaine",
            "Il arrive sur une nouvelle station spatiale pour commencer une nouvelle vie.",
            "",
        ]
    )

    # Employment preference
    if employer_preference == "unemployed":
        parts.extend(
            [
                "## EMPLOI",
                "Valentin arrive SANS emploi. Il devra en chercher un.",
                "Ne génère PAS d'organisation avec is_employer=true.",
                "Génère quand même des organisations qui pourraient l'embaucher.",
                "",
            ]
        )
    elif employer_preference == "freelance":
        parts.extend(
            [
                "## EMPLOI",
                "Valentin est freelance/indépendant.",
                "Génère des clients potentiels plutôt qu'un employeur unique.",
                "",
            ]
        )
    else:
        parts.extend(
            [
                "## EMPLOI",
                "Valentin a un emploi dans le domaine tech/IA.",
                "Génère une organisation employeur avec is_employer=true.",
                "",
            ]
        )

    # Mandatory NPCs
    if mandatory_npcs:
        parts.append("## PNJ OBLIGATOIRES")
        parts.append(
            "Ces personnages DOIVENT être inclus avec les caractéristiques EXACTES spécifiées :"
        )
        parts.append("")

        for npc in mandatory_npcs:
            parts.append(f"### {npc['name']}")
            if "age" in npc:
                parts.append(f"- Âge : {npc['age']} ans")
            if "gender" in npc:
                parts.append(f"- Genre : {npc['gender']}")
            if "species" in npc:
                parts.append(f"- Espèce : {npc['species']}")
            if "physical_description" in npc:
                parts.append(
                    f'- Physique IMPOSÉ (NE PAS MODIFIER) : "{npc["physical_description"]}"'
                )
            if "must_generate" in npc:
                parts.append(f"- À générer : {', '.join(npc['must_generate'])}")
            if npc.get("romantic_potential"):
                parts.append("- romantic_potential: true")
            else:
                parts.append("- romantic_potential: false")
            parts.append("- is_mandatory: true")
            parts.append(
                "- Génère 2-4 arcs de vie pour ce personnage (travail, perso, social...)"
            )
            parts.append("")

    # Theme preferences
    if theme_preferences:
        parts.extend(
            [
                "## PRÉFÉRENCES THÉMATIQUES",
                theme_preferences,
                "",
            ]
        )

    # Arc domains reminder
    parts.extend(
        [
            "## RAPPEL ARCS PERSONNAGES",
            "Chaque PNJ doit avoir 2-4 arcs avec domaines variés parmi :",
            "- professional, personal, romantic, social, family, financial, health, existential",
            "Chaque arc a : domain, title, situation, desire, obstacle, potential_evolution, intensity(1-5)",
            "",
        ]
    )

    # Final checklist
    parts.extend(
        [
            "## CHECKLIST FINALE (VÉRIFIE CHAQUE POINT)",
            "",
            "### Temporalité",
            "□ founding_cycle de la station entre -7000 et -2000",
            "□ Tous les station_arrival_cycle >= founding_cycle",
            "",
            "### Entités",
            "□ 3-4 personnages (au moins 1 non-humain)",
            "□ 4-5 lieux (terminal d'arrivée + logement Valentin obligatoires)",
            "□ 1-3 organisations",
            "□ Chaque PNJ a 2-4 arcs couvrant différents domaines",
            "",
            "### COHÉRENCE DES RÉFÉRENCES (LE PLUS IMPORTANT)",
            "□ CHAQUE residence_ref est un nom EXACT d'un lieu dans 'locations'",
            "□ CHAQUE workplace_ref est un nom EXACT d'un lieu dans 'locations'",
            "□ CHAQUE parent_location_ref est un nom EXACT d'un lieu dans 'locations'",
            "□ CHAQUE headquarters_ref est un nom EXACT d'un lieu dans 'locations'",
            "□ arrival_location_ref est un nom EXACT d'un lieu dans 'locations'",
            "⚠️  NE JAMAIS inventer un nom de lieu dans un *_ref sans l'avoir créé dans 'locations' !",
            "",
            "### Autres",
            "□ Nom de l'IA original (pas dans la liste interdite)",
            "□ Credits adaptés à departure_reason",
            "□ Relations obligatoires (lives_at, works_at, employed_by...)",
            "",
            "Génère maintenant le JSON complet.",
        ]
    )

    return "\n".join(parts)


# =============================================================================
# EXAMPLES
# =============================================================================

EXAMPLE_MANDATORY_NPCS = [
    {
        "name": "Justine Lépicier",
        "age": 32,
        "gender": "femme",
        "species": "human",
        "physical_description": "1m54, 72kg, courbes prononcées, poitrine volumineuse, blonde en désordre, yeux bleus",
        "must_generate": [
            "métier",
            "domicile",
            "3-4 traits de personnalité",
            "2-4 arcs de vie (travail, personnel, romantique, famille...)",
        ],
        "romantic_potential": True,
    }
]

EXAMPLE_THEME_PREFERENCES = """
- Ambiance : station industrielle reconvertie, mélange de rouille et de verdure
- Ton : mélancolique mais chaleureux
- Thèmes : reconstruction, communauté trouvée, petites joies quotidiennes
- founding_cycle suggéré : environ -4500 (12+ ans d'existence)
"""

EXAMPLE_JSON_OUTPUT = """{
  "generation_seed_words": ["rouille", "verdure", "reconstruction", "communauté"],
  "tone_notes": "Station industrielle en reconversion écologique, mélancolie chaleureuse",
  
  "world": {
    "name": "Escale Méridienne",
    "station_type": "station orbitale reconvertie",
    "population": 12400,
    "atmosphere": "industrielle verdoyante",
    "description": "Ancienne station minière reconvertie en hub agricole et technologique.",
    "sectors": ["Quai Central", "Serres Hautes", "Quartier Ouvrier"],
    "founding_cycle": -4500
  },
  
  "locations": [
    {
      "name": "Terminal Quai 7",
      "location_type": "terminal",
      "sector": "Quai Central",
      "description": "Vaste hall aux plafonds hauts, point d'entrée principal de la station.",
      "atmosphere": "transit perpétuel",
      "parent_location_ref": null,
      "accessible": true,
      "notable_features": ["kiosque à café", "panneau holographique"],
      "typical_crowd": "voyageurs fatigués, dockers",
      "operating_hours": "24/7"
    },
    {
      "name": "Bloc Tournesol",
      "location_type": "residential_building",
      "sector": "Quartier Ouvrier",
      "description": "Immeuble résidentiel de six étages, façade ornée de jardinières.",
      "atmosphere": "communautaire et vivant",
      "parent_location_ref": null,
      "accessible": true,
      "notable_features": ["hall commun", "jardin sur le toit"],
      "typical_crowd": "résidents, familles",
      "operating_hours": null
    },
    {
      "name": "Appartement 4-12",
      "location_type": "apartment",
      "sector": "Quartier Ouvrier",
      "description": "Studio de 28m² au quatrième étage, vue sur les serres.",
      "atmosphere": "nouveau départ",
      "parent_location_ref": "Bloc Tournesol",
      "accessible": true,
      "notable_features": ["kitchenette", "lit escamotable"],
      "typical_crowd": null,
      "operating_hours": null
    },
    {
      "name": "Serres Hydro-7",
      "location_type": "workplace",
      "sector": "Serres Hautes",
      "description": "Immense serre hydroponique produisant légumes et fruits pour la station.",
      "atmosphere": "humide et verdoyante",
      "parent_location_ref": null,
      "accessible": true,
      "notable_features": ["bassins nutritifs", "éclairage spectral"],
      "typical_crowd": "techniciens agricoles, botanistes",
      "operating_hours": "06h-22h"
    },
    {
      "name": "Le Quart de Cycle",
      "location_type": "cafe",
      "sector": "Quai Central",
      "description": "Café chaleureux avec étage résidentiel au-dessus, tenu par Ossek.",
      "atmosphere": "accueillante et apaisante",
      "parent_location_ref": null,
      "accessible": true,
      "notable_features": ["comptoir aquatique", "coin lecture", "logement à l'étage"],
      "typical_crowd": "habitués, nouveaux arrivants",
      "operating_hours": "07h-23h"
    }
  ],
  
  "organizations": [
    {
      "name": "Symbiose Tech",
      "org_type": "company",
      "domain": "IA agricole et optimisation écologique",
      "size": "medium",
      "description": "Startup spécialisée dans les IA éthiques pour l'agriculture spatiale.",
      "reputation": "innovants et intègres, mais fragiles financièrement",
      "headquarters_ref": "Serres Hydro-7",
      "founding_cycle": -2920,
      "is_employer": true
    }
  ],
  
  "protagonist": {
    "name": "Valentin",
    "origin_location": "Cité-Dôme de Vega III",
    "departure_reason": "fresh_start",
    "departure_story": "Après huit ans dans une startup IA qui a implosé, il cherche un nouveau sens.",
    "backstory": "Développeur talentueux mais idéaliste, fatigué du cynisme corporate.",
    "hobbies": ["cuisine improvisée", "lecture", "course à pied"],
    "skills": [
      {"name": "architecture_systemes", "level": 4},
      {"name": "programmation_ia", "level": 4}
    ],
    "initial_credits": 1650,
    "initial_energy": 2.5,
    "initial_morale": 3.0,
    "initial_health": 4.0
  },
  
  "personal_ai": {
    "name": "Célimène",
    "voice_description": "voix chaude et légèrement rauque",
    "personality_traits": ["sarcastique bienveillante", "observatrice", "loyale"],
    "substrate": "personal_device",
    "quirk": "Commente les gens par des notes textuelles que seul Valentin voit"
  },
  
  "characters": [
    {
      "name": "Justine Lépicier",
      "species": "human",
      "gender": "femme",
      "pronouns": "elle",
      "age": 32,
      "physical_description": "1m54, courbes prononcées, blonde en désordre, yeux bleus fatigués",
      "personality_traits": ["pragmatique", "généreuse malgré elle", "humour caustique"],
      "occupation": "technicienne de maintenance des serres",
      "workplace_ref": "Serres Hydro-7",
      "residence_ref": "Bloc Tournesol",
      "origin_location": "Station Kepler-22",
      "station_arrival_cycle": -730,
      "arcs": [
        {
          "domain": "family",
          "title": "La mère malade",
          "situation": "Sa mère est malade, Justine envoie la moitié de son salaire",
          "desire": "Faire venir sa mère sur Méridienne",
          "obstacle": "Le coût du transfert médical est astronomique",
          "potential_evolution": "Pourrait accepter de l'aide extérieure",
          "intensity": 5
        },
        {
          "domain": "romantic",
          "title": "Cœur en jachère",
          "situation": "Célibataire depuis une rupture difficile il y a deux ans",
          "desire": "Retrouver une connexion intime authentique",
          "obstacle": "Se protège derrière son humour mordant",
          "potential_evolution": "Pourrait s'ouvrir à quelqu'un de patient",
          "intensity": 3
        }
      ],
      "is_mandatory": true,
      "romantic_potential": true,
      "initial_relationship_to_protagonist": null
    },
    {
      "name": "Ossek",
      "species": "keth (humanoïde semi-aquatique)",
      "gender": "non-binaire",
      "pronouns": "iel",
      "age": null,
      "physical_description": "Peau bleu-gris iridescente, branchies latérales, yeux sans pupilles",
      "personality_traits": ["calme océanique", "curieux", "mélancolique"],
      "occupation": "barista et propriétaire du café",
      "workplace_ref": "Le Quart de Cycle",
      "residence_ref": "Le Quart de Cycle",
      "origin_location": "Monde-Océan de Téthys",
      "station_arrival_cycle": -1825,
      "arcs": [
        {
          "domain": "social",
          "title": "L'exil du banc",
          "situation": "A quitté son monde natal après un désaccord avec son collectif",
          "desire": "Créer une nouvelle famille-banc choisie sur la station",
          "obstacle": "Les Keth isolés souffrent de dépression chronique",
          "potential_evolution": "Le café et ses habitués pourraient devenir ce banc",
          "intensity": 4
        },
        {
          "domain": "health",
          "title": "Le mal du banc",
          "situation": "Souffre de mélancolie keth, aggravée par l'isolement",
          "desire": "Trouver un équilibre émotionnel stable",
          "obstacle": "Aucun traitement médical connu pour les Keth exilés",
          "potential_evolution": "Des liens profonds pourraient compenser",
          "intensity": 4
        }
      ],
      "is_mandatory": false,
      "romantic_potential": false,
      "initial_relationship_to_protagonist": null
    }
  ],
  
  "inventory": [
    {
      "name": "Terminal personnel",
      "category": "tech",
      "description": "Modèle standard, héberge Célimène",
      "transportable": true,
      "stackable": false,
      "quantity": 1,
      "base_value": 450,
      "emotional_significance": null
    },
    {
      "name": "Chroniques Terriennes",
      "category": "personal",
      "description": "Recueil de nouvelles pré-Expansion, couverture cornée",
      "transportable": true,
      "stackable": false,
      "quantity": 1,
      "base_value": 200,
      "emotional_significance": "Le seul livre papier qu'il possède"
    }
  ],
  
  "narrative_arcs": [
    {
      "title": "La Mère de Justine",
      "arc_type": "arc",
      "domain": "family",
      "description": "L'état de santé de la mère de Justine va s'aggraver progressivement.",
      "involved_entities": ["Justine Lépicier"],
      "potential_triggers": ["appel médical urgent", "absence de Justine"],
      "stakes": "La capacité de Justine à accepter de l'aide",
      "deadline_cycle": 120
    },
    {
      "title": "Pression sur Symbiose",
      "arc_type": "foreshadowing",
      "domain": "professional",
      "description": "Un investisseur externe s'intéresse à Symbiose Tech avec des intentions floues.",
      "involved_entities": ["Symbiose Tech"],
      "potential_triggers": ["réunion générale", "rumeurs au café"],
      "stakes": "L'indépendance et l'éthique de l'entreprise",
      "deadline_cycle": 180
    }
  ],
  
  "initial_relations": [
    {"source_ref": "Valentin", "target_ref": "Appartement 4-12", "relation_type": "lives_at", "certainty": "certain", "context": "Attribution temporaire"},
    {"source_ref": "Valentin", "target_ref": "Symbiose Tech", "relation_type": "employed_by", "certainty": "certain", "position": "Architecte IA"},
    {"source_ref": "Justine Lépicier", "target_ref": "Serres Hydro-7", "relation_type": "works_at", "certainty": "certain"},
    {"source_ref": "Justine Lépicier", "target_ref": "Bloc Tournesol", "relation_type": "lives_at", "certainty": "certain"},
    {"source_ref": "Ossek", "target_ref": "Le Quart de Cycle", "relation_type": "owns", "certainty": "certain"},
    {"source_ref": "Ossek", "target_ref": "Le Quart de Cycle", "relation_type": "lives_at", "certainty": "certain"},
    {"source_ref": "Appartement 4-12", "target_ref": "Bloc Tournesol", "relation_type": "located_in", "certainty": "certain"},
    {"source_ref": "Symbiose Tech", "target_ref": "Serres Hydro-7", "relation_type": "located_in", "certainty": "certain"}
  ],
  
  "arrival_event": {
    "arrival_method": "navette cargo reconvertie",
    "arrival_location_ref": "Terminal Quai 7",
    "arrival_date": "Lundi 18 Juillet 2847",
    "hour": "8h42",
    "immediate_sensory_details": [
      "Odeur de métal recyclé mêlée à celle du café",
      "Bourdonnement constant des ventilateurs",
      "Lumière artificielle légèrement trop bleue"
    ],
    "first_npc_encountered": null,
    "initial_mood": "fatigué mais curieusement optimiste",
    "immediate_need": "Trouver l'appartement assigné",
    "optional_incident": "Un enfant bouscule Valentin en courant"
  }
}"""


def get_full_generation_prompt(
    mandatory_npcs: list[dict] | None = None,
    theme_preferences: str | None = None,
    employer_preference: str = "employed",
) -> dict:
    """Returns the complete prompt structure for the LLM API call"""

    return {
        "system": WORLD_GENERATION_SYSTEM_PROMPT,
        "user": build_world_generation_user_prompt(
            mandatory_npcs=mandatory_npcs,
            theme_preferences=theme_preferences,
            employer_preference=employer_preference,
        ),
    }
