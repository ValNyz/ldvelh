"""A narration turn (LIGHT / FIRST_LIGHT): load, arbitrate, narrate, commit, respond, schedule."""

from pipeline.context import TurnContext
from pipeline.steps.arbitrate import HALT, arbitrate
from pipeline.steps.commit import commit_turn
from pipeline.steps.load import load_turn
from pipeline.steps.narrate import narrate
from pipeline.steps.respond import respond
from pipeline.steps.schedule import schedule_background


async def run_turn(ctx: TurnContext) -> None:
    """Run one narration turn. Catches nothing: the API adapter reports failures."""
    prepared = await load_turn(ctx)
    arbitration = await arbitrate(ctx, prepared)
    if arbitration is HALT:
        return
    narrated = await narrate(ctx, prepared, arbitration)
    committed = await commit_turn(ctx, prepared, arbitration, narrated)
    await respond(ctx, narrated, arbitration, committed)
    await schedule_background(ctx, narrated, committed)
