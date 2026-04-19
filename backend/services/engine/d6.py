"""
LDVELH - D6 System Engine
Full D6 implementation: NdD6 + wild die, attributes, skills, wounds, force points.
"""

import json
import random
import re
from uuid import UUID

from schema.engine import EngineType, MechanicalDecision, RollResult
from .base import BaseEngine


def parse_dice_code(code: str) -> tuple[int, int]:
    """Parse a D6 dice code like '3D+2' into (num_dice, pip_bonus).

    Returns (num_dice, pip_bonus). E.g. '3D+2' -> (3, 2), '2D' -> (2, 0).
    """
    code = code.upper().strip()
    match = re.match(r"(\d+)D(?:\+(\d+))?", code)
    if not match:
        return (1, 0)
    num_dice = int(match.group(1))
    pips = int(match.group(2)) if match.group(2) else 0
    return (num_dice, pips)


def roll_d6_pool(num_dice: int, pip_bonus: int = 0) -> dict:
    """Roll NdD6 with wild die rules.

    The last die is the wild die:
    - If wild die = 6: explodes (reroll and add, keep exploding on 6)
    - If wild die = 1: complication (remove wild die AND highest regular die)

    Returns dict with all roll details.
    """
    if num_dice <= 0:
        return {
            "regular_dice": [],
            "wild_die_rolls": [0],
            "total": pip_bonus,
            "complication": False,
        }

    # Roll regular dice (all except wild die)
    regular_dice = [random.randint(1, 6) for _ in range(max(0, num_dice - 1))]

    # Roll wild die
    wild_die_rolls = []
    wild_value = random.randint(1, 6)
    wild_die_rolls.append(wild_value)

    complication = False

    if wild_value == 1:
        # Complication: wild die counts as 0, remove highest regular die
        complication = True
        wild_total = 0
        if regular_dice:
            regular_dice.remove(max(regular_dice))
    elif wild_value == 6:
        # Exploding: keep rolling while getting 6
        wild_total = wild_value
        while wild_value == 6:
            wild_value = random.randint(1, 6)
            wild_die_rolls.append(wild_value)
            wild_total += wild_value
    else:
        wild_total = wild_value

    total = sum(regular_dice) + wild_total + pip_bonus

    return {
        "regular_dice": regular_dice,
        "wild_die_rolls": wild_die_rolls,
        "wild_total": wild_total,
        "pip_bonus": pip_bonus,
        "total": total,
        "complication": complication,
    }


