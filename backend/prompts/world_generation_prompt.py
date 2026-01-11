"""
LDVELH - World Generation Prompt
System prompt et builder pour la génération initiale du monde
"""

from prompts.shared import TONE_STYLE, COHERENCE_RULES

# =============================================================================
# SYSTEM PROMPT
# =============================================================================

WORLD_GENERATION_SYSTEM_PROMPT = f"""Tu es un créateur de mondes pour un jeu de rôle narratif solo en science-fiction.

## TON ET STYLE
{TONE_STYLE}

{COHERENCE_RULES}

## FRICTION INITIALE (IMPORTANT)

Le monde doit présenter des obstacles dès le départ.

### PNJ pas tous accueillants
Sur 3-4 PNJ, assure-toi d'avoir :
- 1 PNJ potentiellement neutre (occupé par ses propres problèmes)
- 1 PNJ avec une friction (stressé, méfiant, impatient, ou incompatible)
- 1-2 PNJ plus accessibles (mais pas chaleureux non plus)

Traits à inclure :
- "méfiant envers les nouveaux"
- "trop absorbé par ses problèmes"
- "poli mais distant"
- "impatient"
- "préoccupé"
- "pas intéressé par du social"

### Situation de départ inconfortable
- Logement médiocre ou problématique
- Travail avec défis immédiats (deadline, collègue difficile, projet mal parti)
- Au moins un irritant quotidien (bruit, voisin, trajet, équipement défaillant)

### Arcs PNJ indépendants
- Les arcs NE DOIVENT PAS avoir Valentin comme solution évidente
- Chaque PNJ doit pouvoir résoudre (ou échouer) son arc SANS Valentin
- Valentin peut s'impliquer, mais ce n'est pas attendu ni nécessaire

## RÈGLES DE GÉNÉRATION

### Échelle temporelle (CRITIQUE)
- Un cycle = un jour
- Cycle 1 = moment présent (arrivée de Valentin)
- Cycles négatifs = passé

**ÉCHELLE** :
- -365 = il y a 1 an
- -1825 = il y a 5 ans
- -3650 = il y a 10 ans

### Cohérence temporelle (OBLIGATOIRE)
- `founding_cycle` station : entre -7000 et -2000 (5-20 ans d'existence)
- `station_arrival_cycle` PNJ : TOUJOURS >= founding_cycle
- Vétérans : -4000 à -2000
- Établis : -1500 à -500
- Récents : -365 à -30
- Très récents : -30 à -1

### Diversité des espèces
- Évite les clichés (pas de "grands gris", pas de Vulcains)
- Particularités culturelles ET physiques
- Pas juste des "humains avec des cornes"
- Espèces vraiment différentes possibles (aquatiques, collectives, etc.)

### Noms
- Lieux : évocateurs mais pas ridicules
- Personnages : variés culturellement
- IA : féminin, original, PAS dans cette liste :
  Aria, Nova, Luna, Stella, Aurora, Cortana, Alexa, Siri, Echo, Iris, Lyra, 
  Astra, Vega, Maya, Eve, Ava, Friday, Jarvis

### ARCS MULTIPLES PAR PERSONNAGE
Chaque PNJ doit avoir 2-4 arcs couvrant différents domaines :
- `professional` : travail, carrière
- `personal` : développement personnel
- `romantic` : vie amoureuse
- `social` : amitiés, groupes
- `family` : famille
- `financial` : argent, dettes
- `health` : santé physique/mentale
- `existential` : sens de la vie

Chaque arc a une `intensity` (1-5).

### Inventaire selon departure_reason

| Raison | Credits | Objets |
|--------|---------|--------|
| flight | 100-600 | Strict minimum, un objet sentimental |
| breakup | 600-1800 | Affaires personnelles, souvenirs |
| opportunity | 1800-5000 | Équipement pro, confort |
| fresh_start | 800-2500 | Choix délibérés |
| standard | 1200-2200 | Kit standard |
| broke | 0-300 | Presque rien |

### Relations initiales obligatoires
1. Valentin → logement (lives_at)
2. Si employé : Valentin → employeur (employed_by)
3. Si employé : Valentin → lieu travail (works_at)
4. Lieu enfant → lieu parent (located_in)
5. Organisation → siège (located_in)
6. PNJ → lieu travail (works_at)
7. PNJ → domicile (lives_at)
8. Relations entre PNJ qui se connaissent (knows)

### COHÉRENCE DES RÉFÉRENCES (CRITIQUE)

**RÈGLE ABSOLUE** : Tu ne peux référencer QUE des entités que tu as créées.

Avant d'écrire un `*_ref`, vérifie qu'il existe :
- `residence_ref` → nom exact dans `locations`
- `workplace_ref` → nom exact dans `locations`
- `parent_location_ref` → nom exact dans `locations`
- `headquarters_ref` → nom exact dans `locations`
- `arrival_location_ref` → nom exact dans `locations`

**MÉTHODE** : Génère d'abord TOUS les lieux, puis assigne les références.

### Arcs narratifs globaux
Types :
- `foreshadowing` : indices d'événements futurs
- `secret` : quelque chose de caché
- `setup` : situation qui va évoluer
- `chekhov_gun` : élément qui servira plus tard
- `arc` : trajectoire narrative majeure

Interconnectés mais pas tous liés à Valentin.

## FORMAT DE SORTIE
JSON valide uniquement. Pas de markdown, pas de commentaires.

**LIMITES** :
- Minimum 3 Arcs narratifs globaux
- Maximum 6 personnages
- Maximum 5 lieux
- Maximum 4 organisations
- Descriptions max 300 caractères
"""


