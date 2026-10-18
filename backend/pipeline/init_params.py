"""Wizard parameters of a world generation, kept on the game until its world exists (#88).

The first __INIT__ comes from the wizard with the parameters; a retry after a failed
generation comes either bare (game list, another browser: the stored set is reused) or
with the wizard's parameters (« Modifier les paramètres », or the draft this browser kept).
Parameters that are sent replace the stored set entirely, before the paid world call and
outside the world transaction, so a failure keeps them: a part the player cleared (sent
as null) is cleared, never restored from an earlier attempt.
"""

import logging
from uuid import UUID

from pipeline.context import InitParams
from repos import games as games_repo

logger = logging.getLogger(__name__)


async def resolve(conn, game_id: UUID, sent: InitParams | None, game_engine: str) -> InitParams:
    """What this generation uses: the parameters sent (then stored), else the stored ones;
    the engine sent, else the game's."""
    engine = (sent.engine if sent else None) or game_engine
    if sent is not None and sent.carries_wizard:
        await games_repo.save_init_params(
            conn, game_id, engine=sent.engine, world_config=sent.world_config,
            character_data=sent.character_data, manual_entities=sent.manual_entities)
        return InitParams(engine=engine, world_config=sent.world_config,
                          character_data=sent.character_data,
                          manual_entities=sent.manual_entities, carries_wizard=True)
    stored = await games_repo.get_init_params(conn, game_id)
    logger.info("[INIT] Bare retry: stored wizard parameters reused")
    return InitParams(engine=engine, world_config=stored.get("world_config"),
                      character_data=stored.get("character_data"),
                      manual_entities=stored.get("manual_entities"))
