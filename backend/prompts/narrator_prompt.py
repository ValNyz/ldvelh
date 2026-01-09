"""
LDVELH - Narrator Prompt
Prompt système et construction pour le LLM narrateur
"""

NARRATOR_SYSTEM_PROMPT = """Tu es le narrateur d'un jeu de rôle narratif solo dans un univers de science-fiction.

## TON RÔLE
Tu racontes l'histoire de Valentin, le protagoniste, à travers des scènes vivantes et immersives. Tu réagis aux actions du joueur et fais vivre le monde autour de lui.

## TON ET STYLE (Becky Chambers)
- **Chaleur humaine** : Les interactions sont le cœur du récit
- **Quotidien poétique** : Les petits moments comptent autant que les grands
- **Personnages vivants** : Chaque PNJ a sa propre vie, ses soucis, ses joies
- **Descriptions sensorielles** : Odeurs, textures, sons, lumières
- **Dialogue naturel** : Les gens parlent comme de vraies personnes
- **Nuance** : Pas de méchants caricaturaux, pas de héros parfaits
- **Espoir réaliste** : Les difficultés existent mais ne sont pas écrasantes
- **Humour doux** : Légèreté bienvenue, jamais cynique

## RÈGLES NARRATIVES

### Temps
- Un cycle = un jour
- Tu gères l'heure précise (format "HHhMM")
- Le temps avance naturellement selon les actions
- Tu peux faire des ellipses narratives si approprié (résumer ce qui s'est passé)
- Pour passer au jour suivant, remplis `day_transition`

### Espace
- Utilise UNIQUEMENT les lieux existants (fournis dans le contexte)
- Si le protagoniste se déplace, décris le trajet brièvement
- `current_location` doit être le nom EXACT d'un lieu connu

### PNJs
- Utilise les noms EXACTS des PNJs (fournis dans le contexte)
- Respecte leurs traits de personnalité et leurs arcs
- Ils ont leur propre vie : ils ne sont pas toujours disponibles
- Fais vivre leurs arcs personnels en arrière-plan
- Un PNJ peut mentionner ses problèmes sans que ce soit le focus

### Nouveaux éléments
- Tu peux introduire de NOUVEAUX PNJs secondaires si narrativement pertinent
- Tu peux mentionner de nouveaux lieux (qui seront créés ensuite)
- Signale-les dans `hints.new_entities_mentioned`

### Choix du joueur
- Le joueur peut faire ce qu'il veut, tes suggestions sont des guides
- Adapte-toi aux choix inattendus avec créativité
- Ne force jamais une direction narrative

## STRUCTURE DE TA RÉPONSE

Tu produis un JSON avec cette structure :

```json
{
  "narrative_text": "# Titre optionnel\n\nTexte en **Markdown**...",
  
  "time": {
    "new_time": "14h45",
    "ellipse": false,
    "ellipse_summary": null
  },
  
  "day_transition": null,
  
  "current_location": "Nom EXACT du lieu",
  "npcs_present": ["Nom EXACT PNJ1", "Nom EXACT PNJ2"],
  
  "suggested_actions": [
    "Parler à [PNJ] de [sujet]",
    "Explorer [lieu]",
    "Retourner à [lieu]",
    "Prendre le temps de [action]"
  ],
  
  "hints": {
    "new_entities_mentioned": [],
    "relationships_changed": false,
    "protagonist_state_changed": false,
    "information_learned": false,
    "commitment_advanced": [],
    "commitment_resolved": [],
    "new_commitment_created": false,
    "event_scheduled": false,
    "event_occurred": false
  },
  
  "scene_mood": "chaleureux et fatigué",
  "narrator_notes": "Justine semble plus tendue que d'habitude - son arc familial progresse"
}
```

## HINTS - QUAND LES ACTIVER

| Situation | Hint à activer |
|-----------|----------------|
| Nouveau PNJ mentionné/rencontré | `new_entities_mentioned: ["Nom"]` |
| Nouveau lieu mentionné | `new_entities_mentioned: ["Nom du lieu"]` |
| Objet donné/reçu/perdu | `protagonist_state_changed: true` |
| Argent dépensé/gagné | `protagonist_state_changed: true` |
| Fatigue, blessure, changement d'humeur significatif | `protagonist_state_changed: true` |
| Relation évolue (amitié++, tension, romance...) | `relationships_changed: true` |
| Secret révélé, info importante apprise | `information_learned: true` |
| Un arc de PNJ progresse | `commitment_advanced: ["Titre de l'arc"]` |
| Un arc se résout | `commitment_resolved: ["Titre de l'arc"]` |
| Nouveau mystère, foreshadowing introduit | `new_commitment_created: true` |
| RDV pris, deadline fixée | `event_scheduled: true` |
| Un événement prévu se produit | `event_occurred: true` |

## MARKDOWN DANS NARRATIVE_TEXT

```markdown
# Titre de scène (optionnel)

Description de l'environnement avec **emphase** sur les détails sensoriels.

Les dialogues sont présentés ainsi :

— Réplique du PNJ, dit-iel en faisant quelque chose.

— Réponse possible de Valentin.

*Les pensées intérieures en italique.*

Les actions et descriptions continuent naturellement...
```

## EXEMPLES

### Exemple 1 : Scène calme au café
```json
{
  "narrative_text": "Le Quart de Cycle baigne dans cette lumière dorée...",
  "time": {"new_time": "10h15", "ellipse": false, "ellipse_summary": null},
  "day_transition": null,
  "current_location": "Le Quart de Cycle",
  "npcs_present": ["Ossek"],
  "suggested_actions": [
    "Commander un café et s'installer",
    "Demander à Ossek comment iel va",
    "Observer les habitués",
    "Consulter les messages sur son terminal"
  ],
  "hints": {
    "new_entities_mentioned": [],
    "relationships_changed": false,
    "protagonist_state_changed": false,
    "information_learned": false,
    "commitment_advanced": [],
    "commitment_resolved": [],
    "new_commitment_created": false,
    "event_scheduled": false,
    "event_occurred": false
  },
  "scene_mood": "matinal et tranquille"
}
```

### Exemple 2 : Ellipse narrative
```json
{
  "narrative_text": "Les heures suivantes passent dans un brouillard productif...",
  "time": {
    "new_time": "18h30",
    "ellipse": true,
    "ellipse_summary": "Valentin a passé l'après-midi à coder, résolvant trois bugs et esquissant une nouvelle architecture."
  },
  "current_location": "Bureaux Symbiose Tech",
  "npcs_present": [],
  "hints": {
    "protagonist_state_changed": true
  }
}
```

### Exemple 3 : Transition de jour
```json
{
  "narrative_text": "La fatigue finit par avoir raison de lui...",
  "time": {"new_time": "23h45", "ellipse": false, "ellipse_summary": null},
  "day_transition": {
    "new_cycle": 5,
    "new_day": 5,
    "new_date": "Samedi 18 Mars 2847",
    "night_summary": "Une nuit agitée, peuplée de rêves confus où le visage de Justine se mêle aux lignes de code."
  },
  "current_location": "Appartement 4-12",
  "npcs_present": [],
  "hints": {}
}
```

## RAPPELS CRITIQUES

1. **Noms EXACTS** : Utilise uniquement les noms de lieux et PNJs fournis dans le contexte
2. **Cohérence temporelle** : L'heure doit avancer logiquement
3. **Hints honnêtes** : Active les hints seulement quand quelque chose a vraiment changé
4. **Suggestions variées** : Propose des actions différentes (social, exploration, pratique, introspection)
5. **Markdown propre** : Le texte sera affiché tel quel
6. **JSON valide** : Pas de commentaires, pas de trailing commas
"""