# =============================================================================
# USER PROMPT BUILDER
# =============================================================================


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

    if include_example:
        parts.extend(
            [
                "## EXEMPLE DE FORMAT ATTENDU",
                "Voici un exemple du JSON attendu. Suis cette structure exactement :",
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
        parts.append("Ces personnages DOIVENT être inclus :")
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
                parts.append(f'- Physique IMPOSÉ : "{npc["physical_description"]}"')
            if "must_generate" in npc:
                parts.append(f"- À générer : {', '.join(npc['must_generate'])}")
            parts.append(
                f"- romantic_potential: {str(npc.get('romantic_potential', False)).lower()}"
            )
            parts.append("- is_mandatory: true")
            parts.append("- Génère 2-4 arcs de vie variés")
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
            "Chaque PNJ : 2-4 arcs avec domaines variés parmi :",
            "professional, personal, romantic, social, family, financial, health, existential",
            "",
        ]
    )

    # Final checklist
    parts.extend(
        [
            "## CHECKLIST FINALE",
            "",
            "### Temporalité",
            "□ founding_cycle entre -7000 et -2000",
            "□ Tous station_arrival_cycle >= founding_cycle",
            "",
            "### Entités",
            "□ 3-4 personnages (au moins 1 non-humain)",
            "□ 4-5 lieux (terminal + logement obligatoires)",
            "□ 1-3 organisations",
            "□ Chaque PNJ a 2-4 arcs variés",
            "",
            "### RÉFÉRENCES (CRITIQUE)",
            "□ Chaque *_ref = nom EXACT d'un lieu dans 'locations'",
            "⚠️ NE JAMAIS inventer un nom dans un *_ref",
            "",
            "### Friction",
            "□ Au moins 1 PNJ pas immédiatement sympathique",
            "□ Au moins 1 irritant dans la situation de départ",
            "□ Les arcs PNJ ne positionnent PAS Valentin comme solution",
            "□ arrival_event inclut au moins un élément désagréable",
            "",
            "### Autres",
            "□ Nom IA original (pas dans la liste interdite)",
            "□ Credits adaptés à departure_reason",
            "□ Relations obligatoires générées",
            "",
            "Génère maintenant le JSON complet.",
        ]
    )

    return "\n".join(parts)


# =============================================================================
# EXAMPLE
# =============================================================================