class D6Engine(BaseEngine):
    engine_type = EngineType.D6

    # =========================================================================
    # DB operations
    # =========================================================================

    async def get_stats(self, conn, game_id: UUID) -> dict:
        """Load full D6 character state."""
        char = await conn.fetchrow(
            """
            SELECT attributes, wounds, force_points
            FROM character_d6
            WHERE game_id = $1
            """,
            game_id,
        )
        if not char:
            return {}

        skills = await conn.fetch(
            """
            SELECT attribute, name, dice_value, custom
            FROM skills_d6
            WHERE game_id = $1
            ORDER BY attribute, name
            """,
            game_id,
        )

        attributes = char["attributes"] if isinstance(char["attributes"], dict) else json.loads(char["attributes"])
        wounds = char["wounds"] if isinstance(char["wounds"], dict) else json.loads(char["wounds"])

        return {
            "attributes": attributes,
            "wounds": wounds,
            "force_points": char["force_points"],
            "skills": [
                {
                    "attribute": s["attribute"],
                    "name": s["name"],
                    "dice_value": s["dice_value"],
                    "custom": s["custom"],
                }
                for s in skills
            ],
        }

    async def get_vitals_display(self, conn, game_id: UUID) -> dict:
        """Vitals for frontend: wounds + force points."""
        stats = await self.get_stats(conn, game_id)
        if not stats:
            return {}
        return {
            "wounds": stats.get("wounds", {}),
            "force_points": stats.get("force_points", 0),
        }

    async def create_character(self, conn, game_id: UUID, data: dict) -> None:
        """Create character_d6 row and initial skills."""
        attributes = data.get("attributes", {})
        force_points = data.get("force_points", 3)

        await conn.execute(
            """
            INSERT INTO character_d6 (game_id, attributes, force_points)
            VALUES ($1, $2, $3)
            """,
            game_id,
            attributes,
            force_points,
        )

        for skill in data.get("skills", []):
            await conn.execute(
                """
                INSERT INTO skills_d6 (game_id, attribute, name, dice_value, custom)
                VALUES ($1, $2, $3, $4, $5)
                """,
                game_id,
                skill["attribute"],
                skill["name"],
                skill["dice_value"],
                skill.get("custom", False),
            )

    async def get_npc_stats(self, conn, character_id: UUID) -> dict:
        """Load D6 stats for an NPC."""
        row = await conn.fetchrow(
            """
            SELECT attributes, skills, wounds, force_points
            FROM npc_d6 WHERE character_id = $1
            """,
            character_id,
        )
        if not row:
            return {}
        return {
            "attributes": row["attributes"] if isinstance(row["attributes"], dict) else json.loads(row["attributes"]),
            "skills": row["skills"] if isinstance(row["skills"], dict) else json.loads(row["skills"]),
            "wounds": row["wounds"] if isinstance(row["wounds"], dict) else json.loads(row["wounds"]),
            "force_points": row["force_points"],
        }

    async def create_npc_stats(self, conn, character_id: UUID, data: dict) -> None:
        """Create npc_d6 row."""
        await conn.execute(
            """
            INSERT INTO npc_d6 (character_id, attributes, skills, force_points)
            VALUES ($1, $2, $3, $4)
            """,
            character_id,
            data.get("attributes", {}),
            data.get("skills", {}),
            data.get("force_points", 0),
        )

    async def apply_roll_result(
        self, conn, game_id: UUID, roll: RollResult, cycle: int
    ) -> dict:
        """Apply wound changes from a failed roll."""
        changes = {}
        details = roll.details

        wound_level = details.get("wound_level")
        if wound_level:
            char = await conn.fetchrow(
                "SELECT wounds FROM character_d6 WHERE game_id = $1",
                game_id,
            )
            if char:
                wounds = char["wounds"] if isinstance(char["wounds"], dict) else json.loads(char["wounds"])
                wounds[wound_level] = True
                await conn.execute(
                    """
                    UPDATE character_d6 SET wounds = $1, updated_at = now()
                    WHERE game_id = $2
                    """,
                    wounds,
                    game_id,
                )
                changes["wound_applied"] = wound_level

        # Handle force point spending
        spent_fp = details.get("force_points_spent", 0)
        if spent_fp > 0:
            await conn.execute(
                """
                UPDATE character_d6
                SET force_points = GREATEST(0, force_points - $1), updated_at = now()
                WHERE game_id = $2
                """,
                spent_fp,
                game_id,
            )
            changes["force_points_spent"] = spent_fp

        return changes

    async def snapshot_state(self, conn, game_id: UUID) -> dict:
        """Full state snapshot for rollback."""
        return await self.get_stats(conn, game_id)

    async def restore_snapshot(self, conn, game_id: UUID, snapshot: dict) -> None:
        """Restore full D6 state from snapshot."""
        if not snapshot:
            return

        await conn.execute(
            """
            UPDATE character_d6 SET
                attributes = $1,
                wounds = $2,
                force_points = $3,
                updated_at = now()
            WHERE game_id = $4
            """,
            snapshot.get("attributes", {}),
            snapshot.get("wounds", {}),
            snapshot.get("force_points", 3),
            game_id,
        )

        # Restore skills
        await conn.execute("DELETE FROM skills_d6 WHERE game_id = $1", game_id)
        for skill in snapshot.get("skills", []):
            await conn.execute(
                """
                INSERT INTO skills_d6 (game_id, attribute, name, dice_value, custom)
                VALUES ($1, $2, $3, $4, $5)
                """,
                game_id,
                skill["attribute"],
                skill["name"],
                skill["dice_value"],
                skill.get("custom", False),
            )

    # =========================================================================
    # Dice rolling
    # =========================================================================

    def needs_mechanical_step(self) -> bool:
        return True

    def roll_dice(self, decision: MechanicalDecision) -> RollResult:
        """Roll D6 pool for the character's skill vs difficulty number."""
        skill_value_str = str(decision.skill_value or "1D")
        # skill_value might be an int (from mechanical LLM) or a dice code string
        # If it's a bare int, treat it as that many D6
        if isinstance(decision.skill_value, int):
            num_dice = decision.skill_value
            pip_bonus = 0
        else:
            num_dice, pip_bonus = parse_dice_code(skill_value_str)

        pool = roll_d6_pool(num_dice, pip_bonus)
        difficulty = decision.difficulty or 10  # default moderate difficulty

        total = pool["total"]

        # Opposition roll (if applicable)
        opposition_total = None
        opp_pool = None
        if decision.opposition:
            opp_code = decision.opposition.get("skill_value", "2D")
            opp_dice, opp_pips = parse_dice_code(str(opp_code))
            opp_pool = roll_d6_pool(opp_dice, opp_pips)
            opposition_total = opp_pool["total"]
            difficulty = opposition_total

        if total >= difficulty:
            outcome = "success"
        else:
            outcome = "failure"

        # All dice for display (regular + wild)
        all_dice = pool["regular_dice"] + pool["wild_die_rolls"]

        details = {
            "skill_name": decision.skill,
            "dice_code": skill_value_str if not isinstance(decision.skill_value, int) else f"{num_dice}D",
            "regular_dice": pool["regular_dice"],
            "wild_die_rolls": pool["wild_die_rolls"],
            "pip_bonus": pip_bonus,
            "difficulty": difficulty,
            "difficulty_label": decision.difficulty_label,
            "reason": decision.reason,
        }
        if decision.opposition:
            details["opposition"] = decision.opposition
            if opp_pool:
                details["opposition_pool"] = opp_pool

        return RollResult(
            dice=all_dice,
            total=total,
            skill_total=total,  # D6: total already includes skill
            opposition_total=opposition_total,
            outcome=outcome,
            shifts=total - difficulty,
            complication=pool["complication"],
            details=details,
        )

    def build_narrator_addon(self, roll_result: RollResult | None) -> str:
        """Inject roll result into narrator prompt."""
        if not roll_result:
            return ""

        details = roll_result.details
        label = "REUSSITE" if roll_result.outcome == "success" else "ECHEC"

        lines = [
            "## Mechanical Roll Result (BINDING — do NOT contradict)",
            f"Skill: {details.get('skill_name', '?')} ({details.get('dice_code', '?')})",
            f"Regular dice: {details.get('regular_dice', [])}",
            f"Wild die: {details.get('wild_die_rolls', [])}",
            f"Total: {roll_result.total} vs difficulty {details.get('difficulty', '?')}",
            f"Margin: {roll_result.shifts:+d}",
        ]

        if roll_result.complication:
            lines.append("**WILD DIE COMPLICATION** — something goes wrong regardless of success/failure.")

        lines.extend([
            f"**Outcome: {label}**",
            "",
            "Narrate the result. The mechanical outcome is FINAL.",
        ])

        if roll_result.complication:
            lines.append(
                "There is a complication: even on success, describe an unexpected side effect."
            )

        return "\n".join(lines)

    def get_gauge_policy(self) -> str:
        return "engine"

    def get_system_prompt_addon(self) -> str:
        return """
## MOTEUR MÉCANIQUE (D6 System — RÉSULTAT DE DÉS)

Ce jeu utilise le système D6 avec un dé sauvage (wild die).

### RÈGLES ABSOLUES
1. Tu ne décides PAS du succès ou de l'échec — les dés l'ont déjà fait
2. Le résultat mécanique (succès/échec) est CONTRAIGNANT
3. Ta narration DOIT respecter ce résultat — pas de contournement
4. Un échec mécanique = un échec narratif (décris-le de façon intéressante)
5. Les complications du dé sauvage ajoutent un twist même en cas de succès

### COMMENT INTÉGRER LE RÉSULTAT
- Le résultat mécanique sera fourni dans "## RÉSULTAT MÉCANIQUE" du contexte
- Décris narrativement CE QUI SE PASSE en conséquence du résultat
- Sois créatif dans la description mais fidèle au résultat
- Si complication : décris un problème annexe même si l'action réussit
"""

    def build_context_stats(self, engine_stats: dict) -> list[str]:
        lines = ["### STATS (D6 System)"]
        # Attributes
        attrs = engine_stats.get("attributes", {})
        if attrs:
            attr_strs = [f"{k}: {v}" for k, v in attrs.items()]
            lines.append(f"Attributs: {', '.join(attr_strs)}")
        # Skills
        skills = engine_stats.get("skills", [])
        if skills:
            lines.append("Compétences:")
            for s in skills:
                if isinstance(s, dict):
                    lines.append(f"  - {s.get('name', '?')}: {s.get('dice_value', '?')}")
        # Wounds
        wounds = engine_stats.get("wounds", {})
        active_wounds = [k for k, v in wounds.items() if v]
        if active_wounds:
            lines.append(f"Blessures: {', '.join(active_wounds)}")
        # Force points
        fp = engine_stats.get("force_points")
        if fp is not None:
            lines.append(f"Points de Force: {fp}")
        lines.append("")
        return lines

    # =========================================================================
    # Progression
    # =========================================================================

    def get_progression_system_prompt(self) -> str:
        return (
            "Tu analyses la progression d'un personnage dans un jeu utilisant le système D6.\n\n"
            "## RÈGLES D'AMÉLIORATION D6\n"
            "- Les compétences utilisées en jeu peuvent être améliorées\n"
            "- Progression : 2D → 2D+1 → 2D+2 → 3D → 3D+1 → 3D+2 → 4D → ...\n"
            "- Chaque +1 est un pip. 3 pips = +1 dé\n"
            "- Maximum 1-2 upgrades par extraction\n"
            "- Ne propose des upgrades que pour des compétences réellement utilisées\n"
            "- Les upgrades doivent être justifiés par les jets récents\n"
            "- Retourne un JSON vide si aucune progression n'est justifiée\n"
        )

    def build_progression_user_prompt(
        self, stats: dict, rolls: list[dict], narrative_summary: str
    ) -> str:
        lines = ["## État actuel du personnage"]

        # Attributes
        attrs = stats.get("attributes", {})
        if attrs:
            lines.append("### Attributs")
            for name, value in attrs.items():
                lines.append(f"- {name}: {value}")

        # Skills
        skills = stats.get("skills", [])
        if skills:
            lines.append("### Compétences")
            for s in skills:
                if isinstance(s, dict):
                    lines.append(
                        f"- {s.get('name', '?')} ({s.get('attribute', '?')}): {s.get('dice_value', '?')}"
                    )

        # Recent rolls
        if rolls:
            lines.append("\n## Jets récents")
            for r in rolls[-5:]:
                outcome = r.get("outcome", "?")
                skill = r.get("skill_used", "?")
                lines.append(f"- {skill}: {outcome}")

        lines.append("\n## Résumé narratif récent")
        lines.append(narrative_summary or "(aucun)")
        lines.append("\nAnalyse si des compétences méritent une amélioration. Retourne un JSON vide si rien ne change.")
        return "\n".join(lines)

    def get_progression_tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_upgrades": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string"},
                            "new_dice_value": {
                                "type": "string",
                                "description": "New dice code, e.g. '3D+1', '4D'",
                            },
                            "reason": {
                                "type": "string",
                                "maxLength": 200,
                                "description": "Why this skill improved",
                            },
                        },
                        "required": ["skill_name", "new_dice_value", "reason"],
                    },
                    "description": "Skills to upgrade based on recent usage",
                },
            },
        }

    async def apply_progression(
        self, conn, game_id: UUID, extraction: dict
    ) -> dict:
        changes = {}

        for upgrade in extraction.get("skill_upgrades", []):
            skill_name = upgrade.get("skill_name", "")
            new_dice_value = upgrade.get("new_dice_value", "")
            if not skill_name or not new_dice_value:
                continue

            # Validate dice code
            num_dice, pips = parse_dice_code(new_dice_value)
            if num_dice <= 0:
                continue

            result = await conn.execute(
                """
                UPDATE skills_d6 SET dice_value = $1
                WHERE game_id = $2 AND name = $3
                """,
                new_dice_value.upper().strip(),
                game_id,
                skill_name,
            )
            if result and "UPDATE 1" in result:
                changes.setdefault("skill_upgrades", []).append(
                    {"skill": skill_name, "new_value": new_dice_value}
                )

        return changes

    # =========================================================================
    # Inventory object extensions
    # =========================================================================

    def get_object_prompt_addon(self) -> str:
        return (
            'For mechanically relevant items (weapons, tools, armor), add `"engine_data": '
            '{"stats": {"damage": "4D", "range": "short"}}` with D6 dice codes for '
            "relevant mechanical properties."
        )

    async def create_object_extension(
        self, conn, object_id: UUID, engine_data: dict
    ) -> None:
        stats = engine_data.get("stats", {})
        if stats:
            await conn.execute(
                """
                INSERT INTO object_d6 (object_id, stats)
                VALUES ($1, $2)
                ON CONFLICT (object_id) DO NOTHING
                """,
                object_id,
                stats,
            )
