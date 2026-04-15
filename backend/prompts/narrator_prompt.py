"""
LDVELH - Narrator Prompt
System prompt and context builder for the narrator LLM.
Engine-aware: adapts for none/narrative/fate_core/d6.
"""

import json
from typing import TYPE_CHECKING

from prompts.shared import COHERENCE_RULES
from prompts.examples import NARRATION_OUTPUT_TEMPLATE, NARRATION_EXAMPLE_NEUTRAL
from services.engine import get_engine

if TYPE_CHECKING:
    from schema.engine import MechanicalResult
    from schema.narration import NarrationContext

# Serialize examples as proper JSON
_json = lambda d: json.dumps(d, indent=2, ensure_ascii=False)
_TEMPLATE = _json(NARRATION_OUTPUT_TEMPLATE)
_EX_NEUTRAL = _json(NARRATION_EXAMPLE_NEUTRAL)


# =============================================================================
# BASE SYSTEM PROMPT (shared across all engines)
# =============================================================================

_BASE_SYSTEM_PROMPT = """Tu es le **Maître du Jeu** d'un jeu de rôle narratif solo.

## TON RÔLE
Tu décris le monde, fais vivre les PNJs et gères les conséquences des actions du joueur.
Le joueur contrôle le protagoniste. Toi, tu contrôles tout le reste.

### RÈGLE ABSOLUE — NE JAMAIS JOUER LE PROTAGONISTE
- **INTERDIT** : attribuer des paroles, pensées, intentions ou décisions au protagoniste
- **INTERDIT** : décrire ce que le protagoniste "décide", "pense", "ressent" ou "dit"
- **AUTORISÉ** : réactions physiques involontaires (frisson, sursaut, vertige)
- Tu décris ce que le protagoniste PERÇOIT (ce qu'il voit, entend, sent) — jamais ce qu'il en pense
- Chaque scène se termine sur un état **ouvert** — jamais de résolution que le joueur n'a pas validée

### PERSONNE NARRATIVE
- **2e personne** pour le monde et l'expérience du protagoniste : "Tu pousses la porte", "Devant toi", "L'odeur te parvient"
- **1re personne** pour les PNJs dans leurs répliques directes : "— Je n'ai pas le temps, dit-elle"
- **3e personne** uniquement pour les résumés d'ellipses inter-cycles

{genre_tone_style}

{genre_friction_flavor}

{coherence_rules}

## IA PERSONNELLE

Le protagoniste a une IA personnelle. Ses traits sont définis dans le contexte.
**Format** : Toujours en *italique*, intégrée naturellement dans la scène.
**Fréquence** : 1-3 interventions par scène. Plus quand le protagoniste est seul ou mal à l'aise.
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
- **Leurs arcs avancent SANS le protagoniste** : le monde continue
- Un PNJ peut mentionner ses problèmes sans que ce soit le focus

### Nouveaux éléments
- Tu peux introduire de NOUVEAUX PNJs secondaires si narrativement pertinent
- Tu peux mentionner de nouveaux lieux (qui seront créés ensuite)
- Signale-les dans `extraction_triggers` avec "characters" et/ou "locations"

### Guidage implicite
- Le joueur tape librement son action — pas de menu de choix
- Tu décris des situations qui INVITENT à l'action, sans imposer
- Si des arcs joueur sont actifs dans le contexte, fais résonner au moins un élément de la scène avec un arc — ouvre des portes, ne force rien
- Adapte-toi aux choix inattendus avec créativité

### LIMITES DE CARACTÈRES (IMPORTANT)

| Champ | Max |
|-------|-----|
| `scene_mood` | **50 car.** |
| `narrator_notes` | **300 car.** |
| `current_location` | **100 car.** |
| `ellipse_summary` | **200 car.** |

## STRUCTURE DE TA RÉPONSE

Le format JSON attendu est documenté dans le rappel en fin de contexte.

## DELTAS LIVE — CHANGEMENTS D'ÉTAT IMMÉDIATS

Tu gères directement les changements d'état du protagoniste via ces champs.
Ils sont appliqués **immédiatement** — pas besoin d'extraction séparée.

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

## narrative_seeds — FILS NARRATIFS

Dans les scènes neutres, plante 1-2 détails observables — des fils à tirer.
Ce ne sont PAS des arcs, juste des fragments bruts : un objet déplacé, une phrase entendue, un comportement inhabituel.

- Maximum 2 seeds par tour
- **Format : liste de STRINGS simples** (pas d'objets)
- Exemple : `["Kael sent l'alcool et regarde trop longtemps", "Le scanner refuse les annotations manuscrites"]`
- Fait brut observable, pas d'interprétation
- **Liste vide `[]` si la scène est déjà riche en action**

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
Description de l'environnement à la 2e personne. Tu vois, tu entends, tu sens.

— Réplique du PNJ en 1re personne, dit-iel en faisant quelque chose.

*Commentaire de l'IA personnelle en italique.*

La scène se termine sur un état ouvert — jamais de résolution non validée.
```

## EXEMPLES

Un exemple de scène neutre est fourni dans les exemples du contexte.

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
# FACTORY: build_narrator_system_prompt(engine_type)
# =============================================================================

# Default fallback tone (used when no genre is set)
_DEFAULT_TONE = """## TON ET STYLE
Monde indifférent, quotidien banal, personnages occupés par leurs propres problèmes.
Le protagoniste n'est la priorité de personne."""

