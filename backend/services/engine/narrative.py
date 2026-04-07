"""
LDVELH - Narrative Engine
Traits-based resistance system. LLM judges outcomes based on character traits.
No dice — the narrator decides success/failure using trait information.
"""

import json
from uuid import UUID

from schema.engine import EngineType, MechanicalDecision, RollResult
from .base import BaseEngine


class NarrativeEngine(BaseEngine):
    engine_type = EngineType.NARRATIVE

    async def get_stats(self, conn, game_id: UUID) -> dict:
        """Load traits from traits_narrative table."""
        rows = await conn.fetch(
            """
            SELECT name, description, active, replaced_by, created_cycle
            FROM traits_narrative
            WHERE game_id = $1 AND active = TRUE
            ORDER BY created_cycle
            """,
            game_id,
        )
        return {
            "traits": [
                {"name": r["name"], "description": r["description"]}
                for r in rows
            ]
        }

    async def get_vitals_display(self, conn, game_id: UUID) -> dict:
        """Narrative engine has no vitals, only traits."""
        stats = await self.get_stats(conn, game_id)
        return {"traits": stats.get("traits", [])}

    async def create_character(self, conn, game_id: UUID, data: dict) -> None:
        """Create character_narrative row and initial traits."""
        await conn.execute(
            "INSERT INTO character_narrative (game_id) VALUES ($1)",
            game_id,
        )
        traits = data.get("traits", [])
        for trait in traits:
            await conn.execute(
                """
                INSERT INTO traits_narrative (game_id, name, description, created_cycle)
                VALUES ($1, $2, $3, $4)
                """,
                game_id,
                trait.get("name", ""),
                trait.get("description"),
                trait.get("created_cycle", 1),
            )

    async def get_npc_stats(self, conn, character_id: UUID) -> dict:
        """Load NPC traits from npc_narrative table."""
        row = await conn.fetchrow(
            "SELECT traits FROM npc_narrative WHERE character_id = $1",
            character_id,
        )
        if not row:
            return {}
        traits = row["traits"] if isinstance(row["traits"], list) else json.loads(row["traits"])
        return {"traits": traits}

    async def create_npc_stats(self, conn, character_id: UUID, data: dict) -> None:
        """Create npc_narrative row."""
        traits = data.get("traits", [])
        await conn.execute(
            "INSERT INTO npc_narrative (character_id, traits) VALUES ($1, $2::jsonb)",
            character_id,
            json.dumps(traits),
        )

    async def apply_roll_result(
        self, conn, game_id: UUID, roll: RollResult, cycle: int
    ) -> dict:
        return {}

    async def snapshot_state(self, conn, game_id: UUID) -> dict:
        """Snapshot active traits for rollback."""
        rows = await conn.fetch(
            """
            SELECT name, description, active, created_cycle
            FROM traits_narrative
            WHERE game_id = $1 AND active = TRUE
            """,
            game_id,
        )
        return {
            "traits": [dict(r) for r in rows],
        }

    async def restore_snapshot(self, conn, game_id: UUID, snapshot: dict) -> None:
        """Restore traits from snapshot."""
        # Deactivate all current traits
        await conn.execute(
            "UPDATE traits_narrative SET active = FALSE WHERE game_id = $1",
            game_id,
        )
        # Re-insert snapshot traits
        for trait in snapshot.get("traits", []):
            await conn.execute(
                """
                INSERT INTO traits_narrative (game_id, name, description, active, created_cycle)
                VALUES ($1, $2, $3, TRUE, $4)
                ON CONFLICT (game_id, name) DO UPDATE SET
                    active = TRUE,
                    description = EXCLUDED.description
                """,
                game_id,
                trait["name"],
                trait.get("description"),
                trait.get("created_cycle", 1),
            )

    def needs_mechanical_step(self) -> bool:
        return False

    def roll_dice(self, decision: MechanicalDecision) -> RollResult:
        raise NotImplementedError("NarrativeEngine does not roll dice")

    def build_narrator_addon(self, roll_result: RollResult | None) -> str:
        return ""

    def get_gauge_policy(self) -> str:
        return "none"

    def get_system_prompt_addon(self) -> str:
        return """
## MOTEUR NARRATIF (TRAITS)

Le protagoniste possède des **traits narratifs** qui influencent le récit.
Quand une action met en jeu un trait, utilise-le comme guide de résistance :
- Un trait pertinent augmente les chances de succès
- L'absence de trait pertinent rend l'action plus difficile
- Sois honnête sur les échecs : si rien ne justifie la réussite, c'est un échec

Les traits sont listés dans le contexte sous "TRAITS DU PERSONNAGE".
"""

    def build_context_stats(self, engine_stats: dict) -> list[str]:
        lines = []
        traits = engine_stats.get("traits", [])
        if traits:
            lines.append("### TRAITS DU PERSONNAGE")
            for t in traits:
                if isinstance(t, dict):
                    name = t.get("name", "?")
                    desc = t.get("description", "")
                    lines.append(f"- **{name}**: {desc}" if desc else f"- **{name}**")
                else:
                    lines.append(f"- {t}")
            lines.append("")
        return lines

    # =========================================================================
    # Progression
    # =========================================================================

    def get_progression_system_prompt(self) -> str:
        return (
            "Tu analyses la progression narrative d'un personnage dans un jeu de rôle solo.\n"
            "Le personnage a des **traits narratifs** qui évoluent au fil du récit.\n\n"
            "## RÈGLES\n"
            "- Un trait peut apparaître quand le personnage vit une expérience marquante\n"
            "- Un trait peut être désactivé s'il n'est plus pertinent\n"
            "- Un trait peut être remplacé par une version évoluée\n"
            "- Maximum 1-2 changements par extraction\n"
            "- Ne propose des changements que si le récit le justifie clairement\n"
            "- Les traits doivent être concis (2-5 mots) avec une description courte\n"
        )

    def build_progression_user_prompt(
        self, stats: dict, rolls: list[dict], narrative_summary: str
    ) -> str:
        lines = ["## Traits actuels"]
        traits = stats.get("traits", [])
        if traits:
            for t in traits:
                name = t.get("name", "?") if isinstance(t, dict) else str(t)
                desc = t.get("description", "") if isinstance(t, dict) else ""
                lines.append(f"- **{name}**: {desc}" if desc else f"- **{name}**")
        else:
            lines.append("(aucun trait)")
        lines.append("")
        lines.append("## Résumé narratif récent")
        lines.append(narrative_summary or "(aucun)")
        lines.append("")
        lines.append("Analyse si des traits doivent évoluer. Retourne un JSON vide si rien ne change.")
        return "\n".join(lines)

    def get_progression_tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "new_traits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "maxLength": 100},
                            "description": {"type": "string", "maxLength": 300},
                        },
                        "required": ["name"],
                    },
                    "description": "New traits gained from recent experiences",
                },
                "traits_deactivated": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of traits no longer relevant",
                },
                "traits_replaced": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_trait": {"type": "string"},
                            "new_trait_name": {"type": "string", "maxLength": 100},
                            "new_trait_description": {"type": "string", "maxLength": 300},
                        },
                        "required": ["old_trait", "new_trait_name"],
                    },
                    "description": "Traits that evolved into new versions",
                },
            },
        }

    async def apply_progression(
        self, conn, game_id: UUID, extraction: dict
    ) -> dict:
        changes = {}

        # New traits
        for trait in extraction.get("new_traits", []):
            await conn.execute(
                """
                INSERT INTO traits_narrative (game_id, name, description, active, created_cycle)
                VALUES ($1, $2, $3, TRUE, (SELECT COALESCE(MAX(cycle), 1) FROM messages WHERE game_id = $1))
                ON CONFLICT (game_id, name) DO UPDATE SET active = TRUE, description = EXCLUDED.description
                """,
                game_id,
                trait.get("name", ""),
                trait.get("description"),
            )
        if extraction.get("new_traits"):
            changes["new_traits"] = [t.get("name") for t in extraction["new_traits"]]

        # Deactivated traits
        for trait_name in extraction.get("traits_deactivated", []):
            await conn.execute(
                "UPDATE traits_narrative SET active = FALSE WHERE game_id = $1 AND name = $2",
                game_id,
                trait_name,
            )
        if extraction.get("traits_deactivated"):
            changes["traits_deactivated"] = extraction["traits_deactivated"]

        # Replaced traits
        for replacement in extraction.get("traits_replaced", []):
            old_name = replacement.get("old_trait", "")
            new_name = replacement.get("new_trait_name", "")
            new_desc = replacement.get("new_trait_description")

            # Insert new trait
            new_id = await conn.fetchval(
                """
                INSERT INTO traits_narrative (game_id, name, description, active, created_cycle)
                VALUES ($1, $2, $3, TRUE, (SELECT COALESCE(MAX(cycle), 1) FROM messages WHERE game_id = $1))
                ON CONFLICT (game_id, name) DO UPDATE SET active = TRUE, description = EXCLUDED.description
                RETURNING id
                """,
                game_id,
                new_name,
                new_desc,
            )
            # Deactivate old and link
            if new_id:
                await conn.execute(
                    "UPDATE traits_narrative SET active = FALSE, replaced_by = $1 WHERE game_id = $2 AND name = $3",
                    new_id,
                    game_id,
                    old_name,
                )
        if extraction.get("traits_replaced"):
            changes["traits_replaced"] = [
                {"old": r.get("old_trait"), "new": r.get("new_trait_name")}
                for r in extraction["traits_replaced"]
            ]

        return changes

    # =========================================================================
    # Inventory object extensions
    # =========================================================================

    def get_object_prompt_addon(self) -> str:
        return (
            'For objects with special narrative weight, add `"engine_data": '
            '{"narrative_description": "..."}` with a short text describing '
            "the object's narrative significance."
        )

    async def create_object_extension(
        self, conn, object_id: UUID, engine_data: dict
    ) -> None:
        desc = engine_data.get("narrative_description")
        if desc:
            await conn.execute(
                """
                INSERT INTO object_narrative (object_id, narrative_description)
                VALUES ($1, $2)
                ON CONFLICT (object_id) DO NOTHING
                """,
                object_id,
                desc,
            )
