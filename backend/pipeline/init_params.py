"""Wizard parameters of a world generation, kept on the game until its world exists (#88).

The first __INIT__ comes from the wizard with every parameter; a retry after a failed
generation comes from the game list with none. Each __INIT__ stores what it sends before
the paid world call (outside the world transaction, so a failure keeps it), and a field it
leaves out is read back from the game. A field it does send wins: the player may have
edited the wizard before retrying, and nothing was generated from the stored value yet.
"""

import logging
from uuid import UUID

from pipeline.context import InitParams
from repos import games as games_repo

logger = logging.getLogger(__name__)

_FIELDS = ("world_config", "character_data", "manual_entities")


async def resolve(conn, game_id: UUID, sent: InitParams | None, game_engine: str) -> InitParams:
    """What this generation uses: the parameters sent, else the stored ones; the engine
    sent, else the game's."""
    sent = sent or InitParams(engine=None, world_config=None, character_data=None,
                              manual_entities=None)
    await games_repo.save_init_params(
        conn, game_id, engine=sent.engine, world_config=sent.world_config,
        character_data=sent.character_data, manual_entities=sent.manual_entities)
    stored = await games_repo.get_init_params(conn, game_id)
    missing = [f for f in _FIELDS if getattr(sent, f) is None and stored.get(f) is not None]
    if missing:
        # Field names only: the values are the player's story text.
        logger.info(f"[INIT] Stored wizard parameters reused: {', '.join(missing)}")
    # Stored = sent where sent (save_init_params keeps a field only when it is None).
    return InitParams(engine=sent.engine or game_engine,
                      **{f: stored.get(f) for f in _FIELDS})