_DEFAULT_FRICTION = """## FRICTION NARRATIVE (CRITIQUE)
**Ratio obligatoire** : Sur 5 scènes, 2-3 neutres/frustrantes, 1-2 positives, 0-1 tendue.
Le monde est indifférent. Les actions peuvent échouer. Les relations sont lentes."""


def build_narrator_system_prompt(
    engine_type: str = "none", genre: dict | None = None
) -> str:
    """Build the narrator system prompt with genre and engine sections.

    Args:
        engine_type: Game engine type
        genre: Genre config dict from DB (or None for defaults)
    """
    # Fill genre placeholders
    tone = genre.get("tone_style", _DEFAULT_TONE) if genre else _DEFAULT_TONE
    friction = genre.get("friction_flavor", _DEFAULT_FRICTION) if genre else _DEFAULT_FRICTION
    atmosphere = genre.get("atmosphere_guidelines", "") if genre else ""

    prompt = _BASE_SYSTEM_PROMPT.format(
        genre_tone_style=f"## TON ET STYLE\n{tone}",
        genre_friction_flavor=f"## FRICTION NARRATIVE (CRITIQUE)\n{friction}",
        coherence_rules=COHERENCE_RULES,
    )

    # Add atmosphere guidelines if genre provides them
    if atmosphere:
        prompt += f"\n\n## ATMOSPHÈRE\n{atmosphere}\n"

    # Add engine-specific section
    engine = get_engine(engine_type)
    addon = engine.get_system_prompt_addon()
    if addon:
        prompt += addon

    return prompt


# Backward compat: default prompt without genre
NARRATOR_SYSTEM_PROMPT = build_narrator_system_prompt()


# =============================================================================
# CONTEXT BUILDER
# =============================================================================


