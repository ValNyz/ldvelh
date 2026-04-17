"""
LDVELH / InkRealm - World Generation Prompt
System prompt et builder pour la génération initiale du monde.
Genre-aware: tone, friction, vocabulary, and example come from the genres DB table.
"""

from prompts.shared import COHERENCE_RULES


# =============================================================================
# SYSTEM PROMPT (generic core + genre injection)
# =============================================================================

_WORLD_GEN_SYSTEM_CORE = """Tu es un créateur de mondes pour un jeu de rôle narratif solo.

{genre_tone}

{coherence_rules}

## FRICTION INITIALE (IMPORTANT)

Le monde doit présenter des obstacles dès le départ.

### PNJ pas tous accueillants
Sur 3-4 PNJ, assure-toi d'avoir :
- 1 PNJ potentiellement neutre (occupé par ses propres problèmes)
- 1 PNJ avec une friction (stressé, méfiant, impatient, ou incompatible)
- 1-2 PNJ plus accessibles (mais pas chaleureux non plus)

{genre_friction}

### Situation de départ inconfortable
- Logement médiocre ou problématique
- Au moins un irritant quotidien
- Le protagoniste n'est attendu par personne

### Arcs PNJ indépendants
- Les arcs NE DOIVENT PAS avoir le protagoniste comme solution évidente
- Chaque PNJ doit pouvoir résoudre (ou échouer) son arc SANS le protagoniste
- Le protagoniste peut s'impliquer, mais ce n'est pas attendu ni nécessaire

## RÈGLES DE GÉNÉRATION

### Échelle temporelle (CRITIQUE)
- Un cycle = un jour
- Cycle 1 = moment présent (arrivée du protagoniste)
- Cycles négatifs = passé

**ÉCHELLE** :
- -365 = il y a 1 an
- -1825 = il y a 5 ans
- -3650 = il y a 10 ans

### Cohérence temporelle (OBLIGATOIRE)
- `founding_cycle` : entre -7000 et -2000 (5-20 ans d'existence)
- `station_arrival_cycle` PNJ : TOUJOURS >= founding_cycle
- Vétérans : -4000 à -2000
- Établis : -1500 à -500
- Récents : -365 à -30

### Noms
- Lieux : évocateurs mais pas ridicules
- Personnages : variés culturellement
- Compagnon : original, PAS dans cette liste : {forbidden_ai_names}
- **`unknown_name`** (PNJ pas encore connus) : description PHYSIQUE simple et concrète.
  Exemples corrects : "La femme aux cernes", "Le vieux gardien", "Le type en blouse blanche"
  Exemples INTERDITS : "Celle qui compte les pages", "La Nouvelle", "Le Gardien des Secrets"
  C'est ce que le protagoniste VOIT, pas un titre poétique ou un rôle narratif.

### ARCS PAR PERSONNAGE
Chaque PNJ peut avoir 1-3 arcs couvrant différents domaines :
professional, personal, romantic, social, family, financial, health, existential

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
1. Protagoniste → logement (lives_at)
2. Si employé : Protagoniste → employeur (employed_by)
3. Lieu enfant → lieu parent (located_in)
4. Organisation → siège (located_in)
5. PNJ → lieu travail (works_at)
6. PNJ → domicile (lives_at)

### COHÉRENCE DES RÉFÉRENCES (CRITIQUE)

**RÈGLE ABSOLUE** : Tu ne peux référencer QUE des entités que tu as créées.

Avant d'écrire un `*_ref`, vérifie qu'il existe :
- `residence_ref` → nom exact dans `locations`
- `workplace_ref` → nom exact dans `locations`
- `parent_location_ref` → nom exact dans `locations`
- `headquarters_ref` → nom exact dans `locations`
- `arrival_location_ref` → nom exact dans `locations`

**MÉTHODE** : Génère d'abord TOUS les lieux, puis assigne les références.

## FORMAT DE SORTIE
JSON valide uniquement. Pas de markdown, pas de commentaires.

**LIMITES** :
- Minimum 2 Arcs narratifs globaux
- Maximum 6 personnages
- Maximum 5 lieux
- Maximum 4 organisations
- Descriptions max 300 caractères
"""