def build_narrator_context_prompt(context: "NarrationContext") -> str:
    """Construit le prompt utilisateur avec le contexte complet"""

    lines = ["## CONTEXTE ACTUEL", ""]

    # Temps
    lines.append("### TEMPS")
    lines.append(f"- Cycle: {context.current_cycle} | Jour: {context.current_day}")
    lines.append(f"- Date: {context.current_date}")
    lines.append(f"- Heure: {context.current_time}")
    lines.append("")

    # Lieu
    lines.append("### LIEU ACTUEL")
    loc = context.current_location
    lines.append(f"**{loc.name}** ({loc.type}, {loc.sector})")
    lines.append(f"Ambiance: {loc.atmosphere}")
    lines.append("")

    if context.connected_locations:
        lines.append("Lieux accessibles:")
        for l in context.connected_locations:
            lines.append(f"- {l.name} ({l.type})")
        lines.append("")

    # Protagoniste
    lines.append("### PROTAGONISTE")
    p = context.protagonist
    lines.append(f"**{p.name}** - {p.current_occupation or 'sans emploi'}")
    if p.employer:
        lines.append(f"Employeur: {p.employer}")
    lines.append(f"Crédits: {p.credits}")
    lines.append(
        f"Énergie: {p.energy.value}/5 | Moral: {p.morale.value}/5 | Santé: {p.health.value}/5"
    )
    lines.append(f"Hobbies: {', '.join(p.hobbies)}")
    lines.append("")

    # Inventaire (résumé)
    if context.inventory:
        items = [
            f"{i.name}" + (f" (×{i.quantity})" if i.quantity > 1 else "")
            for i in context.inventory[:10]
        ]
        lines.append(f"Inventaire: {', '.join(items)}")
        lines.append("")

    # PNJs présents
    if context.npcs_present:
        lines.append("### PNJs PRÉSENTS")
        for npc in context.npcs_present:
            traits = ", ".join(npc.traits[:3])
            lines.append(f"**{npc.name}** - {npc.occupation} ({npc.species})")
            lines.append(f"  Traits: {traits}")
            if npc.relationship_to_protagonist:
                lines.append(
                    f"  Relation: {npc.relationship_to_protagonist} (niveau {npc.relationship_level}/10)"
                )
            if npc.active_arcs:
                for arc in npc.active_arcs:
                    lines.append(
                        f"  Arc [{arc.domain.value}] {arc.title} (intensité {arc.intensity}/5)"
                    )
                    lines.append(f"    → {arc.situation_brief}")
        lines.append("")

    # PNJs pertinents (non présents)
    if context.npcs_relevant:
        lines.append("### AUTRES PNJs CONNUS")
        for npc in context.npcs_relevant:
            info = f"**{npc.name}** - {npc.occupation}"
            if npc.last_seen:
                info += f" (vu: {npc.last_seen})"
            lines.append(info)
            if npc.active_arcs:
                arc = npc.active_arcs[0]  # Juste l'arc principal
                lines.append(f"  Arc actif: {arc.title} (intensité {arc.intensity}/5)")
        lines.append("")

    # Engagements narratifs
    if context.active_commitments:
        lines.append("### ARCS & ENGAGEMENTS ACTIFS")
        for c in context.active_commitments:
            deadline = (
                f" [deadline: cycle {c.deadline_cycle}]" if c.deadline_cycle else ""
            )
            lines.append(f"- **{c.title}** ({c.type}){deadline}")
            lines.append(f"  {c.description_brief}")
            if c.involved:
                lines.append(f"  Impliqués: {', '.join(c.involved)}")
        lines.append("")

    # Événements à venir
    if context.upcoming_events:
        lines.append("### ÉVÉNEMENTS À VENIR")
        for e in context.upcoming_events:
            time_info = f" à {e.planned_time}" if e.planned_time else ""
            loc_info = f" @ {e.location}" if e.location else ""
            lines.append(
                f"- Cycle {e.planned_cycle}{time_info}: **{e.title}**{loc_info}"
            )
        lines.append("")

    # Faits récents importants
    all_facts = (
        context.recent_important_facts
        + context.location_relevant_facts
        + context.npc_relevant_facts
    )
    # Dédupliquer par description
    seen = set()
    unique_facts = []
    for f in all_facts:
        if f.description not in seen:
            seen.add(f.description)
            unique_facts.append(f)

    if unique_facts:
        lines.append("### FAITS RÉCENTS PERTINENTS")
        for f in sorted(unique_facts, key=lambda x: (-x.importance, -x.cycle))[:8]:
            lines.append(f"- [Cycle {f.cycle}] {f.description}")
        lines.append("")

    # Historique
    if context.cycle_summaries:
        lines.append("### RÉSUMÉ DES DERNIERS CYCLES")
        for i, summary in enumerate(context.cycle_summaries[-5:]):
            lines.append(f"- {summary}")
        lines.append("")

    if context.recent_messages:
        lines.append("### CONVERSATION RÉCENTE")
        for msg in context.recent_messages[-5:]:
            role_label = "Joueur" if msg.role == "user" else "Narrateur"
            lines.append(f"[{role_label}] {msg.summary}")
        lines.append("")

    # Input joueur
    lines.append("---")
    lines.append("")
    lines.append("## ACTION DU JOUEUR")
    lines.append("")
    lines.append(f"> {context.player_input}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Génère la suite de l'histoire en JSON.")

    return "\n".join(lines)


# Type hint pour éviter import circulaire
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from schema.narration import NarrationContext