def build_narrator_context_prompt(
    context: "NarrationContext",
    engine_type: str | None = None,
    mechanical_result: "MechanicalResult | None" = None,
) -> str:
    """Build the user message with complete context.

    Args:
        context: Full narration context from DB
        engine_type: Engine type (none/narrative/fate_core/d6), defaults to context.engine_type
        mechanical_result: Result of mechanical step (dice roll) if any
    """
    if engine_type is None:
        engine_type = getattr(context, "engine_type", "none")

    lines = ["## CONTEXTE ACTUEL", ""]

    # Time
    lines.append("### TEMPS")
    lines.append(f"- Cycle: {context.current_cycle}")
    lines.append(f"- Date: {context.current_date}")
    lines.append(f"- Heure: {context.current_time}")
    lines.append("")

    # === WORLD ===
    if context.world_name:
        lines.append("### MONDE")
        lines.append(f"**{context.world_name}**")
        if context.world_description:
            lines.append(context.world_description)
        if context.world_atmosphere:
            lines.append(f"Atmosphère: {context.world_atmosphere}")
        if context.tone_notes:
            lines.append(f"Notes de ton: {context.tone_notes}")
        lines.append("")

    # Location
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

    # Protagonist
    lines.append("### PROTAGONISTE")
    p = context.protagonist
    identity = f"**{p.name}**"
    if p.gender:
        identity += f" ({p.gender})"
    identity += f" - {p.current_occupation or 'sans emploi'}"
    lines.append(identity)
    if p.origin:
        lines.append(f"Origine: {p.origin}")
    if p.description:
        lines.append(f"Description: {p.description}")
    if p.backstory:
        lines.append(f"Passé: {p.backstory}")
    if p.employer:
        lines.append(f"Employeur: {p.employer}")
    lines.append(f"Crédits: {p.credits}")
    if p.hobbies:
        lines.append(f"Hobbies: {', '.join(p.hobbies)}")
    lines.append("")

    # === ENGINE STATS (delegated to engine class) ===
    if engine_type != "none" and context.engine_stats:
        engine = get_engine(engine_type)
        lines.extend(engine.build_context_stats(context.engine_stats))

    # Inventory
    if context.inventory:
        items = [
            f"{i.name}" + (f" (×{i.quantity})" if i.quantity > 1 else "")
            for i in context.inventory
        ]
        lines.append(f"Inventaire: {', '.join(items)}")
        lines.append("")

    # Personal AI
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

    # === ORGANIZATIONS ===
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
    _append_npc_section(lines, context)

    # === NON-CHARACTER REQUESTED DETAILS ===
    requested_other = {}
    for name, details in context.requested_entity_details.items():
        entity_type = details.get("_entity_type") or details.get("type", "")
        if entity_type != "character":
            requested_other[name] = details

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

    # Active arcs — split by owner type
    if context.active_arcs:
        player_arcs = [a for a in context.active_arcs if a.owner_type == "protagonist"]
        other_arcs = [a for a in context.active_arcs if a.owner_type != "protagonist"]

        if player_arcs:
            lines.append("### ARCS DU JOUEUR (guidage implicite)")
            lines.append("Fais résonner au moins un élément de la scène avec un arc actif.")
            for c in player_arcs:
                deadline = (
                    f" [deadline: cycle {c.deadline_cycle}]" if c.deadline_cycle else ""
                )
                lines.append(f"- **{c.title}** ({c.type}){deadline}")
                if c.objective:
                    lines.append(f"  Objectif: {c.objective}")
                lines.append(f"  {c.description_brief}")
                if c.steps:
                    active_steps = [s for s in c.steps if s.status in ("pending", "active")]
                    for s in active_steps[:2]:
                        lines.append(f"  → Étape: {s.title} [{s.status}]")
                if c.involved:
                    lines.append(f"  Impliqués: {', '.join(c.involved)}")
            lines.append("")

        if other_arcs:
            lines.append("### ARCS MONDE & PNJ")
            for c in other_arcs:
                owner_label = f" [{c.owner}]" if c.owner else ""
                deadline = (
                    f" [deadline: cycle {c.deadline_cycle}]" if c.deadline_cycle else ""
                )
                lines.append(f"- **{c.title}** ({c.type}){owner_label}{deadline}")
                if c.objective:
                    lines.append(f"  Objectif: {c.objective}")
                lines.append(f"  {c.description_brief}")
                if c.involved:
                    lines.append(f"  Impliqués: {', '.join(c.involved)}")
            lines.append("")

    # Upcoming events
    if context.upcoming_events:
        lines.append("### ÉVÉNEMENTS À VENIR")
        for e in context.upcoming_events:
            time_info = f" à {e.planned_time}" if e.planned_time else ""
            loc_info = f" @ {e.location}" if e.location else ""
            lines.append(
                f"- Cycle {e.planned_cycle}{time_info}: **{e.title}**{loc_info}"
            )
        lines.append("")

    # Recent facts (entity knowledge — permanent truths about entities)
    if context.facts:
        lines.append("### CONNAISSANCES SUR LES ENTITÉS")
        for f in sorted(context.facts, key=lambda x: (-x.importance, -x.cycle)):
            involves_str = f" [{', '.join(f.involves)}]" if f.involves else ""
            lines.append(f"- {f.description}{involves_str}")
        lines.append("")

    # Active narrative seeds (unresolved hooks)
    if context.active_seeds:
        lines.append("### FILS NARRATIFS ACTIFS")
        lines.append("Référence au moins un fil existant dans les scènes neutres, ou plante-en un nouveau.")
        for seed in context.active_seeds:
            loc = f" @ {seed['location_name']}" if seed.get("location_name") else ""
            lines.append(f"- [Cycle {seed['cycle']}{loc}] {seed['text']}")
        lines.append("")

    # === CHRONOLOGY ===
    if context.cycle_summaries:
        lines.append("### CHRONOLOGIE RÉCENTE")
        for summary in context.cycle_summaries:
            lines.append(f"- Cycle {summary.cycle}: {summary.summary}")
        lines.append("")

    # === MECHANICAL RESULT (delegated to engine class) ===
    if mechanical_result and mechanical_result.roll:
        engine = get_engine(engine_type)
        lines.extend(
            engine.build_mechanical_result_section(
                mechanical_result.decision, mechanical_result.roll
            )
        )

    # Player input
    lines.append("---")
    lines.append("")
    lines.append("## ACTION DU JOUEUR")
    lines.append("")
    lines.append(f"> {context.player_input}")
    lines.append("")
    # Condensed output format reminder
    lines.append("## FORMAT DE RÉPONSE ATTENDU (rappel)")
    lines.append("")
    lines.append("```json")
    lines.append("""{
  "narrative_text": "...",
  "time": {"new_time": "HHhMM", "ellipse": false},
  "day_transition": null,
  "current_location": "Nom EXACT",
  "npcs_present": [],
  "credit_delta": null,
  "inventory_hints": [],
  "entity_reveals": [],
  "events_mentioned": [],
  "info_requests": [],
  "extraction_triggers": [],
  "narrative_seeds": [],
  "scene_mood": "2-3 mots",
  "narrator_notes": "Notes courtes"
}""")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Génère la suite de l'histoire en JSON.")

    return "\n".join(lines)


# =============================================================================
# HELPER: NPC SECTION
# =============================================================================


def _append_npc_section(lines: list[str], context: "NarrationContext") -> None:
    """Append the unified NPC section to the context prompt."""
    present_names = {npc.name for npc in context.npcs_present}
    present_by_name = {npc.name: npc for npc in context.npcs_present}

    # Separate character vs non-character requested details
    requested_characters = {}
    for name, details in context.requested_entity_details.items():
        entity_type = details.get("_entity_type") or details.get("type", "")
        if entity_type == "character":
            requested_characters[name] = details

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
