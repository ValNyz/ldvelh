"""
LDVELH - Fate Core Engine
Full Fate Core implementation: 4dF dice, aspects, stunts, stress, consequences, fate points.
"""

import logging
import random
from collections.abc import Sequence
from uuid import UUID

from pydantic import ValidationError

from domain.errors import TurnError
from domain.turn import InvocationOffer
from schema.engine import EngineType, MechanicalDecision, RollResult
from schema.extraction import FateSkillUpgrade
from utils.log_safe import validation_summary
from .base import BaseEngine, normalize_name
from .fate_aspects import KIND_LABELS, aspect_pairs, insert_aspects, load_aspects, rename_aspect

logger = logging.getLogger(__name__)

# Fate Core ladder labels
FATE_LADDER = {
    -2: "Terrible",
    -1: "Mauvais",
    0: "Médiocre",
    1: "Moyen",
    2: "Correct",
    3: "Bon",
    4: "Excellent",
    5: "Superbe",
    6: "Fantastique",
    7: "Épique",
    8: "Légendaire",
}


def _valid_skill_upgrade(raw) -> FateSkillUpgrade | None:
    """The upgrade typed and bounded, or None (logged without its values) if invalid."""
    try:
        return FateSkillUpgrade.model_validate(raw)
    except ValidationError as e:
        logger.warning(f"[FATE] Skill upgrade skipped: {validation_summary(e)}")
        return None


def _ladder_label(value: int) -> str:
    """Get the Fate ladder label for a numeric value."""
    if value <= -2:
        return FATE_LADDER[-2]
    if value >= 8:
        return FATE_LADDER[8]
    return FATE_LADDER.get(value, f"+{value}" if value > 0 else str(value))


_LADDER_BY_LABEL = {label.lower(): value for value, label in FATE_LADDER.items()}


def _fate_value(value) -> int:
    """Read a Fate ladder value written as an int, "+3", "-1" or a ladder label ("Bon")."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    try:
        return int(text.replace("+", ""))
    except ValueError:
        return _LADDER_BY_LABEL.get(text.lower(), 0)


def outcome_for_shifts(shifts: int) -> str:
    """The one Fate outcome ladder, for fresh rolls and invoked ones alike."""
    if shifts < 0:
        return "failure"
    if shifts == 0:
        return "tie"
    if shifts >= 3:
        return "success_with_style"
    return "success"


def aspect_names(engine_stats: dict) -> list[str]:
    """Aspect names of a character sheet: plain strings or {"name"} / {"text"} dicts."""
    names = []
    for aspect in (engine_stats or {}).get("aspects") or []:
        if isinstance(aspect, dict):
            aspect = aspect.get("name") or aspect.get("text")
        if isinstance(aspect, str) and aspect:
            names.append(aspect)
    return names


def _known_invocations(invoked: Sequence[str], aspects: Sequence[str]) -> list[str]:
    """Invoked aspects as spelled on the sheet, without duplicates (order kept).

    An unknown one is refused.
    """
    known = {normalize_name(a): a for a in aspects}
    unique = []
    for name in invoked:
        canonical = known.get(normalize_name(name))
        if canonical is None:
            raise TurnError("invalid_invocation", f"Aspect inconnu : {name}.")
        if canonical not in unique:
            unique.append(canonical)
    return unique


async def _apply_aspect_renames(conn, game_id: UUID, renames) -> tuple[list[dict], list[dict]]:
    """Apply the extractor's aspect renames: (applied, failed) as {"old", "new"[, "reason"]}."""
    applied, failed = [], []
    for rename in renames or []:
        rename = rename if isinstance(rename, dict) else {}
        old = str(rename.get("old_name") or "").strip()
        new = str(rename.get("new_name") or "").strip()
        item = {"old": old, "new": new}
        if not old or not new:
            failed.append({**item, "reason": "blank_name"})
        elif await rename_aspect(conn, game_id, old, new):
            applied.append(item)
        else:
            failed.append({**item, "reason": "no_such_aspect"})
    for item in failed:
        logger.warning(f"[FATE] Aspect rename skipped ({item['reason']})")
    return applied, failed


