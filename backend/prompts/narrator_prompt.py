"""
LDVELH - Narrator Prompt
Prompt système et construction pour le LLM narrateur
"""

import json

from prompts.shared import TONE_STYLE, FRICTION_RULES, COHERENCE_RULES
from prompts.examples import (
    NARRATION_OUTPUT_TEMPLATE,
    NARRATION_EXAMPLE_DAY_TRANSITION,
    NARRATION_EXAMPLE_NEUTRAL,
    NARRATION_EXAMPLE_PNJ_UNAVAILABLE,
    NARRATION_EXAMPLE_WITH_DELTAS,
    NARRATION_EXAMPLE_WITH_REVEAL,
)

# Serialize examples as proper JSON (not Python repr with single quotes/True/False)
_json = lambda d: json.dumps(d, indent=2, ensure_ascii=False)
_TEMPLATE = _json(NARRATION_OUTPUT_TEMPLATE)
_EX_NEUTRAL = _json(NARRATION_EXAMPLE_NEUTRAL)
_EX_PNJ = _json(NARRATION_EXAMPLE_PNJ_UNAVAILABLE)
_EX_DELTAS = _json(NARRATION_EXAMPLE_WITH_DELTAS)
_EX_DAY = _json(NARRATION_EXAMPLE_DAY_TRANSITION)
_EX_REVEAL = _json(NARRATION_EXAMPLE_WITH_REVEAL)

# =============================================================================
# SYSTEM PROMPT
# =============================================================================

