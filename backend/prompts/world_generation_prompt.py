"""
LDVELH - World Generation Prompt
System prompt et builder pour la génération initiale du monde
"""

from prompts.shared import TONE_STYLE, COHERENCE_RULES
from prompts.examples import WORLD_GENERATION_EXAMPLE

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
                WORLD_GENERATION_EXAMPLE,
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