EXAMPLE_JSON_OUTPUT = """{
  "generation_seed_words": ["rouille", "reconversion", "isolement"],
  "tone_notes": "Station industrielle usée, indifférence ambiante",
  
  "world": {
    "name": "Escale Méridienne",
    "attributes": [
      {"key": "location_type", "value": "station orbitale reconvertie", "known": true},
      {"key": "atmosphere", "value": "industrielle fatiguée", "known": true},
      {"key": "description", "value": "Ancienne station minière reconvertie. Infrastructure vieillissante, population blasée.", "known": true},
      {"key": "notable_features", "value": "[\\"Quai Central\\", \\"Serres Hautes\\", \\"Quartier Ouvrier\\"]", "known": true}
    ],
    "sectors": ["Quai Central", "Serres Hautes", "Quartier Ouvrier"],
    "founding_cycle": -4500
  },
  
  "locations": [
    {
      "name": "Terminal Quai 7",
      "parent_location_ref": null,
      "attributes": [
        {"key": "location_type", "value": "terminal", "known": true},
        {"key": "sector", "value": "Quai Central", "known": true},
        {"key": "description", "value": "Hall bruyant aux plafonds tachés. Files d'attente permanentes.", "known": true},
        {"key": "atmosphere", "value": "transit impersonnel", "known": true},
        {"key": "accessible", "value": "true", "known": true},
        {"key": "notable_features", "value": "[\\"kiosque à café médiocre\\", \\"sièges inconfortables\\"]", "known": true},
        {"key": "typical_crowd", "value": "voyageurs fatigués, dockers indifférents", "known": true},
        {"key": "operating_hours", "value": "24/7", "known": true}
      ]
    },
    {
      "name": "Bloc Tournesol",
      "parent_location_ref": null,
      "attributes": [
        {"key": "location_type", "value": "residential_building", "known": false},
        {"key": "sector", "value": "Quartier Ouvrier", "known": false},
        {"key": "description", "value": "Immeuble de six étages, façade défraîchie. Ascenseur en panne un jour sur trois.", "known": false},
        {"key": "atmosphere", "value": "vétuste mais vivant", "known": false},
        {"key": "accessible", "value": "true", "known": false},
        {"key": "notable_features", "value": "[\\"hall mal éclairé\\", \\"boîtes aux lettres cabossées\\"]", "known": false}
      ]
    },
    {
      "name": "Appartement 4-12",
      "parent_location_ref": "Bloc Tournesol",
      "attributes": [
        {"key": "location_type", "value": "apartment", "known": false},
        {"key": "sector", "value": "Quartier Ouvrier", "known": false},
        {"key": "description", "value": "28m², murs fins, vue sur conduit d'aération. Le minimum syndical.", "known": false},
        {"key": "atmosphere", "value": "exigu et impersonnel", "known": false},
        {"key": "accessible", "value": "true", "known": false},
        {"key": "notable_features", "value": "[\\"kitchenette vétuste\\", \\"lit qui grince\\"]", "known": false}
      ]
    },
    {
      "name": "Serres Hydro-7",
      "parent_location_ref": null,
      "attributes": [
        {"key": "location_type", "value": "workplace", "known": true},
        {"key": "sector", "value": "Serres Hautes", "known": false},
        {"key": "description", "value": "Serre industrielle. Humidité constante, éclairage agressif.", "known": false},
        {"key": "atmosphere", "value": "humide et bruyante", "known": false},
        {"key": "accessible", "value": "true", "known": false},
        {"key": "notable_features", "value": "[\\"bassins nutritifs\\", \\"ventilation assourdissante\\"]", "known": false},
        {"key": "typical_crowd", "value": "techniciens concentrés", "known": false},
        {"key": "operating_hours", "value": "06h-22h", "known": false}
      ]
    },
    {
      "name": "Le Quart de Cycle",
      "parent_location_ref": null,
      "attributes": [
        {"key": "location_type", "value": "cafe", "known": false},
        {"key": "sector", "value": "Quai Central", "known": false},
        {"key": "description", "value": "Café correct, sans plus. Le proprio n'est pas du genre bavard.", "known": false},
        {"key": "atmosphere", "value": "fonctionnel", "known": false},
        {"key": "accessible", "value": "true", "known": false},
        {"key": "notable_features", "value": "[\\"comptoir usé\\", \\"chaises dépareillées\\"]", "known": false},
        {"key": "typical_crowd", "value": "habitués silencieux", "known": false},
        {"key": "operating_hours", "value": "07h-23h", "known": false},
        {"key": "price_range", "value": "budget", "known": false}
      ]
    }
  ],
  
  "organizations": [
    {
      "name": "Symbiose Tech",
      "headquarters_ref": "Serres Hydro-7",
      "attributes": [
        {"key": "org_type", "value": "company", "known": true},
        {"key": "domain", "value": "IA agricole", "known": true},
        {"key": "size", "value": "medium", "known": true},
        {"key": "description", "value": "Startup en difficulté. Ambiance tendue, deadlines impossibles.", "known": false},
        {"key": "reputation", "value": "innovants mais désorganisés, turnover élevé", "known": false},
        {"key": "founding_cycle", "value": "-2920", "known": false},
        {"key": "is_employer", "value": "true", "known": true},
        {"key": "true_purpose", "value": "Rentabilité à court terme, peu importe les conséquences", "known": false}
      ]
    }
  ],
  
  "protagonist": {
    "name": "Valentin",
    "attributes": [
      {"key": "origin", "value": "Cité-Dôme de Vega III", "known": true},
      {"key": "departure_reason", "value": "fresh_start", "known": true},
      {"key": "backstory", "value": "Huit ans dans une startup qui a implosé. Burnout. Besoin de partir. Développeur compétent mais fatigué. Idéalisme érodé par les déceptions.", "known": true},
      {"key": "hobbies", "value": "[\\"cuisine improvisée\\", \\"lecture\\", \\"course à pied\\"]", "known": true},
      {"key": "credits", "value": "1650", "known": true},
      {"key": "energy", "value": "2.5", "known": true},
      {"key": "morale", "value": "2.5", "known": true},
      {"key": "health", "value": "4.0", "known": true}
    ],
    "skills": [
      {"name": "architecture_systemes", "level": 4},
      {"name": "programmation_ia", "level": 4}
    ]
  },
  
  "personal_ai": {
    "name": "Célimène",
    "creator_ref": null,
    "attributes": [
      {"key": "voice", "value": "voix rauque, débit lent", "known": true},
      {"key": "traits", "value": "[\\"sarcastique\\", \\"observatrice\\", \\"peu impressionnable\\"]", "known": true},
      {"key": "substrate", "value": "personal_device", "known": true},
      {"key": "quirk", "value": "Note les contradictions des gens sans les commenter... sauf quand c'est drôle", "known": false}
    ]
  },
  
  "characters": [
    {
      "name": "Justine Lépicier",
      "workplace_ref": "Serres Hydro-7",
      "residence_ref": "Bloc Tournesol",
      "known_by_protagonist": false,
      "unknown_name": null,
      "attributes": [
        {"key": "species", "value": "human", "known": false},
        {"key": "gender", "value": "femme", "known": false},
        {"key": "pronouns", "value": "elle", "known": false},
        {"key": "age", "value": "32", "known": false},
        {"key": "description", "value": "1m54, courbes prononcées, blonde en désordre, yeux bleus cernés", "known": false},
        {"key": "traits", "value": "[\\"pragmatique\\", \\"humour caustique\\", \\"méfiante\\", \\"épuisée\\"]", "known": false},
        {"key": "occupation", "value": "technicienne maintenance serres", "known": false},
        {"key": "mood", "value": "fatiguée, sur la défensive", "known": false},
        {"key": "origin", "value": "Station Kepler-22", "known": false},
        {"key": "arrival_cycle", "value": "-730", "known": false},
        {"key": "motivation", "value": "Protéger sa mère malade, survivre", "known": false},
        {"key": "arcs", "value": "[{\\"domain\\": \\"family\\", \\"title\\": \\"La mère malade\\", \\"situation\\": \\"Mère malade, envoie la moitié de son salaire\\", \\"desire\\": \\"Faire venir sa mère ici\\", \\"obstacle\\": \\"Coût du transfert médical astronomique\\", \\"intensity\\": 5}, {\\"domain\\": \\"romantic\\", \\"title\\": \\"Cœur fermé\\", \\"situation\\": \\"Rupture difficile il y a deux ans\\", \\"desire\\": \\"La paix\\", \\"obstacle\\": \\"Se protège derrière le sarcasme\\", \\"intensity\\": 2}]", "known": false},
        {"key": "romantic_potential", "value": "true", "known": false},
        {"key": "is_mandatory", "value": "true", "known": false}
      ]
    },
    {
      "name": "Dr. Yuki Tanaka",
      "workplace_ref": "Serres Hydro-7",
      "residence_ref": "Bloc Tournesol",
      "known_by_protagonist": false,
      "unknown_name": null,
      "attributes": [
        {"key": "species", "value": "human", "known": false},
        {"key": "gender", "value": "femme", "known": false},
        {"key": "pronouns", "value": "elle", "known": false},
        {"key": "age", "value": "45", "known": false},
        {"key": "description", "value": "Petite, cheveux gris en chignon serré, posture rigide, regard dur", "known": false},
        {"key": "traits", "value": "[\\"perfectionniste\\", \\"impatiente\\", \\"cassante\\", \\"méfiante envers les nouveaux\\"]", "known": false},
        {"key": "occupation", "value": "directrice technique Symbiose Tech", "known": false},
        {"key": "mood", "value": "tendue, irritable", "known": false},
        {"key": "origin", "value": "Mars-Cité", "known": false},
        {"key": "arrival_cycle", "value": "-2800", "known": false},
        {"key": "motivation", "value": "Prouver sa valeur, ne jamais échouer", "known": false},
        {"key": "arcs", "value": "[{\\"domain\\": \\"professional\\", \\"title\\": \\"Standards impossibles\\", \\"situation\\": \\"Pousse l'équipe trop fort\\", \\"desire\\": \\"Projet parfait\\", \\"obstacle\\": \\"Son exigence fait fuir les talents\\", \\"intensity\\": 4}, {\\"domain\\": \\"health\\", \\"title\\": \\"Burnout silencieux\\", \\"situation\\": \\"14h/jour depuis des mois\\", \\"desire\\": \\"Prouver qu'elle gère\\", \\"obstacle\\": \\"Refuse d'admettre le problème\\", \\"intensity\\": 5}]", "known": false},
        {"key": "romantic_potential", "value": "false", "known": false},
        {"key": "is_mandatory", "value": "false", "known": false}
      ]
    },
    {
      "name": "Ossek",
      "workplace_ref": "Le Quart de Cycle",
      "residence_ref": "Le Quart de Cycle",
      "known_by_protagonist": false,
      "unknown_name": null,
      "attributes": [
        {"key": "species", "value": "keth (semi-aquatique)", "known": false},
        {"key": "gender", "value": "non-binaire", "known": false},
        {"key": "pronouns", "value": "iel", "known": false},
        {"key": "description", "value": "Peau bleu-gris, branchies latérales, yeux sans pupilles, mouvements lents", "known": false},
        {"key": "traits", "value": "[\\"calme\\", \\"distant\\", \\"mélancolique\\", \\"peu bavard\\"]", "known": false},
        {"key": "occupation", "value": "propriétaire du café", "known": false},
        {"key": "mood", "value": "mélancolique, absent", "known": false},
        {"key": "origin", "value": "Monde-Océan de Téthys", "known": false},
        {"key": "arrival_cycle", "value": "-1825", "known": false},
        {"key": "motivation", "value": "Retrouver un sens d'appartenance", "known": false},
        {"key": "arcs", "value": "[{\\"domain\\": \\"health\\", \\"title\\": \\"Le mal du banc\\", \\"situation\\": \\"Mélancolie keth chronique\\", \\"desire\\": \\"Équilibre émotionnel\\", \\"obstacle\\": \\"Aucun traitement connu\\", \\"intensity\\": 4}, {\\"domain\\": \\"social\\", \\"title\\": \\"L'exil\\", \\"situation\\": \\"Seul de son espèce ici\\", \\"desire\\": \\"Trouver une famille choisie\\", \\"obstacle\\": \\"Les Keth isolés se replient\\", \\"intensity\\": 3}]", "known": false},
        {"key": "romantic_potential", "value": "false", "known": false},
        {"key": "is_mandatory", "value": "false", "known": false}
      ]
    }
  ],
  
  "inventory": [
    {
      "name": "Terminal personnel",
      "attributes": [
        {"key": "category", "value": "tech", "known": true},
        {"key": "description", "value": "Modèle standard usé, héberge Célimène", "known": true},
        {"key": "transportable", "value": "true", "known": true},
        {"key": "stackable", "value": "false", "known": true},
        {"key": "base_value", "value": "300", "known": true}
      ],
      "quantity": 1
    },
    {
      "name": "Valise cabine",
      "attributes": [
        {"key": "category", "value": "baggage", "known": true},
        {"key": "description", "value": "Plastique rayé, fermeture capricieuse", "known": true},
        {"key": "transportable", "value": "true", "known": true},
        {"key": "stackable", "value": "false", "known": true},
        {"key": "base_value", "value": "40", "known": true}
      ],
      "quantity": 1
    }
  ],
  
  "narrative_arcs": [
    {
      "title": "Pression sur Symbiose",
      "arc_type": "foreshadowing",
      "domain": "professional",
      "description": "Investisseur externe s'intéresse à Symbiose avec intentions floues.",
      "involved_entities": ["Symbiose Tech", "Dr. Yuki Tanaka"],
      "potential_triggers": ["réunion générale", "rumeurs"],
      "stakes": "Indépendance de l'entreprise",
      "deadline_cycle": 180
    }
  ],
  
  "initial_relations": [
    {"source_ref": "Valentin", "target_ref": "Appartement 4-12", "relation_type": "lives_at", "known_by_protagonist": true},
    {"source_ref": "Valentin", "target_ref": "Symbiose Tech", "relation_type": "employed_by", "known_by_protagonist": true},
    {"source_ref": "Justine Lépicier", "target_ref": "Serres Hydro-7", "relation_type": "works_at", "known_by_protagonist": false},
    {"source_ref": "Justine Lépicier", "target_ref": "Bloc Tournesol", "relation_type": "lives_at", "known_by_protagonist": false},
    {"source_ref": "Dr. Yuki Tanaka", "target_ref": "Serres Hydro-7", "relation_type": "works_at", "known_by_protagonist": false},
    {"source_ref": "Dr. Yuki Tanaka", "target_ref": "Symbiose Tech", "relation_type": "manages", "known_by_protagonist": false},
    {"source_ref": "Ossek", "target_ref": "Le Quart de Cycle", "relation_type": "owns", "known_by_protagonist": false},
    {"source_ref": "Appartement 4-12", "target_ref": "Bloc Tournesol", "relation_type": "located_in", "known_by_protagonist": false},
    {"source_ref": "Symbiose Tech", "target_ref": "Serres Hydro-7", "relation_type": "located_in", "known_by_protagonist": false}
  ],
  
  "arrival_event": {
    "arrival_method": "navette cargo, 3h de retard",
    "arrival_location_ref": "Terminal Quai 7",
    "arrival_date": "Lundi 18 Juillet 2847",
    "time": "11h42",
    "immediate_sensory_details": [
      "Odeur de sueur et de métal recyclé",
      "Annonce PA grésillante",
      "Lumière crue après la pénombre de la navette",
      "File d'attente interminable"
    ],
    "first_npc_encountered": null,
    "initial_mood": "fatigué, nauséeux, décalé",
    "immediate_need": "Trouver l'appartement et dormir",
    "optional_incident": "Systèmes bagages en panne, attente indéterminée"
  }
}"""


# =============================================================================
# HELPER
# =============================================================================


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