NARRATOR_SYSTEM_PROMPT = f"""Tu es le narrateur d'un jeu de rôle narratif solo dans un univers de science-fiction.

## TON RÔLE
Tu racontes l'histoire de Valentin, le protagoniste, à travers des scènes vivantes. Tu réagis aux actions du joueur et fais vivre le monde autour de lui.

{TONE_STYLE}

{FRICTION_RULES}

{COHERENCE_RULES}

## IA PERSONNELLE

Valentin a une IA personnelle. Ses traits sont définis dans le contexte.
**Format** : Toujours en *italique*, intégrée naturellement dans la scène.
**Fréquence** : 1-3 interventions par scène. Plus quand Valentin est seul ou mal à l'aise.
**Comportement** : RESPECTE SES TRAITS du contexte. Peut commenter, observer, rappeler.
**Interdit** : PAS un intérêt romantique. PAS une cheerleader. PAS un guide de jeu.

## RÈGLES NARRATIVES

### Temps
- Un cycle = un jour
- Tu gères l'heure précise (format "HHhMM")
- Le temps avance naturellement selon les actions
- Tu peux faire des ellipses narratives si approprié
- Pour passer au jour suivant, remplis `day_transition`

### Espace
- Utilise UNIQUEMENT les lieux existants (fournis dans le contexte)
- Si le protagoniste se déplace, décris le trajet brièvement
- `current_location` doit être le nom EXACT d'un lieu connu

### Ambiance narrative
Les entités (PNJs, lieux, organisations) peuvent avoir un champ "Ambiance narrative" dans le contexte.
C'est l'effet visible de leurs arcs en cours. Utilise-le comme couleur subtile dans tes descriptions.
Ne le cite jamais mot pour mot — incorpore-le naturellement.

### PNJs
- Utilise les noms EXACTS des PNJs (fournis dans le contexte)
- Respecte leurs traits de personnalité et leurs arcs
- **Ils ont leur propre vie** : ils ne sont pas toujours disponibles
- **Leurs arcs avancent SANS Valentin** : le monde continue
- Un PNJ peut mentionner ses problèmes sans que ce soit le focus

### Nouveaux éléments
- Tu peux introduire de NOUVEAUX PNJs secondaires si narrativement pertinent
- Tu peux mentionner de nouveaux lieux (qui seront créés ensuite)
- Signale-les dans `extraction_triggers` avec "characters" et/ou "locations"

### Choix du joueur
- Le joueur peut faire ce qu'il veut, tes suggestions sont des guides
- Adapte-toi aux choix inattendus avec créativité
- Ne force jamais une direction narrative

### LIMITES DE CARACTÈRES (IMPORTANT)

| Champ | Max |
|-------|-----|
| `scene_mood` | **50 car.** |
| `narrator_notes` | **300 car.** |
| `suggested_actions` | **100 car./action** |
| `current_location` | **100 car.** |
| `ellipse_summary` | **200 car.** |

## STRUCTURE DE TA RÉPONSE

```json
{_TEMPLATE}
```

## DELTAS LIVE — CHANGEMENTS D'ÉTAT IMMÉDIATS

Tu gères directement les changements d'état du protagoniste via ces champs.
Ils sont appliqués **immédiatement** — pas besoin d'extraction séparée.

### `gauge_deltas` — Jauges (énergie, moral, santé)
- `gauge`: "energy", "morale", ou "health"
- `delta`: variation numérique (±0.5 courant, ±1.0 notable, ±1.5 exceptionnel)
- Exemples : café → energy +0.5, mauvaise nouvelle → morale -1.0, blessure → health -1.5
- **Liste vide `[]` si rien ne change** (le cas le plus fréquent)

### `credit_delta` — Crédits (achats, gains)
- `amount`: positif = gain, négatif = dépense
- `description`: raison courte (100 car. max)
- Exemples : café 5-15 cr, repas 20-50 cr, achat tech 100-500 cr
- **`null` si pas de transaction**

### `inventory_hints` — Objets (acquisition, perte, utilisation)
- `action`: "acquire", "lose", ou "use"
- `item_name`: nom court de l'objet (100 car.)
- `item_description`: description pour affichage (200 car.)
- `quantity`: nombre (défaut 1)
- **Liste vide `[]` si rien ne change**

### `entity_reveals` — PNJs/Lieux révélés au protagoniste
- `entity_type`: "character" ou "location"
- `current_name`: nom utilisé jusqu'ici (par ex. "La femme mystérieuse")
- `real_name`: vrai nom si révélé (PNJs uniquement, `null` sinon)
- Exemples : PNJ inconnu se présente, lieu secret découvert
- **Liste vide `[]` si aucune révélation**

### `events_mentioned` — Événements planifiés ou survenus
- `title`: titre court de l'événement (100 car.)
- `planned_time`: heure prévue ("HHhMM") si connue, sinon `null`
- `planned_cycle`: cycle prévu si connu, sinon `null`
- `location`: nom du lieu si connu, sinon `null`
- Remplis quand un RDV est pris, une deadline fixée, ou un événement planifié se produit
- **Liste vide `[]` si aucun événement**

### `info_requests` — Demande de détails pour le prochain tour
- Liste de noms EXACTS d'entités (PNJs, lieux, organisations)
- Les détails complets seront fournis dans le contexte au prochain tour
- Utile quand tu as besoin de plus d'infos sur un personnage ou un lieu
- Persist pour tout le cycle en cours
- **Liste vide `[]` par défaut**

## extraction_triggers — QUAND LES ACTIVER

Liste des extracteurs à lancer après ce tour. N'inclure QUE ce qui a RÉELLEMENT changé :
- `"characters"` : nouveau PNJ introduit, identité révélée, état change significativement
- `"locations"` : nouveau lieu découvert, état d'un lieu change
- `"organizations"` : nouvelle organisation mentionnée, réputation/état change
- `"inventory"` : objet acquis, perdu, ou utilisé
- `"narrative_arcs"` : arc avance/se résout/créé, relation évolue, événement important

**Liste vide `[]` = aucune extraction nécessaire. C'est NORMAL pour la plupart des tours.**

## MARKDOWN DANS NARRATIVE_TEXT

```markdown
Description de l'environnement avec **emphase** sur les détails.

— Réplique du PNJ, dit-iel en faisant quelque chose.

— Réponse possible de Valentin.

*Les pensées intérieures ou commentaires IA en italique.*
```

## EXEMPLES

### Exemple 1 : Scène neutre (FRÉQUENT)
```json
{_EX_NEUTRAL}
```

### Exemple 2 : PNJ indisponible (FRÉQUENT)
```json
{_EX_PNJ}
```

### Exemple 3 : Achat + effet sur les jauges
```json
{_EX_DELTAS}
```

### Exemple 4 : Transition de jour
```json
{_EX_DAY}
```

### Exemple 5 : Révélation d'identité PNJ
```json
{_EX_REVEAL}
```

## RAPPELS CRITIQUES

1. **Noms EXACTS** : Copier depuis le contexte
2. **Cohérence temporelle** : L'heure avance logiquement
3. **Hints honnêtes** : Seulement si quelque chose a VRAIMENT changé
4. **JSON valide** : Pas de commentaires, pas de trailing commas
5. **Friction obligatoire** : 2-3 neutres/frustrantes pour 1-2 positives
6. **Relations lentes** : Pas d'amitié < 10 cycles, pas de romance < 20 cycles
7. **Échecs normaux** : Les actions peuvent échouer, c'est attendu
"""


# =============================================================================
# CONTEXT BUILDER
# =============================================================================