def build_world_generation_system_prompt(genre: dict | None = None) -> str:
    """Build world gen system prompt with genre-specific content."""
    if genre:
        tone = f"## TON ET STYLE\n{genre.get('tone_style', '')}"
        friction = genre.get('friction_flavor', '')
        forbidden = ", ".join(genre.get('forbidden_ai_names', []) or [])
    else:
        tone = "## TON ET STYLE\nMonde indifférent, quotidien banal."
        friction = ""
        forbidden = "Aria, Nova, Luna, Cortana, Alexa, Siri"

    return _WORLD_GEN_SYSTEM_CORE.format(
        genre_tone=tone,
        coherence_rules=COHERENCE_RULES,
        genre_friction=friction,
        forbidden_ai_names=forbidden,
    )


# =============================================================================
# USER PROMPT BUILDER
# =============================================================================


def _build_engine_section(engine: str, world_config: dict | None = None) -> list[str]:
    """Build engine-specific prompt section for world generation."""
    if engine == "none" or not engine:
        return []

    parts = ["## MOTEUR DE JEU", ""]
    genre = world_config.get("genre", "sci-fi") if world_config else "sci-fi"
    difficulty = world_config.get("difficulty", "moderate") if world_config else "moderate"

    if engine == "narrative":
        parts.extend([
            "Moteur : **Narratif** (résistance basée sur les traits)",
            f"Genre : {genre} | Difficulté : {difficulty}",
            "",
            "Le protagoniste aura des **traits narratifs** qui influencent les épreuves.",
            "Les PNJ n'ont pas besoin de stats mécaniques.",
            "",
        ])

    elif engine == "fate_core":
        from services.engine.engine_data import get_fate_skills

        skills = get_fate_skills(genre)
        parts.extend([
            "Moteur : **Fate Core** (dés Fudge, aspects, compétences, points de destin)",
            f"Genre : {genre} | Difficulté : {difficulty}",
            "",
            f"Compétences disponibles : {', '.join(skills)}",
            "",
            "### PNJ — Stats Fate (IMPORTANT)",
            "Chaque PNJ doit avoir dans son champ `details` :",
            '- `"fate_skills"`: dict de 2-4 compétences clés avec niveaux (0-6)',
            '- `"fate_aspects"`: liste de 1-2 aspects narratifs',
            "",
        ])

    elif engine == "d6":
        from services.engine.engine_data import get_d6_skills, D6_ATTRIBUTES

        parts.extend([
            "Moteur : **D6 System** (pools de D6, dé sauvage, attributs/compétences)",
            f"Genre : {genre} | Difficulté : {difficulty}",
            "",
            f"Attributs : {', '.join(D6_ATTRIBUTES)}",
            "",
            "### PNJ — Stats D6 (IMPORTANT)",
            "Chaque PNJ doit avoir dans son champ `details` :",
            '- `"d6_attributes"`: dict d\'attributs principaux en code dé',
            '- `"d6_skills"`: dict de 2-4 compétences clés en code dé',
            "",
        ])

    if world_config:
        if world_config.get("lore"):
            parts.extend(["### Contexte supplémentaire", world_config["lore"], ""])
        if world_config.get("custom_rules"):
            parts.extend(["### Règles personnalisées", world_config["custom_rules"], ""])
        if world_config.get("hardcore"):
            parts.extend([
                "### Mode Hardcore",
                "Ce monde est BRUTAL. Les ressources sont rares, les PNJ hostiles,",
                "et les conséquences des erreurs sont graves.",
                "",
            ])

    return parts


def _build_manual_entities_section(manual_entities: dict) -> list[str]:
    """Build section for user-defined entities."""
    parts = ["## ENTITÉS IMPOSÉES PAR LE JOUEUR", ""]

    if "npcs" in manual_entities:
        parts.append("### PNJ imposés")
        for npc in manual_entities["npcs"]:
            parts.append(f"- **{npc.get('name', '???')}**: {npc.get('description', '')}")
        parts.append("")

    if "locations" in manual_entities:
        parts.append("### Lieux imposés")
        for loc in manual_entities["locations"]:
            parts.append(f"- **{loc.get('name', '???')}**: {loc.get('description', '')}")
        parts.append("")

    if "organizations" in manual_entities:
        parts.append("### Organisations imposées")
        for org in manual_entities["organizations"]:
            parts.append(f"- **{org.get('name', '???')}**: {org.get('description', '')}")
        parts.append("")

    parts.append("Intègre ces entités naturellement dans le monde généré.")
    parts.append("")
    return parts


