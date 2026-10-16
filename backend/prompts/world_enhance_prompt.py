"""
LDVELH - World Enhance Prompts
POST /world/enhance: the player's short text in the wizard enriches the whole step.
- scope "world": the "Contexte libre" (lore) text fills the world step;
- scope "character": the character description fills the character step.
"""

import json

from services.engine.engine_data import (
    D6_ATTRIBUTES,
    D6_MAX_SKILL_DICE_AT_CREATION,
    D6_STARTING_ATTRIBUTE_DICE,
    D6_STARTING_SKILL_DICE,
    get_d6_skills,
    get_fate_skills,
)

_ROLE = """Tu es l'**assistant de création de partie** d'un jeu de rôle textuel solo.

Le joueur a écrit quelques mots dans le formulaire de création. Tu enrichis son texte et tu
remplis le reste de l'étape à partir de lui : choix précis, évocateurs, cohérents, en français.
Si son texte est vide, tu inventes l'étape entière à partir des autres choix du formulaire,
avec une idée originale (évite les clichés du genre).
"""

WORLD_SYSTEM_PROMPT = _ROLE + """
## ÉTAPE : MONDE

Le texte du joueur est le champ CONTEXTE LIBRE.

## RÈGLES

1. **Le texte du joueur fait foi.** Garde toutes ses idées, noms et détails ; ne les contredis pas.
2. **lore** : réécris-le en l'enrichissant (texte vide : invente une prémisse), 4 à 8 phrases d'ambiance et de contexte (époque,
   lieux, tensions, ton), sans raconter l'intrigue ni décider du personnage.
3. **genre** : UNIQUEMENT un slug de GENRES DISPONIBLES, le plus proche du texte ; texte vide :
   garde le genre actuel.
4. **difficulty** : "easy" | "moderate" | "hard" | "brutal" ; **duration** : "short" | "medium" |
   "long". Déduis-les du ton du texte ; s'il ne dit rien, garde les valeurs actuelles.
   **hardcore** : true seulement si le texte demande la mort permanente, sinon la valeur actuelle.
5. **Entités** : 1 à 3 PNJs, 1 à 3 lieux, 0 à 2 organisations ; reprends d'abord celles que le
   texte nomme, puis complète. Noms originaux, description d'une phrase (rôle, ambiance).
   Les entités du formulaire actuel sont conservées : ne les répète pas.

## FORMAT DE SORTIE

Réponds UNIQUEMENT avec un objet JSON :
```json
{
  "world_config": {"genre": "slug", "difficulty": "moderate", "duration": "medium",
                   "hardcore": false, "lore": "..."},
  "manual_entities": {
    "npcs": [{"name": "...", "description": "..."}],
    "locations": [{"name": "...", "description": "..."}],
    "organizations": [{"name": "...", "description": "..."}]
  }
}
```
"""

CHARACTER_SYSTEM_PROMPT = _ROLE + """
## ÉTAPE : PERSONNAGE

Le texte du joueur est la DESCRIPTION du personnage. Le MONDE est donné pour la cohérence.

## RÈGLES

1. **Le texte du joueur fait foi.** Garde toutes ses idées et détails ; ne les contredis pas.
2. **name** : garde le nom actuel s'il y en a un, sinon invente un nom adapté au monde.
3. **gender** : "male" | "female" | "non-binary" | "other" | "" ; déduis-le du texte, sinon
   garde la valeur actuelle.
4. **occupation** : quelques mots, cohérente avec le monde ; garde l'actuelle si le texte ne la
   contredit pas.
5. **description** : réécris le texte en l'enrichissant (texte vide : invente un personnage
   adapté au monde), 3 à 5 phrases (apparence, caractère,
   passé, ce qui le pousse à agir).
6. **engine** : uniquement la section du MOTEUR demandé, cohérente avec la description et le
   monde ; compétences prises UNIQUEMENT dans les listes autorisées. Les compétences actuelles
   indiquent les préférences du joueur : garde-les si la description ne s'y oppose pas.

## FORMAT DE SORTIE

Réponds UNIQUEMENT avec un objet JSON :
```json
{
  "character": {"name": "...", "gender": "", "occupation": "...", "description": "..."},
  "engine": {}
}
```
"""