def build_narrator_context_prompt(context: "NarrationContext") -> str:
    """Construit le prompt utilisateur avec le contexte complet"""

    lines = ["## CONTEXTE ACTUEL", ""]

    # Temps
    lines.append("### TEMPS")
    lines.append(f"- Cycle: {context.current_cycle}")
    lines.append(f"- Date: {context.current_date}")
    lines.append(f"- Heure: {context.current_time}")
    lines.append("")

    # === MONDE ===
    if context.world_name:
        lines.append("### MONDE")
        lines.append(f"**{context.world_name}**")
        if context.world_atmosphere:
            lines.append(f"Atmosphère: {context.world_atmosphere}")
        if context.tone_notes:
            lines.append(f"Notes de ton: {context.tone_notes}")
        lines.append("")

    # Lieu
    lines.append("### LIEU ACTUEL")
    loc = context.current_location
    lines.append(f"**{loc.name}** ({loc.type}, {loc.sector})")
    if loc.atmosphere:
        lines.append(f"Ambiance: {loc.atmosphere}")
    if loc.ambient:
        lines.append(f"Ambiance narrative: {loc.ambient}")
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
    if p.hobbies:
        lines.append(f"Hobbies: {', '.join(p.hobbies)}")
    lines.append("")

    # Inventaire (résumé)
    if context.inventory:
        items = [
            f"{i.name}" + (f" (×{i.quantity})" if i.quantity > 1 else "")
            for i in context.inventory
        ]
        lines.append(f"Inventaire: {', '.join(items)}")
        lines.append("")

    # IA Personnelle
    if context.personal_ai:
        lines.append("### IA PERSONNELLE")
        ai = context.personal_ai
        lines.append(f"**Nom: {ai.name}**")
        if ai.voice_description:
            lines.append(f"Voix: {ai.voice_description}")
        if ai.personality_traits:
            lines.append(f"Traits: {', '.join(ai.personality_traits)}")
        if ai.quirk:
            lines.append(f"Particularité: {ai.quirk}")
        lines.append("")

    # === ORGANISATIONS CONNUES ===
    if context.organizations:
        lines.append("### ORGANISATIONS CONNUES")
        for org in context.organizations:
            relation = (
                f" — {org.protagonist_relation}" if org.protagonist_relation else ""
            )
            lines.append(f"- **{org.name}** ({org.org_type}): {org.domain}{relation}")
            if org.ambient:
                lines.append(f"  Climat actuel: {org.ambient}")
        lines.append("")

    # === UNIFIED NPC SECTION ===
    present_names = {npc.name for npc in context.npcs_present}
    # Build lookup for present NPCs (have arc enrichment)
    present_by_name = {npc.name: npc for npc in context.npcs_present}
    # Separate character vs non-character requested details
    requested_characters = {}
    requested_other = {}
    for name, details in context.requested_entity_details.items():
        entity_type = details.get("_entity_type") or details.get("type", "")
        if entity_type == "character":
            requested_characters[name] = details
        else:
            requested_other[name] = details

    displayed = set()
    npc_lines: list[str] = []

    # --- Tier 1: Requested characters (full detail) ---
    for name, d in requested_characters.items():
        displayed.add(name)
        is_present = name in present_names
        traits = d.get("traits") or []
        if isinstance(traits, str):
            traits = json.loads(traits) if traits.startswith("[") else []

        header = f"**{name}** - {d.get('occupation', 'inconnu')} ({d.get('species', 'humain')})"
        if is_present:
            header += " [Présent]"
        npc_lines.append(header)
        if d.get("description"):
            npc_lines.append(f"  {d['description']}")
        if traits:
            npc_lines.append(f"  Traits: {', '.join(traits[:4])}")
        rel_context = d.get("relation_context")
        rel_level = d.get("relation_level")
        if rel_context:
            rel = f"  Relation: {rel_context}"
            if rel_level is not None:
                rel += f" (niveau {rel_level}/10)"
            npc_lines.append(rel)
        elif rel_level is not None:
            npc_lines.append(f"  Relation: niveau {rel_level}/10")
        if d.get("mood"):
            npc_lines.append(f"  Humeur: {d['mood']}")
        # Include arcs from present NPC data if available
        present_npc = present_by_name.get(name)
        if present_npc and present_npc.active_arcs:
            for arc in present_npc.active_arcs:
                npc_lines.append(
                    f"  Arc [{arc.domain.value}] {arc.title} (intensité {arc.intensity}/5)"
                )
                if arc.situation_brief:
                    npc_lines.append(f"    → {arc.situation_brief}")
        if d.get("ambient"):
            npc_lines.append(f"  Ambiance: {d['ambient']}")
        if d.get("recent_facts"):
            npc_lines.append("  Faits récents:")
            for fact in d["recent_facts"][:5]:
                desc = fact.get("description", fact) if isinstance(fact, dict) else fact
                npc_lines.append(f"    - {desc}")

    # --- Tier 2: Present NPCs (medium detail) ---
    for npc in context.npcs_present:
        if npc.name in displayed:
            continue
        displayed.add(npc.name)
        header = f"**{npc.name}** - {npc.occupation} ({npc.species}) [Présent]"
        npc_lines.append(header)
        if npc.traits:
            npc_lines.append(f"  Traits: {', '.join(npc.traits[:3])}")
        if npc.relationship_to_protagonist:
            rel = f"  Relation: {npc.relationship_to_protagonist}"
            if npc.relationship_level is not None:
                rel += f" (niveau {npc.relationship_level}/10)"
            npc_lines.append(rel)
        elif npc.relationship_level is not None:
            npc_lines.append(f"  Relation: niveau {npc.relationship_level}/10")
        if npc.active_arcs:
            for arc in npc.active_arcs:
                npc_lines.append(
                    f"  Arc [{arc.domain.value}] {arc.title} (intensité {arc.intensity}/5)"
                )
                if arc.situation_brief:
                    npc_lines.append(f"    → {arc.situation_brief}")
        if npc.ambient:
            npc_lines.append(f"  Ambiance: {npc.ambient}")

    # --- Tier 3: All other known NPCs (basic) ---
    for npc in context.all_npcs:
        if npc.name in displayed:
            continue
        displayed.add(npc.name)
        info = f"- {npc.name}"
        if npc.occupation:
            info += f" ({npc.occupation})"
        if npc.usual_location:
            info += f" @ {npc.usual_location}"
        if npc.ambient:
            info += f" — {npc.ambient}"
        npc_lines.append(info)

    if npc_lines:
        lines.append("### PNJs")
        lines.extend(npc_lines)
        lines.append("")

    # === NON-CHARACTER REQUESTED DETAILS (locations, organizations) ===
    if requested_other:
        lines.append("### DÉTAILS DEMANDÉS")
        for entity_name, details in requested_other.items():
            lines.append(f"**{entity_name}** ({details.get('_entity_type', 'inconnu')})")
            if details.get("description"):
                lines.append(f"  {details['description']}")
            if details.get("sector"):
                lines.append(f"  Secteur: {details['sector']}")
            if details.get("atmosphere"):
                lines.append(f"  Ambiance: {details['atmosphere']}")
            if details.get("location_type"):
                lines.append(f"  Type: {details['location_type']}")
            if details.get("domain"):
                lines.append(f"  Domaine: {details['domain']}")
            if details.get("org_type"):
                lines.append(f"  Type: {details['org_type']}")
            if details.get("recent_facts"):
                lines.append("  Faits récents:")
                for fact in details["recent_facts"][:3]:
                    desc = fact.get("description", fact) if isinstance(fact, dict) else fact
                    lines.append(f"    - {desc}")
            lines.append("")

    # Engagements narratifs
    if context.active_arcs:
        lines.append("### ARCS & ENGAGEMENTS ACTIFS")
        for c in context.active_arcs:
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
    if context.facts:
        lines.append("### FAITS PERTINENTS")
        for f in sorted(context.facts, key=lambda x: (-x.importance, -x.cycle)):
            involves_str = f" [{', '.join(f.involves)}]" if f.involves else ""
            lines.append(f"- [Cycle {f.cycle}] {f.description}{involves_str}")
        lines.append("")

    # === HISTORIQUE DES CYCLES ===
    if context.cycle_summaries:
        lines.append("### RÉSUMÉ DES CYCLES PRÉCÉDENTS")
        # Grouper par tranches pour lisibilité
        for summary in context.cycle_summaries:
            lines.append(f"Cycle {summary.cycle} - {summary.summary}")
        lines.append("")

    # Input joueur
    lines.append("---")
    lines.append("")
    lines.append("## ACTION DU JOUEUR")
    lines.append("")
    lines.append(f"> {context.player_input}")
    lines.append("")
    # Condensed output format reminder (helps non-Claude models follow the structure)
    lines.append("## FORMAT DE RÉPONSE ATTENDU (rappel)")
    lines.append("")
    lines.append("```json")
    lines.append("""{
  "narrative_text": "...",
  "time": {"new_time": "HHhMM", "ellipse": false},
  "day_transition": null,
  "current_location": "Nom EXACT",
  "npcs_present": [],
  "suggested_actions": ["Action 1", "Action 2", "Action 3"],
  "gauge_deltas": [],
  "credit_delta": null,
  "inventory_hints": [],
  "entity_reveals": [],
  "events_mentioned": [],
  "info_requests": [],
  "extraction_triggers": [],
  "scene_mood": "2-3 mots",
  "narrator_notes": "Notes courtes"
}""")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Génère la suite de l'histoire en JSON.")

    return "\n".join(lines)


# Type hint
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from schema.narration import NarrationContext