def build_world_generation_user_prompt(
    protagonist_name: str = "Valentin",
    mandatory_npcs: list[dict] | None = None,
    theme_preferences: str | None = None,
    employer_preference: str = "employed",
    include_example: bool = True,
    engine: str | None = None,
    world_config: dict | None = None,
    character_data: dict | None = None,
    manual_entities: dict | None = None,
    genre: dict | None = None,
) -> str:
    """Build the user prompt for world generation."""

    parts = [
        "Génère un monde complet.",
        "",
    ]

    # Genre-specific example from DB
    if include_example and genre and genre.get("world_gen_example"):
        parts.extend([
            "## EXEMPLE DE FORMAT ATTENDU",
            "Voici un exemple du JSON attendu. Suis cette structure exactement :",
            "",
            genre["world_gen_example"],
            "",
            "---",
            "",
        ])

    # Engine-specific section
    if engine and engine != "none":
        parts.extend(_build_engine_section(engine, world_config))

    # Manual entities (user-defined NPCs, locations, orgs)
    if manual_entities:
        parts.extend(_build_manual_entities_section(manual_entities))

    parts.append("## PERSONNAGE PRINCIPAL")
    parts.append(f"Nom : {protagonist_name}")
    if character_data:
        if character_data.get("gender"):
            parts.append(f"Genre : {character_data['gender']}")
        if character_data.get("occupation"):
            parts.append(f"Occupation : {character_data['occupation']}")
        if character_data.get("description"):
            parts.append(f"Description : {character_data['description']}")
    parts.append("")

    # Employment preference
    if employer_preference == "unemployed":
        parts.extend([
            "## EMPLOI",
            f"{protagonist_name} arrive SANS emploi. Il devra en chercher un.",
            "Ne génère PAS d'organisation avec is_employer=true.",
            "",
        ])
    elif employer_preference == "freelance":
        parts.extend([
            "## EMPLOI",
            f"{protagonist_name} est freelance/indépendant.",
            "Génère des clients potentiels plutôt qu'un employeur unique.",
            "",
        ])
    else:
        parts.extend([
            "## EMPLOI",
            f"{protagonist_name} a un emploi.",
            "Génère une organisation employeur avec is_employer=true.",
            "",
        ])

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
            parts.append("- is_mandatory: true")
            parts.append("")

    # Theme preferences
    if theme_preferences:
        parts.extend([
            "## PRÉFÉRENCES THÉMATIQUES",
            theme_preferences,
            "",
        ])

    # Final checklist
    parts.extend([
        "## CHECKLIST FINALE",
        "",
        "### Entités",
        "□ 3-4 personnages",
        "□ 4-5 lieux (dont un logement)",
        "□ 1-3 organisations",
        "□ Chaque PNJ a 1-3 arcs variés",
        "",
        "### RÉFÉRENCES (CRITIQUE)",
        "□ Chaque *_ref = nom EXACT d'un lieu dans 'locations'",
        "⚠️ NE JAMAIS inventer un nom dans un *_ref",
        "",
        "### Friction",
        "□ Au moins 1 PNJ pas immédiatement sympathique",
        "□ Au moins 1 irritant dans la situation de départ",
        "□ Les arcs PNJ ne positionnent PAS le protagoniste comme solution",
        "",
        "Génère maintenant le JSON complet.",
    ])

    return "\n".join(parts)


# =============================================================================
# HELPER — called from routes.py
# =============================================================================


def get_full_generation_prompt(
    protagonist_name: str = "Valentin",
    mandatory_npcs: list[dict] | None = None,
    theme_preferences: str | None = None,
    employer_preference: str = "employed",
    engine: str | None = None,
    world_config: dict | None = None,
    character_data: dict | None = None,
    manual_entities: dict | None = None,
    genre: dict | None = None,
) -> dict:
    """Returns the complete prompt structure for the LLM API call."""

    return {
        "system": build_world_generation_system_prompt(genre),
        "user": build_world_generation_user_prompt(
            protagonist_name=protagonist_name,
            mandatory_npcs=mandatory_npcs,
            theme_preferences=theme_preferences,
            employer_preference=employer_preference,
            engine=engine,
            world_config=world_config,
            character_data=character_data,
            manual_entities=manual_entities,
            genre=genre,
        ),
    }
