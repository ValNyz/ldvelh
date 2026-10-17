"""A narration turn (LIGHT / FIRST_LIGHT): load, arbitrate, narrate, commit, respond, schedule."""

import logging
import time

from llm.session import Purpose
from pipeline.context import TurnContext
from pipeline.errors import finish_saved
from pipeline.steps.arbitrate import HALT, Arbitration, arbitrate
from pipeline.steps.commit import Committed, commit_turn
from pipeline.steps.load import Prepared, load_turn
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


def _log_halted(ctx: TurnContext, started: float) -> None:
    """One INFO line for a turn that stops on a pending roll (HALT): nothing narrated or billed."""
    logger.info(
        f"[TURN] game={ctx.request.game_id} engine={ctx.snapshot.engine} "
        f"provider={ctx.session.provider_name} halted=roll_pending "
        f"ms={int((time.perf_counter() - started) * 1000)}"
    )


async def run_turn(ctx: TurnContext) -> None:
    """Run one narration turn. Catches nothing: the API adapter reports failures."""
    started = time.perf_counter()
    prepared = await load_turn(ctx)
    arbitration = await arbitrate(ctx, prepared)
    if arbitration is HALT:
        _log_halted(ctx, started)
        return
    narrated = await narrate(ctx, prepared, arbitration)
    # Waiting for a connection stays cancellable (exhausted pool, #79); once it is held,
    # the commit and what follows it complete even if the client leaves (#20).
    # Invariant: no await between acquire() and finish_despite_cancel(), which creates the
    # shielded task synchronously: that task owns `conn` and always releases it.
    conn = await ctx.pool.acquire()
    await finish_despite_cancel(
        _commit_and_finish(ctx, conn, prepared, arbitration, narrated, started), ref=ctx.ref)


async def _commit_and_finish(ctx: TurnContext, conn, prepared: Prepared,
                             arbitration: Arbitration, narrated: Narrated,
                             started: float) -> None:
    try:
        committed = await commit_turn(ctx, conn, prepared, arbitration, narrated)
    finally:
        await ctx.pool.release(conn)
    # Saved: a failure from here on must not invite a resend.
    await finish_saved(_after_commit(ctx, narrated, arbitration, committed, started), ref=ctx.ref)


async def _after_commit(ctx: TurnContext, narrated: Narrated, arbitration: Arbitration,
                        committed: Committed, started: float) -> None:
    _log_summary(ctx, narrated, started)
    await respond(ctx, narrated, arbitration, committed)
    await schedule_background(ctx, narrated, committed)
