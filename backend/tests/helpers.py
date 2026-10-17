"""
Shared helpers for integration tests.
"""


def auth_headers(token: str) -> dict:
    """Build Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# Turn writes for test setup (repos.turns on a pooled connection)
# =============================================================================


def make_roll(dice, total, outcome, *, skill=None, skill_total=None, shifts=None,
              complication=False, details=None):
    """RollResult for tests; `skill` goes to details.skill_name (the logged skill_used)."""
    from schema.engine import RollResult

    details = dict(details or {})
    if skill is not None:
        details["skill_name"] = skill
    return RollResult(dice=dice, total=total,
                      skill_total=total if skill_total is None else skill_total,
                      outcome=outcome, shifts=shifts, complication=complication,
                      details=details)


async def apply_state(pool, game_id, narration, current_cycle):
    """repos.turns.apply_narration_state on its own connection."""
    from repos import turns

    async with pool.acquire() as conn:
        return await turns.apply_narration_state(conn, game_id, narration, current_cycle)


async def apply_deltas(pool, game_id, narration, cycle):
    """repos.turns.apply_narrator_deltas on its own connection."""
    from repos import turns

    async with pool.acquire() as conn:
        return await turns.apply_narrator_deltas(conn, game_id, narration, cycle)


async def store_requests(pool, game_id, requests):
    """repos.turns.store_info_requests on its own connection."""
    from repos import turns

    async with pool.acquire() as conn:
        await turns.store_info_requests(conn, game_id, requests)


async def save_pair(pool, game_id, user_message, assistant_message, *, cycle=1, time=None,
                    game_date=None, location_ref=None, narrator_deltas=None,
                    engine_snapshot=None):
    """repos.turns.save_turn_messages with an explicit state; returns (user_id, assistant_id)."""
    from domain.turn import NarrationState
    from repos import turns

    state = NarrationState(cycle=cycle, time=time, location=location_ref, npcs_present=[],
                           date=game_date)
    async with pool.acquire() as conn:
        return await turns.save_turn_messages(
            conn, game_id, user_message=user_message, assistant_message=assistant_message,
            state=state, narrator_deltas=narrator_deltas, engine_snapshot=engine_snapshot,
        )


async def log_roll(pool, game_id, roll, *, message_id=None, engine="fate_core", cycle=1):
    """repos.turns.log_mechanic_roll on its own connection; returns the roll id."""
    from repos import turns

    async with pool.acquire() as conn:
        return await turns.log_mechanic_roll(conn, game_id, message_id=message_id,
                                             engine=engine, roll=roll, cycle=cycle)
