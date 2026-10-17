"""
LDVELH - World creation helpers
POST /world/enhance: the player's short text enriches a whole wizard step (one LLM call);
an empty text has the step invented from the form's other choices.
- scope "world": the "Contexte libre" (lore) fills the world step;
- scope "character": the character description fills the character step.
"""

import json
import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from api import routes
from api.dependencies import get_current_user, get_pool
from llm.session import LLMSession
from repos.llm_models import load_catalog
from services.llm_providers import _CLASSES
from services.world_enhance import (
    ENGINES, SCOPES, WorldEnhanceFailed, enhance,
)
from utils.rate_limit import shared_limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["world"])

# Each call is a paid LLM call on the player's key: keep a double click or a loop cheap.
enhance_limiter = shared_limiter(max_requests=10, window_seconds=60)


# Far above what the wizard produces: an oversized form is refused before any LLM call.
MAX_FORM_CHARS = 20_000
MAX_ENTITIES_PER_KIND = 20


class WizardState(BaseModel):
    """The wizard form as it stands (same shape as the /chat init fields)."""

    world_config: dict | None = None
    character_data: dict | None = None
    manual_entities: dict | None = None

    @model_validator(mode="after")
    def _bounded(self):
        if len(json.dumps(self.model_dump(), ensure_ascii=False)) > MAX_FORM_CHARS:
            raise ValueError(f"form larger than {MAX_FORM_CHARS} characters")
        for kind, items in (self.manual_entities or {}).items():
            if isinstance(items, list) and len(items) > MAX_ENTITIES_PER_KIND:
                raise ValueError(f"more than {MAX_ENTITIES_PER_KIND} {kind}")
        return self


class WorldEnhanceRequest(BaseModel):
    scope: str = "world"  # "world" | "character"
    engine: str = "none"
    provider: str = "anthropic"
    model: str | None = None
    current: WizardState = Field(default_factory=WizardState)


@router.post("/world/enhance")
async def world_enhance(
    request: WorldEnhanceRequest,
    raw_request: Request,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return the scope's wizard fields, enriched from the player's text in that step."""
    enhance_limiter.check(raw_request)

    current = request.current.model_dump()
    if request.scope not in SCOPES:
        raise HTTPException(status_code=400, detail=f"Étape inconnue : {request.scope}")

    if request.engine not in ENGINES:
        raise HTTPException(status_code=400, detail=f"Moteur inconnu : {request.engine}")
    if request.provider not in _CLASSES:
        raise HTTPException(status_code=400, detail=f"Fournisseur inconnu : {request.provider}")

    api_key = await routes._resolve_user_api_key(pool, user["id"], request.provider)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"Aucune clé API configurée pour {request.provider}. "
                   "Ajoutez votre clé dans Paramètres > Modèle IA.",
        )

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT slug, label FROM genres
               WHERE is_preset = true OR user_id = $1
               ORDER BY is_preset DESC, label ASC""",
            user["id"],
        )
    genres = [dict(r) for r in rows]
    if not genres:
        raise HTTPException(status_code=500, detail="Aucun genre disponible")

    session = LLMSession(request.provider, api_key, request.model,
                         catalog=await load_catalog(pool), user_id=user["id"])
    try:
        result, cost = await enhance(session, request.scope, request.engine, genres, current)
    except WorldEnhanceFailed:
        raise HTTPException(
            status_code=502,
            detail="L'IA n'a pas pu remplir le formulaire. Réessaie ou reformule ton texte.",
        )
    return {**result, "cost": cost}