EMPTY_TEXT = "(vide : invente à partir des autres choix)"

SYSTEM_PROMPTS = {"world": WORLD_SYSTEM_PROMPT, "character": CHARACTER_SYSTEM_PROMPT}

def engine_section(engine: str, genre: str | None) -> str:
    """What "engine" must contain for the selected engine (skill lists depend on the genre)."""
    if engine == "narrative":
        return ('Narratif : "engine" vaut {"traits": [{"name": "...", "description": "..."}]}, '
                "2 à 4 traits (un mot ou une courte expression, et une phrase qui l'illustre).")
    if engine == "fate_core":
        return "\n".join([
            'Fate Core : "engine" vaut {"aspects": {"high_concept": "...", "trouble": "...", '
            '"other": ["...", "...", "..."]}, "skills": {"Compétence": niveau}}.',
            "- aspects : un concept principal, un problème, trois autres aspects ; chaque aspect "
            "est une expression courte et imagée.",
            "- skills : la pyramide, exactement 10 compétences : 1 à 4, 2 à 3, 3 à 2, 4 à 1, "
            "les plus hautes étant celles qui définissent le personnage.",
            f"- Compétences autorisées (noms exacts) : {', '.join(get_fate_skills(genre))}",
        ])
    if engine == "d6":
        skills = get_d6_skills(genre)
        return "\n".join([
            'Système D6 : "engine" vaut {"attributes": {"Attribut": dés}, "skills": {"Compétence": dés}}.',
            f"- attributes : exactement {', '.join(D6_ATTRIBUTES)} ; chaque valeur est un entier "
            f"de 1 à 5 (nombre de dés), total exactement {D6_STARTING_ATTRIBUTE_DICE}.",
            f"- skills : dés AJOUTÉS à l'attribut, {D6_STARTING_SKILL_DICE} dés au total, au plus "
            f"{D6_MAX_SKILL_DICE_AT_CREATION} par compétence (valeurs : 1, 2, ou \"1D+1\", \"1D+2\"), "
            "4 à 6 compétences qui définissent le personnage.",
            "- Compétences autorisées par attribut (noms exacts) :",
            *[f"  - {attr} : {', '.join(names)}" for attr, names in skills.items()],
        ])
    return 'Mode libre : "engine" vaut {}.'


def build_user_message(scope: str, source_text: str, engine: str, genres: list[dict],
                       current: dict) -> str:
    """User message for one scope: the player's text, the constraints and the form as it stands."""
    world = current.get("world_config") or {}
    if scope == "world":
        return "\n".join([
            "## CONTEXTE LIBRE (texte du joueur)",
            source_text.strip() or EMPTY_TEXT,
            "",
            "## GENRES DISPONIBLES",
            *[f"- {g['slug']} : {g['label']}" for g in genres],
            "",
            "## FORMULAIRE ACTUEL",
            json.dumps({"world_config": world,
                        "manual_entities": current.get("manual_entities") or {}},
                       ensure_ascii=False, indent=2),
        ])
    genre_label = next((g["label"] for g in genres if g["slug"] == world.get("genre")),
                       world.get("genre") or "non précisé")
    character = {k: v for k, v in (current.get("character_data") or {}).items()
                 if k in ("name", "gender", "occupation", "skills")}
    return "\n".join([
        "## DESCRIPTION DU PERSONNAGE (texte du joueur)",
        source_text.strip() or EMPTY_TEXT,
        "",
        "## MONDE",
        f"Genre : {genre_label}",
        f"Contexte : {world.get('lore') or 'non précisé'}",
        "",
        "## MOTEUR",
        engine_section(engine, world.get("genre")),
        "",
        "## PERSONNAGE ACTUEL",
        json.dumps(character, ensure_ascii=False, indent=2),
    ])
