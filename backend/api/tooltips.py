"""
LDVELH - Tooltips API Routes
Expose les données du KG pour les tooltips frontend
"""

from uuid import UUID
from typing import Optional
import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.dependencies import get_pool


router = APIRouter(tags=["tooltips"])


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class TooltipInfo(BaseModel):
    """Info tooltip formatée pour le frontend"""

    icon: str
    nom: str
    type: str
    infos: list[str]
    relation: Optional[str] = None


class TooltipEntry(BaseModel):
    """Entrée tooltip complète"""

    entite_id: UUID
    entite_type: str
    entite_nom: str
    alias: list[str]
    connaissances: dict
    relation_valentin: Optional[dict] = None
    formatted: TooltipInfo


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Labels pour le formatage
TYPE_ICONS = {
    "personnage": "👤",
    "lieu": "📍",
    "organisation": "🏢",
    "objet": "📦",
    "arc_narratif": "📖",
    "ia": "🤖",
}

TYPE_LABELS = {
    "personnage": "Personnage",
    "lieu": "Lieu",
    "organisation": "Organisation",
    "objet": "Objet",
    "ia": "IA",
}

CONNAISSANCE_LABELS = {
    "metier": "Métier",
    "physique": "Apparence",
    "espece": "Espèce",
    "age": "Âge",
    "domicile": "Domicile",
    "hobby": "Hobby",
    "traits": "Traits",
    "type_lieu": "Type",
    "ambiance": "Ambiance",
    "horaires": "Horaires",
    "domaine": "Domaine",
    "type_org": "Type",
    "voix": "Voix",
    "occupation": "Occupation",
}

RELATION_LABELS = {
    "connait": "Connaissance",
    "ami_de": "Ami",
    "collegue_de": "Collègue",
    "superieur_de": "Supérieur",
    "employe_de": "Employeur",
    "travaille_a": "Lieu de travail",
    "habite": "Domicile",
    "frequente": "Lieu fréquenté",
    "possede": "Possédé",
}

# Ordre de priorité pour l'affichage des connaissances
PRIORITY_ORDER = [
    "metier",
    "physique",
    "espece",
    "age",
    "domicile",
    "hobby",
    "traits",
    "type_lieu",
    "ambiance",
    "horaires",
    "domaine",
    "type_org",
]


def truncate(text: str, max_len: int = 50) -> str:
    """Tronque un texte si nécessaire"""
    if not text or len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def format_connaissance(key: str, value) -> str:
    """Formate une connaissance pour affichage"""
    label = CONNAISSANCE_LABELS.get(key, key.replace("_", " ").title())

    if isinstance(value, list):
        val = ", ".join(str(v) for v in value)
    else:
        val = str(value)

    return f"{label}: {truncate(val)}"


def format_tooltip(entity_data: dict) -> TooltipInfo:
    """
    Formate les données d'une entité pour affichage tooltip.
    Equivalent de formatTooltip() dans knowledgeService.js
    """
    entite_type = entity_data.get("entite_type", "")
    entite_nom = entity_data.get("entite_nom", "")
    connaissances = entity_data.get("connaissances") or {}
    relation_valentin = entity_data.get("relation_valentin")

    # Icône selon type
    icon = TYPE_ICONS.get(entite_type, "❓")

    # Relation avec Valentin
    relation_txt = None
    if relation_valentin and relation_valentin.get("type"):
        rel_type = relation_valentin["type"]
        relation_txt = RELATION_LABELS.get(rel_type, rel_type)

    # Formater les connaissances
    infos = []

    # D'abord les clés prioritaires
    for key in PRIORITY_ORDER:
        if key in connaissances and connaissances[key]:
            infos.append(format_connaissance(key, connaissances[key]))

    # Puis le reste (sauf 'nom')
    for key, val in connaissances.items():
        if key not in PRIORITY_ORDER and key != "nom" and val:
            infos.append(format_connaissance(key, val))

    return TooltipInfo(
        icon=icon, nom=entite_nom, type=entite_type, infos=infos, relation=relation_txt
    )


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/tooltips")
async def get_tooltips(
    partie_id: UUID = Query(..., alias="partieId"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """
    GET /api/tooltips?partieId=xxx
    Retourne les données tooltip pour toutes les entités connues.

    Équivalent de la route Next.js /api/tooltips
    """
    async with pool.acquire() as conn:
        # Utiliser la vue kg_v_tooltip si elle existe, sinon construire la query
        rows = await conn.fetch(
            """
            SELECT 
                e.id as entite_id,
                e.type as entite_type,
                e.name as entite_nom,
                e.aliases as alias,
                COALESCE(
                    jsonb_object_agg(
                        f.attribute, f.value
                    ) FILTER (WHERE f.attribute IS NOT NULL),
                    '{}'::jsonb
                ) as connaissances,
                (
                    SELECT jsonb_build_object('type', r.type, 'props', r.properties)
                    FROM relations r
                    JOIN entities valentin ON valentin.id = r.target_id 
                        AND valentin.name = 'Valentin Dumont'
                    WHERE r.source_id = e.id
                    LIMIT 1
                ) as relation_valentin
            FROM entities e
            LEFT JOIN facts f ON f.entity_id = e.id AND f.game_id = e.game_id
            WHERE e.game_id = $1
              AND e.removed_cycle IS NULL
            GROUP BY e.id, e.type, e.name, e.aliases
        """,
            partie_id,
        )

    # Construire l'objet tooltips indexé par nom/alias
    tooltips = {}

    for row in rows:
        entity_data = {
            "entite_id": row["entite_id"],
            "entite_type": row["entite_type"],
            "entite_nom": row["entite_nom"],
            "alias": row["alias"] or [],
            "connaissances": dict(row["connaissances"]) if row["connaissances"] else {},
            "relation_valentin": dict(row["relation_valentin"])
            if row["relation_valentin"]
            else None,
        }

        # Formater pour le tooltip
        formatted = format_tooltip(entity_data)

        entry = {**entity_data, "formatted": formatted.model_dump()}

        # Stocker avec nom comme clé
        key = row["entite_nom"].lower()
        tooltips[key] = entry

        # Ajouter les alias comme clés alternatives
        for alias in row["alias"] or []:
            tooltips[alias.lower()] = entry

    return {"tooltips": tooltips}


@router.get("/tooltips/{entity_id}")
async def get_entity_tooltip(
    entity_id: UUID, pool: asyncpg.Pool = Depends(get_pool)
) -> dict:
    """
    GET /api/tooltips/{entity_id}
    Retourne les données détaillées d'une entité spécifique.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 
                e.id as entite_id,
                e.type as entite_type,
                e.name as entite_nom,
                e.aliases as alias,
                e.properties,
                COALESCE(
                    jsonb_object_agg(
                        f.attribute, f.value
                    ) FILTER (WHERE f.attribute IS NOT NULL),
                    '{}'::jsonb
                ) as connaissances
            FROM entities e
            LEFT JOIN facts f ON f.entity_id = e.id AND f.game_id = e.game_id
            WHERE e.id = $1
            GROUP BY e.id, e.type, e.name, e.aliases, e.properties
        """,
            entity_id,
        )

    if not row:
        return {"error": "Entity not found"}

    entity_data = {
        "entite_id": row["entite_id"],
        "entite_type": row["entite_type"],
        "entite_nom": row["entite_nom"],
        "alias": row["alias"] or [],
        "properties": dict(row["properties"]) if row["properties"] else {},
        "connaissances": dict(row["connaissances"]) if row["connaissances"] else {},
    }

    formatted = format_tooltip(entity_data)

    return {**entity_data, "formatted": formatted.model_dump()}
