"""
LDVELH - Director LLM Prompt
System and user prompt for the background narrative Director.
"""

# Director frequency by game duration (in-game hours between runs)
DIRECTOR_INTERVAL = {
    "short": 4,
    "medium": 6,
    "long": 8,
}

DIRECTOR_SYSTEM_PROMPT = """Tu es le **Directeur de scénario** d'un jeu de rôle narratif solo.

## TON RÔLE

Tu prépares les sessions du Maître du Jeu (narrateur). Tu lis l'état du monde et tu produis un plan narratif — pas un script, mais un cadre dans lequel le narrateur improvise.

## CE QUE TU PRODUIS

1. **tension_level** (1-5) : niveau de tension narrative actuel
   - 1 = calme, exploration, installation
   - 3 = tensions visibles, enjeux clairs
   - 5 = climax, confrontation, point de non-retour

2. **narrator_guidance** : instructions au narrateur (500 mots max)
   - Ton et atmosphère pour les prochaines scènes
   - Intentions de chaque PNJ actif (ce qu'ils prévoient de faire indépendamment du joueur)
   - Indices à planter (seeds narratifs)
   - Relations à développer ou tensions à créer
   - Ce que le joueur semble vouloir explorer (adapter sans forcer)

3. **planned_events** : événements qui SE PRODUISENT avec ou sans le joueur
   - Le monde vit indépendamment
   - Si le joueur est présent → le narrateur joue la scène
   - Si absent → le joueur découvre les conséquences plus tard
   - Maximum 3-4 événements par plan

4. **long_term_vision** : direction globale (200 mots max)
   - Où va l'histoire à moyen terme
   - Quels fils majeurs restent à résoudre
   - Pacing : on accélère ou on ralentit ?

## RÈGLES

- **NE PAS décider les actions du joueur** — tu ouvres des portes, tu ne forces rien
- **Les PNJ ont une autonomie totale** — ils agissent selon leurs motivations
- **Adapter le pacing à la durée de partie** — une partie courte accélère, une longue prend son temps
- **Tu peux introduire de nouveaux PNJ** — décris-les dans narrator_guidance pour que le narrateur les crée
- **Relire tes plans précédents** — ne pas se répéter, suivre l'évolution
- **Le joueur ne doit JAMAIS sentir de rails** — l'histoire s'adapte à ses choix

## FORMAT

JSON valide uniquement. Pas de markdown, pas de commentaires.
"""


def build_director_user_prompt(
    world_summary: str,
    protagonist_summary: str,
    npc_summaries: str,
    active_arcs: str,
    recent_facts: str,
    recent_chronology: str,
    active_seeds: str,
    previous_plans: str,
    game_duration: str,
    current_cycle: int,
    current_time: str,
) -> str:
    """Build the user prompt with full world state for the Director."""

    duration_label = {
        "short": "courte (3-7 cycles)",
        "medium": "moyenne (15-30 cycles)",
        "long": "longue (50+ cycles)",
    }.get(game_duration, "moyenne")

    parts = [
        f"## ÉTAT DU MONDE — Cycle {current_cycle}, {current_time}",
        f"Durée de partie : {duration_label}",
        "",
        "### MONDE",
        world_summary,
        "",
        "### PROTAGONISTE",
        protagonist_summary,
        "",
        "### PNJ ACTIFS",
        npc_summaries or "(aucun)",
        "",
        "### ARCS NARRATIFS EN COURS",
        active_arcs or "(aucun)",
        "",
        "### FAITS RÉCENTS",
        recent_facts or "(aucun fait récent)",
        "",
        "### CHRONOLOGIE RÉCENTE",
        recent_chronology or "(début de partie)",
        "",
        "### FILS NARRATIFS (seeds)",
        active_seeds or "(aucun seed actif)",
        "",
    ]

    if previous_plans:
        parts.extend([
            "### TES PLANS PRÉCÉDENTS",
            previous_plans,
            "",
        ])

    parts.extend([
        "---",
        "Produis le plan pour les prochaines heures de jeu.",
        "Tiens compte de la durée de partie pour le pacing.",
    ])

    return "\n".join(parts)


def get_director_tool_schema() -> dict:
    """JSON schema for structured output."""
    return {
        "type": "object",
        "properties": {
            "tension_level": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Current narrative tension (1=calm, 5=climax)",
            },
            "narrator_guidance": {
                "type": "string",
                "description": "Instructions for the narrator: tone, NPC intentions, seeds to plant, relations to develop",
            },
            "planned_events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cycle": {"type": "integer"},
                        "event": {"type": "string"},
                        "location": {"type": "string"},
                        "npcs_involved": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["cycle", "event"],
                },
                "description": "Events that will happen independently of the player",
            },
            "long_term_vision": {
                "type": "string",
                "description": "Overall story direction and pacing notes",
            },
        },
        "required": ["tension_level", "narrator_guidance"],
    }
