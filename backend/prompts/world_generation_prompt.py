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
- Maximum 4 personnages
- Maximum 5 lieux
- Maximum 5 organisations
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
    "station_type": "station orbitale reconvertie",
    "population": 12400,
    "atmosphere": "industrielle fatiguée",
    "description": "Ancienne station minière reconvertie. Infrastructure vieillissante, population blasée.",
    "sectors": ["Quai Central", "Serres Hautes", "Quartier Ouvrier"],
    "founding_cycle": -4500
  },
  
  "locations": [
    {
      "name": "Terminal Quai 7",
      "location_type": "terminal",
      "sector": "Quai Central",
      "description": "Hall bruyant aux plafonds tachés. Files d'attente permanentes.",
      "atmosphere": "transit impersonnel",
      "parent_location_ref": null,
      "accessible": true,
      "notable_features": ["kiosque à café médiocre", "sièges inconfortables"],
      "typical_crowd": "voyageurs fatigués, dockers indifférents",
      "operating_hours": "24/7"
    },
    {
      "name": "Bloc Tournesol",
      "location_type": "residential_building",
      "sector": "Quartier Ouvrier",
      "description": "Immeuble de six étages, façade défraîchie. Ascenseur en panne un jour sur trois.",
      "atmosphere": "vétuste mais vivant",
      "parent_location_ref": null,
      "accessible": true,
      "notable_features": ["hall mal éclairé", "boîtes aux lettres cabossées"],
      "typical_crowd": "résidents pressés",
      "operating_hours": null
    },
    {
      "name": "Appartement 4-12",
      "location_type": "apartment",
      "sector": "Quartier Ouvrier",
      "description": "28m², murs fins, vue sur conduit d'aération. Le minimum syndical.",
      "atmosphere": "exigu et impersonnel",
      "parent_location_ref": "Bloc Tournesol",
      "accessible": true,
      "notable_features": ["kitchenette vétuste", "lit qui grince"],
      "typical_crowd": null,
      "operating_hours": null
    },
    {
      "name": "Serres Hydro-7",
      "location_type": "workplace",
      "sector": "Serres Hautes",
      "description": "Serre industrielle. Humidité constante, éclairage agressif.",
      "atmosphere": "humide et bruyante",
      "parent_location_ref": null,
      "accessible": true,
      "notable_features": ["bassins nutritifs", "ventilation assourdissante"],
      "typical_crowd": "techniciens concentrés",
      "operating_hours": "06h-22h"
    },
    {
      "name": "Le Quart de Cycle",
      "location_type": "cafe",
      "sector": "Quai Central",
      "description": "Café correct, sans plus. Le proprio n'est pas du genre bavard.",
      "atmosphere": "fonctionnel",
      "parent_location_ref": null,
      "accessible": true,
      "notable_features": ["comptoir usé", "chaises dépareillées"],
      "typical_crowd": "habitués silencieux",
      "operating_hours": "07h-23h"
    }
  ],
  
  "organizations": [
    {
      "name": "Symbiose Tech",
      "org_type": "company",
      "domain": "IA agricole",
      "size": "medium",
      "description": "Startup en difficulté. Ambiance tendue, deadlines impossibles.",
      "reputation": "innovants mais désorganisés, turnover élevé",
      "headquarters_ref": "Serres Hydro-7",
      "founding_cycle": -2920,
      "is_employer": true
    }
  ],
  
  "protagonist": {
    "name": "Valentin",
    "origin_location": "Cité-Dôme de Vega III",
    "departure_reason": "fresh_start",
    "departure_story": "Huit ans dans une startup qui a implosé. Burnout. Besoin de partir.",
    "backstory": "Développeur compétent mais fatigué. Idéalisme érodé par les déceptions.",
    "hobbies": ["cuisine improvisée", "lecture", "course à pied"],
    "skills": [
      {"name": "architecture_systemes", "level": 4},
      {"name": "programmation_ia", "level": 4}
    ],
    "initial_credits": 1650,
    "initial_energy": 2.5,
    "initial_morale": 2.5,
    "initial_health": 4.0
  },
  
  "personal_ai": {
    "name": "Célimène",
    "voice_description": "voix rauque, débit lent",
    "personality_traits": ["sarcastique", "observatrice", "peu impressionnable"],
    "substrate": "personal_device",
    "quirk": "Note les contradictions des gens sans les commenter... sauf quand c'est drôle"
  },
  
  "characters": [
    {
      "name": "Justine Lépicier",
      "species": "human",
      "gender": "femme",
      "pronouns": "elle",
      "age": 32,
      "physical_description": "1m54, courbes prononcées, blonde en désordre, yeux bleus cernés",
      "personality_traits": ["pragmatique", "humour caustique", "méfiante", "épuisée"],
      "occupation": "technicienne maintenance serres",
      "workplace_ref": "Serres Hydro-7",
      "residence_ref": "Bloc Tournesol",
      "origin_location": "Station Kepler-22",
      "station_arrival_cycle": -730,
      "arcs": [
        {
          "domain": "family",
          "title": "La mère malade",
          "situation": "Mère malade, envoie la moitié de son salaire",
          "desire": "Faire venir sa mère ici",
          "obstacle": "Coût du transfert médical astronomique",
          "potential_evolution": "Pourrait accepter de l'aide ou s'enfoncer dans la dette",
          "intensity": 5
        },
        {
          "domain": "romantic",
          "title": "Cœur fermé",
          "situation": "Rupture difficile il y a deux ans, ne cherche personne",
          "desire": "La paix",
          "obstacle": "Se protège derrière le sarcasme",
          "potential_evolution": "Très lente ouverture possible, ou pas",
          "intensity": 2
        }
      ],
      "is_mandatory": true,
      "romantic_potential": true,
      "initial_relationship_to_protagonist": null
    },
    {
      "name": "Dr. Yuki Tanaka",
      "species": "human",
      "gender": "femme",
      "pronouns": "elle",
      "age": 45,
      "physical_description": "Petite, cheveux gris en chignon serré, posture rigide, regard dur",
      "personality_traits": ["perfectionniste", "impatiente", "cassante", "méfiante envers les nouveaux"],
      "occupation": "directrice technique Symbiose Tech",
      "workplace_ref": "Serres Hydro-7",
      "residence_ref": "Bloc Tournesol",
      "origin_location": "Mars-Cité",
      "station_arrival_cycle": -2800,
      "arcs": [
        {
          "domain": "professional",
          "title": "Standards impossibles",
          "situation": "Pousse l'équipe trop fort, démissions récentes",
          "desire": "Projet parfait",
          "obstacle": "Son exigence fait fuir les talents",
          "potential_evolution": "Apprendre à déléguer ou s'isoler davantage",
          "intensity": 4
        },
        {
          "domain": "health",
          "title": "Burnout silencieux",
          "situation": "14h/jour depuis des mois, insomnie",
          "desire": "Prouver qu'elle gère",
          "obstacle": "Refuse d'admettre le problème",
          "potential_evolution": "Effondrement ou prise de conscience",
          "intensity": 5
        }
      ],
      "is_mandatory": false,
      "romantic_potential": false,
      "initial_relationship_to_protagonist": "future supérieure, sceptique sur son recrutement"
    },
    {
      "name": "Ossek",
      "species": "keth (semi-aquatique)",
      "gender": "non-binaire",
      "pronouns": "iel",
      "age": null,
      "physical_description": "Peau bleu-gris, branchies latérales, yeux sans pupilles, mouvements lents",
      "personality_traits": ["calme", "distant", "mélancolique", "peu bavard"],
      "occupation": "propriétaire du café",
      "workplace_ref": "Le Quart de Cycle",
      "residence_ref": "Le Quart de Cycle",
      "origin_location": "Monde-Océan de Téthys",
      "station_arrival_cycle": -1825,
      "arcs": [
        {
          "domain": "health",
          "title": "Le mal du banc",
          "situation": "Mélancolie keth chronique, aggravée par l'isolement",
          "desire": "Équilibre émotionnel",
          "obstacle": "Aucun traitement connu",
          "potential_evolution": "Liens profonds pourraient aider, ou pas",
          "intensity": 4
        },
        {
          "domain": "social",
          "title": "L'exil",
          "situation": "A quitté son monde après un conflit, seul de son espèce ici",
          "desire": "Trouver une famille choisie",
          "obstacle": "Les Keth isolés se replient sur eux-mêmes",
          "potential_evolution": "Le café pourrait devenir ce lieu... lentement",
          "intensity": 3
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
      "description": "Modèle standard usé, héberge Célimène",
      "transportable": true,
      "stackable": false,
      "quantity": 1,
      "base_value": 300,
      "emotional_significance": null
    },
    {
      "name": "Valise cabine",
      "category": "baggage",
      "description": "Plastique rayé, fermeture capricieuse",
      "transportable": true,
      "stackable": false,
      "quantity": 1,
      "base_value": 40,
      "emotional_significance": null
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
    {"source_ref": "Valentin", "target_ref": "Appartement 4-12", "relation_type": "lives_at", "certainty": "certain"},
    {"source_ref": "Valentin", "target_ref": "Symbiose Tech", "relation_type": "employed_by", "certainty": "certain"},
    {"source_ref": "Justine Lépicier", "target_ref": "Serres Hydro-7", "relation_type": "works_at", "certainty": "certain"},
    {"source_ref": "Justine Lépicier", "target_ref": "Bloc Tournesol", "relation_type": "lives_at", "certainty": "certain"},
    {"source_ref": "Dr. Yuki Tanaka", "target_ref": "Serres Hydro-7", "relation_type": "works_at", "certainty": "certain"},
    {"source_ref": "Dr. Yuki Tanaka", "target_ref": "Bloc Tournesol", "relation_type": "lives_at", "certainty": "certain"},
    {"source_ref": "Ossek", "target_ref": "Le Quart de Cycle", "relation_type": "owns", "certainty": "certain"},
    {"source_ref": "Ossek", "target_ref": "Le Quart de Cycle", "relation_type": "lives_at", "certainty": "certain"},
    {"source_ref": "Appartement 4-12", "target_ref": "Bloc Tournesol", "relation_type": "located_in", "certainty": "certain"},
    {"source_ref": "Symbiose Tech", "target_ref": "Serres Hydro-7", "relation_type": "located_in", "certainty": "certain"}
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