TURN_STATE_KEYS = ("stress_physical", "stress_mental", "consequences", "fate_points")


class FateCoreEngine(BaseEngine):
    engine_type = EngineType.FATE_CORE

    # =========================================================================
    # DB operations
    # =========================================================================

    async def get_stats(self, conn, game_id: UUID) -> dict:
        """Load full Fate Core character state."""
        char = await conn.fetchrow(
            """
            SELECT stunts, stress_physical, stress_mental,
                   consequences, fate_points, refresh
            FROM character_fate
            WHERE game_id = $1
            """,
            game_id,
        )
        if not char:
            return {}

        skills = await conn.fetch(
            """
            SELECT name, level, custom
            FROM skills_fate
            WHERE game_id = $1
            ORDER BY level DESC, name
            """,
            game_id,
        )

        from schema.coerce import coerce_json_dict, coerce_json_list

        aspects = await load_aspects(conn, game_id)
        stunts = coerce_json_list(char["stunts"])
        consequences = coerce_json_dict(char["consequences"])

        return {
            "aspects": aspects,
            "stunts": stunts,
            "stress_physical": list(char["stress_physical"]),
            "stress_mental": list(char["stress_mental"]),
            "consequences": consequences,
            "fate_points": char["fate_points"],
            "refresh": char["refresh"],
            "skills": [
                {
                    "name": s["name"],
                    "level": s["level"],
                    "label": _ladder_label(s["level"]),
                    "custom": s["custom"],
                }
                for s in skills
            ],
        }

    def vitals_from_stats(self, stats: dict) -> dict:
        """Vitals for frontend: stress boxes, consequences, fate points."""
        if not stats:
            return {}
        return {
            "stress_physical": stats.get("stress_physical", []),
            "stress_mental": stats.get("stress_mental", []),
            "consequences": stats.get("consequences", {}),
            "fate_points": stats.get("fate_points", 0),
            "refresh": stats.get("refresh", 0),
        }

    def sheet_from_stats(self, stats: dict) -> dict:
        """Sheet for frontend: aspects with their stored kind, skill pyramid (highest
        first), stunts."""
        if not stats:
            return {}
        return {
            "aspects": stats.get("aspects", []),
            "skills": [
                {"name": s["name"], "level": s["level"], "label": s["label"]}
                for s in stats.get("skills", [])
            ],
            "stunts": stats.get("stunts", []),
        }

    async def create_character(self, conn, game_id: UUID, data: dict) -> None:
        """Create character_fate row, aspects (with their kind) and initial skills."""
        from schema.coerce import coerce_json_list

        stunts = coerce_json_list(data.get("stunts"))
        fate_points = data.get("fate_points", 3)
        refresh = data.get("refresh", 3)

        await conn.execute(
            """
            INSERT INTO character_fate
                (game_id, stunts, fate_points, refresh)
            VALUES ($1, $2, $3, $4)
            """,
            game_id,
            stunts,
            fate_points,
            refresh,
        )
        # Wizard sends {"high_concept": "...", "trouble": "...", "other": [...]}.
        await insert_aspects(conn, game_id, aspect_pairs(data.get("aspects", [])))

        # Insert skills — canonical format: {"Furtivité": 3, "Combat": 2}
        raw_skills = data.get("skills", {})

        skills_to_insert = []
        if isinstance(raw_skills, dict):
            for name, level in raw_skills.items():
                if name and isinstance(level, (int, float)):
                    skills_to_insert.append((name, int(level)))
        elif isinstance(raw_skills, list):
            # Fallback: list of {"name": ..., "level": ...} from world gen
            for skill in raw_skills:
                if isinstance(skill, dict):
                    skills_to_insert.append((skill.get("name", "?"), skill.get("level", 0)))

        for name, level in skills_to_insert:
            await conn.execute(
                """
                INSERT INTO skills_fate (game_id, name, level, custom)
                VALUES ($1, $2, $3, $4)
                """,
                game_id, name, level, False,
            )

    async def get_npc_stats(self, conn, character_id: UUID) -> dict:
        """Load Fate stats for an NPC."""
        row = await conn.fetchrow(
            """
            SELECT aspects, skills, stunts, stress_physical, stress_mental,
                   consequences, fate_points
            FROM npc_fate WHERE character_id = $1
            """,
            character_id,
        )
        if not row:
            return {}
        from schema.coerce import coerce_json_dict, coerce_json_list
        return {
            "aspects": coerce_json_list(row["aspects"]),
            "skills": coerce_json_dict(row["skills"]),
            "stunts": coerce_json_list(row["stunts"]),
            "stress_physical": list(row["stress_physical"]),
            "stress_mental": list(row["stress_mental"]),
            "consequences": coerce_json_dict(row["consequences"]),
            "fate_points": row["fate_points"],
        }

    async def create_npc_stats(self, conn, character_id: UUID, data: dict) -> None:
        """Create npc_fate row."""
        await conn.execute(
            """
            INSERT INTO npc_fate (character_id, aspects, skills, stunts, fate_points)
            VALUES ($1, $2, $3, $4, $5)
            """,
            character_id,
            data.get("aspects", []),
            data.get("skills", {}),
            data.get("stunts", []),
            data.get("fate_points", 1),
        )

    async def apply_roll_result(
        self, conn, game_id: UUID, roll: RollResult
    ) -> dict:
        """Apply stress/consequences from a failed roll."""
        changes = {}
        details = roll.details

        # Handle stress absorption from attacks
        stress_type = details.get("stress_type")  # "physical" or "mental"
        stress_amount = details.get("stress_amount", 0)

        if stress_type and stress_amount > 0:
            col = (
                "stress_physical" if stress_type == "physical" else "stress_mental"
            )
            row = await conn.fetchrow(
                f"SELECT {col} FROM character_fate WHERE game_id = $1",
                game_id,
            )
            if row:
                boxes = list(row[col])
                # Try to absorb stress in the box matching the shift value
                absorbed = False
                if stress_amount <= len(boxes) and not boxes[stress_amount - 1]:
                    boxes[stress_amount - 1] = True
                    absorbed = True
                else:
                    # Try higher boxes
                    for i in range(stress_amount, len(boxes)):
                        if not boxes[i]:
                            boxes[i] = True
                            absorbed = True
                            break

                if absorbed:
                    await conn.execute(
                        f"UPDATE character_fate SET {col} = $1, updated_at = now() WHERE game_id = $2",
                        boxes,
                        game_id,
                    )
                    changes["stress_absorbed"] = {
                        "type": stress_type,
                        "amount": stress_amount,
                    }
                else:
                    changes["overflow"] = True

        # Fate points spent on invocations: never below zero, or the whole turn fails.
        spent_fp = details.get("fate_points_spent", 0)
        if spent_fp > 0:
            remaining = await conn.fetchval(
                """
                UPDATE character_fate
                SET fate_points = fate_points - $1, updated_at = now()
                WHERE game_id = $2 AND fate_points >= $1
                RETURNING fate_points
                """,
                spent_fp,
                game_id,
            )
            if remaining is None:
                raise TurnError(
                    "invalid_invocation",
                    f"Pas assez de points de destin pour {spent_fp} invocations.",
                )
            changes["fate_points_spent"] = spent_fp

        return changes

    async def snapshot_turn_state(self, conn, game_id: UUID) -> dict:
        """Stress, consequences and fate points: what a roll or a compel writes. Aspects,
        stunts, skills and refresh are progression (extraction), not restored."""
        stats = await self.get_stats(conn, game_id)
        return {k: stats[k] for k in TURN_STATE_KEYS} if stats else {}

    async def restore_turn_state(self, conn, game_id: UUID, snapshot: dict) -> None:
        if not snapshot:
            return
        await conn.execute(
            """
            UPDATE character_fate SET
                stress_physical = $1, stress_mental = $2, consequences = $3,
                fate_points = $4, updated_at = now()
            WHERE game_id = $5
            """,
            snapshot["stress_physical"], snapshot["stress_mental"],
            snapshot["consequences"], snapshot["fate_points"], game_id,
        )

    # =========================================================================
    # Dice rolling
    # =========================================================================

    def needs_mechanical_step(self) -> bool:
        return True

    def resolve_roll_inputs(
        self, decision: MechanicalDecision, engine_stats: dict
    ) -> MechanicalDecision:
        """Use the sheet's skill level; an untrained skill is Mediocre (+0)."""
        skills = engine_stats.get("skills") if engine_stats else None
        if not skills or not decision.skill:
            return decision
        wanted = normalize_name(decision.skill)
        level = next(
            (s.get("level", 0) for s in skills
             if isinstance(s, dict) and normalize_name(s.get("name")) == wanted),
            0,
        )
        return decision.model_copy(update={"skill_value": level})

    def roll_dice(self, decision: MechanicalDecision) -> RollResult:
        """Roll 4 Fudge dice (each -1, 0, or +1) + skill value vs difficulty."""
        dice = [random.choice([-1, 0, 1]) for _ in range(4)]
        total = sum(dice)
        skill_value = _fate_value(decision.skill_value)
        skill_total = total + skill_value

        difficulty = decision.difficulty or 0
        opposition_total = None

        # If opposed roll, roll for opposition too
        if decision.opposition:
            opp_dice = [random.choice([-1, 0, 1]) for _ in range(4)]
            opp_skill = _fate_value(decision.opposition.get("skill_value", 0))
            opposition_total = sum(opp_dice) + opp_skill
            difficulty = opposition_total

        shifts = skill_total - difficulty
        outcome = outcome_for_shifts(shifts)

        details = {
            "skill_name": decision.skill,
            "skill_value": skill_value,
            "skill_label": _ladder_label(skill_value),
            "difficulty": difficulty,
            "difficulty_label": (
                decision.difficulty_label or _ladder_label(difficulty)
            ),
            "reason": decision.reason,
        }
        if decision.opposition:
            details["opposition"] = decision.opposition
            if opposition_total is not None:
                details["opposition_dice"] = opp_dice  # type: ignore[possibly-undefined]

        return RollResult(
            dice=dice,
            total=total,
            skill_total=skill_total,
            opposition_total=opposition_total,
            outcome=outcome,
            shifts=shifts,
            complication=False,
            details=details,
        )

    def available_invocations(self, engine_stats: dict | None) -> InvocationOffer:
        return InvocationOffer(aspects=aspect_names(engine_stats),
                               fate_points=(engine_stats or {}).get("fate_points", 0))

    def invocation_offer(self, roll: RollResult,
                         engine_stats: dict | None) -> InvocationOffer | None:
        """A failed roll waits for an invocation while fate points and aspects remain."""
        if roll.outcome != "failure":
            return None
        offer = self.available_invocations(engine_stats)
        return offer if offer.fate_points > 0 and offer.aspects else None

    def apply_invocation(self, roll: RollResult, invoked: Sequence[str],
                         aspects: Sequence[str], fate_points: int) -> RollResult:
        """+2 per invoked aspect on the ORIGINAL roll, outcome recomputed (pure)."""
        unique = _known_invocations(invoked, aspects)
        if not unique:
            return roll.model_copy(deep=True)
        if len(unique) > fate_points:
            raise TurnError(
                "invalid_invocation",
                f"Pas assez de points de destin ({fate_points}) pour {len(unique)} invocations.",
            )
        bonus = 2 * len(unique)
        skill_total = roll.skill_total + bonus
        shifts = skill_total - roll.details.get("difficulty", 0)
        details = {**roll.details, "invoked_aspects": unique, "invocation_bonus": bonus,
                   "fate_points_spent": len(unique)}
        return roll.model_copy(update={"skill_total": skill_total, "shifts": shifts,
                                       "outcome": outcome_for_shifts(shifts),
                                       "details": details})

    def build_narrator_addon(self, roll_result: RollResult | None) -> str:
        """Inject roll result into narrator prompt."""
        if not roll_result:
            return ""

        outcome_labels = {
            "failure": "ECHEC",
            "tie": "EGALITE",
            "success": "REUSSITE",
            "success_with_style": "REUSSITE AVEC STYLE",
        }
        label = outcome_labels.get(roll_result.outcome, roll_result.outcome.upper())
        details = roll_result.details

        lines = [
            "## Mechanical Roll Result (BINDING — do NOT contradict)",
            f"Skill: {details.get('skill_name', '?')} ({details.get('skill_label', '?')})",
            f"Dice: {roll_result.dice} → total {roll_result.total}",
            f"Skill total: {roll_result.skill_total} vs difficulty {details.get('difficulty', '?')} ({details.get('difficulty_label', '?')})",
            f"Shifts: {roll_result.shifts:+d}",
            f"**Outcome: {label}**",
            "",
            "Narrate the result. The mechanical outcome is FINAL.",
        ]

        if roll_result.outcome == "success_with_style":
            lines.append(
                "Success with style: the character achieves their goal with a bonus or flair."
            )
        elif roll_result.outcome == "tie":
            lines.append(
                "Tie: partial success or success at minor cost."
            )
        elif roll_result.outcome == "failure":
            lines.append(
                "Failure: the character does not achieve their goal. Describe consequences."
            )

        return "\n".join(lines)

    def get_gauge_policy(self) -> str:
        return "engine"

    def get_system_prompt_addon(self) -> str:
        return """
## MOTEUR MÉCANIQUE (Fate Core — RÉSULTAT DE DÉS)

Ce jeu utilise le système Fate Core avec des dés Fudge (4dF).

### RÈGLES ABSOLUES
1. Tu ne décides PAS du succès ou de l'échec — les dés l'ont déjà fait
2. Le résultat mécanique (succès/échec/égalité/critique) est CONTRAIGNANT
3. Ta narration DOIT respecter ce résultat — pas de contournement
4. Un échec mécanique = un échec narratif (décris-le de façon intéressante)
5. Un succès avec style = un résultat spectaculaire avec bonus
6. Une égalité = succès partiel ou succès à coût mineur

### COMMENT INTÉGRER LE RÉSULTAT
- Le résultat mécanique sera fourni dans "## RÉSULTAT MÉCANIQUE" du contexte
- Décris narrativement CE QUI SE PASSE en conséquence du résultat
- Sois créatif dans la description mais fidèle au résultat

### COMPELS — UTILISER LES ASPECTS CONTRE LE JOUEUR

Un compel est une complication narrative basée sur un **aspect du protagoniste**.
C'est une mécanique Fate Core centrale : le MJ propose une complication, le joueur choisit.

**Quand proposer un compel :**
- Quand un aspect du protagoniste crée naturellement un problème dans la situation
- 1 compel tous les 3-5 tours environ — pas à chaque tour
- Privilégier le "Trouble" (l'aspect marqué Problème) mais tous les aspects sont compelables

**Format OBLIGATOIRE dans narrative_text :**
Inclure un encadré markdown après la narration de la complication :

> **⚖️ Compel — [Nom exact de l'aspect]**
> [Description de la complication en 1-2 phrases]
> - **Accepter** : la complication se produit, tu gagnes 1 point de destin
> - **Refuser** : tu dépenses 1 point de destin pour éviter cette complication

**Quand le joueur a DÉJÀ répondu à un compel précédent :**
- "J'accepte" / "OK" / "oui" → la complication se produit, remplir `compel_result: "accepted"`
- "Je refuse" / "non" / "je dépense un FP" → la complication ne se produit pas, remplir `compel_result: "refused"`
- Si le joueur n'avait pas assez de FP pour refuser → le compel est automatiquement accepté

**Champ JSON :**
- `compel_aspect`: nom exact de l'aspect compelé (string ou null)
- `compel_result`: "proposed" (nouveau compel), "accepted" (joueur accepte), "refused" (joueur refuse), ou null (pas de compel)
"""

    def build_context_stats(self, engine_stats: dict) -> list[str]:
        lines = ["### STATS (Fate Core)"]
        # Aspects with their kind (get_stats: [{"type", "name"}]; wizard dict shape accepted)
        for kind, name in aspect_pairs(engine_stats.get("aspects")):
            lines.append(f"- {KIND_LABELS[kind]}: **{name}**")
        # Skills
        skills = engine_stats.get("skills", [])
        if skills:
            lines.append("Compétences:")
            for s in skills:
                if isinstance(s, dict):
                    label = s.get("label", "")
                    lines.append(
                        f"  - {s.get('name', '?')}: +{s.get('level', 0)}"
                        + (f" ({label})" if label else "")
                    )
        # Stress
        stress_p = engine_stats.get("stress_physical", [])
        stress_m = engine_stats.get("stress_mental", [])
        if stress_p or stress_m:
            p_display = "".join("☒" if b else "☐" for b in stress_p)
            m_display = "".join("☒" if b else "☐" for b in stress_m)
            lines.append(f"Stress physique: {p_display} | Mental: {m_display}")
        # Consequences
        cons = engine_stats.get("consequences", {})
        active_cons = {k: v for k, v in cons.items() if v}
        if active_cons:
            lines.append("Conséquences: " + ", ".join(f"{k}: {v}" for k, v in active_cons.items()))
        # Fate points
        fp = engine_stats.get("fate_points")
        if fp is not None:
            lines.append(f"Points de Destin: {fp}")
        lines.append("")
        return lines

    # =========================================================================
    # Progression
    # =========================================================================

    def get_progression_system_prompt(self) -> str:
        return (
            "Tu analyses la progression d'un personnage dans un jeu Fate Core.\n\n"
            "## MILESTONES FATE CORE\n"
            "- **Minor** (fin de session) : renommer 1 aspect OU échanger 2 compétences adjacentes\n"
            "- **Significant** (fin d'arc) : +1 niveau de compétence OU nouveau stunt\n"
            "- **Major** (événement majeur) : +1 refresh OU aspect supplémentaire + significant\n\n"
            "## RÈGLES\n"
            "- Ne propose un milestone que si le récit le justifie\n"
            "- Maximum 1 milestone par extraction\n"
            "- Les renommages d'aspects doivent refléter l'évolution du personnage\n"
            "- Les upgrades de compétences doivent être cohérents avec les actions récentes\n"
            "- Retourne un JSON vide si aucune progression n'est justifiée\n"
        )

    def build_progression_user_prompt(
        self, stats: dict, rolls: list[dict], narrative_summary: str
    ) -> str:
        lines = ["## État actuel du personnage"]

        # Aspects
        aspects = stats.get("aspects", [])
        if aspects:
            lines.append("### Aspects")
            for a in aspects:
                if isinstance(a, dict):
                    lines.append(f"- ({a.get('type', 'other')}) {a.get('name', '?')}")
                else:
                    lines.append(f"- {a}")

        # Skills
        skills = stats.get("skills", [])
        if skills:
            lines.append("### Compétences")
            for s in skills:
                if isinstance(s, dict):
                    label = s.get("label", "")
                    lines.append(
                        f"- {s.get('name', '?')}: +{s.get('level', 0)}"
                        + (f" ({label})" if label else "")
                    )

        # Stunts
        stunts = stats.get("stunts", [])
        if stunts:
            lines.append("### Stunts")
            for st in stunts:
                if isinstance(st, dict):
                    lines.append(f"- {st.get('name', '?')}: {st.get('description', '')}")

        # Fate points / refresh
        lines.append(f"\nPoints de Destin: {stats.get('fate_points', 0)} | Refresh: {stats.get('refresh', 3)}")

        # Recent rolls
        if rolls:
            lines.append("\n## Jets récents")
            for r in rolls[-5:]:
                outcome = r.get("outcome", "?")
                skill = r.get("skill_used", "?")
                lines.append(f"- {skill}: {outcome}")

        lines.append("\n## Résumé narratif récent")
        lines.append(narrative_summary or "(aucun)")
        lines.append("\nAnalyse si un milestone est mérité. Retourne un JSON vide si rien ne change.")
        return "\n".join(lines)

    def get_progression_tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "milestone_type": {
                    "type": "string",
                    "enum": ["minor", "significant", "major"],
                    "description": "Type of milestone reached, or omit if none",
                },
                "aspect_renames": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_name": {"type": "string"},
                            "new_name": {"type": "string"},
                        },
                        "required": ["old_name", "new_name"],
                    },
                    "description": "Aspects to rename (minor/major milestone)",
                },
                "new_stunts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["name", "description"],
                    },
                    "description": "New stunts gained (significant/major milestone)",
                },
                "skill_upgrades": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string"},
                            "new_level": {"type": "integer", "minimum": 1, "maximum": 8},
                        },
                        "required": ["skill_name", "new_level"],
                    },
                    "description": "Skills to upgrade (significant/major milestone)",
                },
                "refresh_increase": {
                    "type": "boolean",
                    "description": "Whether refresh increases by 1 (major milestone only)",
                },
            },
        }

    async def apply_progression(
        self, conn, game_id: UUID, extraction: dict
    ) -> dict:
        changes = {}

        # Aspect renames (in place: kind and position kept); a blank name or an unknown
        # aspect is reported as failed, the rest of the progression still applies
        applied, failed = await _apply_aspect_renames(
            conn, game_id, extraction.get("aspect_renames", []))
        if applied:
            changes["aspect_renames"] = applied
        if failed:
            changes["aspect_renames_failed"] = failed

        # New stunts
        for stunt in extraction.get("new_stunts", []):
            row = await conn.fetchrow(
                "SELECT stunts FROM character_fate WHERE game_id = $1", game_id
            )
            if row:
                from schema.coerce import coerce_json_list
                stunts = coerce_json_list(row["stunts"])
                stunts.append({"name": stunt.get("name", ""), "description": stunt.get("description", "")})
                await conn.execute(
                    "UPDATE character_fate SET stunts = $1, updated_at = now() WHERE game_id = $2",
                    stunts,
                    game_id,
                )
        if extraction.get("new_stunts"):
            changes["new_stunts"] = [s.get("name") for s in extraction["new_stunts"]]

        # Skill upgrades (an invalid upgrade is skipped, the valid ones are applied)
        upgrades = []
        for raw in extraction.get("skill_upgrades", []):
            upgrade = _valid_skill_upgrade(raw)
            if upgrade is None:
                continue
            await conn.execute(
                """
                UPDATE skills_fate SET level = $1
                WHERE game_id = $2 AND name = $3
                """,
                upgrade.new_level,
                game_id,
                upgrade.skill_name,
            )
            upgrades.append({"skill": upgrade.skill_name, "level": upgrade.new_level})
        if upgrades:
            changes["skill_upgrades"] = upgrades

        # Refresh increase
        if extraction.get("refresh_increase"):
            await conn.execute(
                "UPDATE character_fate SET refresh = refresh + 1, updated_at = now() WHERE game_id = $1",
                game_id,
            )
            changes["refresh_increase"] = True

        if extraction.get("milestone_type"):
            changes["milestone_type"] = extraction["milestone_type"]

        return changes

    # =========================================================================
    # Inventory object extensions
    # =========================================================================

    def get_object_prompt_addon(self) -> str:
        return (
            'For mechanically relevant items, add `"engine_data": '
            '{"item_type": "aspect"|"extra", "stunts": [{"name": "...", "description": "..."}]}`. '
            "Use item_type 'aspect' for items that define a character aspect, "
            "'extra' for items that grant stunts."
        )

    async def create_object_extension(
        self, conn, object_id: UUID, engine_data: dict
    ) -> None:
        item_type = engine_data.get("item_type")
        stunts = engine_data.get("stunts", [])
        if item_type or stunts:
            await conn.execute(
                """
                INSERT INTO object_fate (object_id, item_type, stunts)
                VALUES ($1, $2, $3)
                ON CONFLICT (object_id) DO NOTHING
                """,
                object_id,
                item_type,
                stunts,
            )
