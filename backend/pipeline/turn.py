"""A narration turn (LIGHT / FIRST_LIGHT): load, arbitrate, narrate, commit, respond, schedule."""

from pipeline.context import TurnContext
from pipeline.steps.arbitrate import HALT, Arbitration, arbitrate
from pipeline.steps.commit import Committed, commit_turn
from pipeline.steps.load import load_turn
from pipeline.steps.narrate import Narrated, narrate
from pipeline.steps.respond import respond
from pipeline.steps.schedule import schedule_background
from pipeline.uncancellable import finish_despite_cancel


async def run_turn(ctx: TurnContext) -> None:
    """Run one narration turn. Catches nothing: the API adapter reports failures."""
    prepared = await load_turn(ctx)
    arbitration = await arbitrate(ctx, prepared)
    if arbitration is HALT:
        return
    narrated = await narrate(ctx, prepared, arbitration)
    committed = await commit_turn(ctx, prepared, arbitration, narrated)
    # Saved: what follows completes even if the client closes the stream (#20).
    await finish_despite_cancel(_after_commit(ctx, narrated, arbitration, committed),
                                ref=ctx.ref)


async def _after_commit(ctx: TurnContext, narrated: Narrated, arbitration: Arbitration,
                        committed: Committed) -> None:
    await respond(ctx, narrated, arbitration, committed)
    await schedule_background(ctx, narrated, committed)
