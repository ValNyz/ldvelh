"""A narration turn (LIGHT / FIRST_LIGHT): load, arbitrate, narrate, commit, respond, schedule."""

import logging
import time

from llm.session import Purpose
from pipeline.context import TurnContext
from pipeline.steps.arbitrate import HALT, Arbitration, arbitrate
from pipeline.steps.commit import Committed, commit_turn
from pipeline.steps.load import load_turn
from pipeline.steps.narrate import Narrated, narrate
from pipeline.steps.respond import respond
from pipeline.steps.schedule import schedule_background
from pipeline.uncancellable import finish_despite_cancel

logger = logging.getLogger(__name__)


def _log_summary(ctx: TurnContext, narrated: Narrated, started: float) -> None:
    """One INFO line per completed turn: no prompt, no story text."""
    cost = narrated.cost or {}
    session = ctx.session
    logger.info(
        f"[TURN] game={ctx.request.game_id} engine={ctx.snapshot.engine} "
        f"provider={session.provider_name} model={session.model_for(Purpose.NARRATION)} "
        f"history={narrated.history} in={cost.get('input_tokens', 0)} "
        f"out={cost.get('output_tokens', 0)} cache_read={cost.get('cache_read_input_tokens', 0)} "
        f"cost=${cost.get('cost_usd', 0):.4f} ms={int((time.perf_counter() - started) * 1000)}"
    )


async def run_turn(ctx: TurnContext) -> None:
    """Run one narration turn. Catches nothing: the API adapter reports failures."""
    started = time.perf_counter()
    prepared = await load_turn(ctx)
    arbitration = await arbitrate(ctx, prepared)
    if arbitration is HALT:
        return
    narrated = await narrate(ctx, prepared, arbitration)
    committed = await commit_turn(ctx, prepared, arbitration, narrated)
    # A HALT turn (roll awaiting aspects) is not completed: no summary line.
    _log_summary(ctx, narrated, started)
    # Saved: what follows completes even if the client closes the stream (#20).
    await finish_despite_cancel(_after_commit(ctx, narrated, arbitration, committed),
                                ref=ctx.ref)


async def _after_commit(ctx: TurnContext, narrated: Narrated, arbitration: Arbitration,
                        committed: Committed) -> None:
    await respond(ctx, narrated, arbitration, committed)
    await schedule_background(ctx, narrated, committed)
