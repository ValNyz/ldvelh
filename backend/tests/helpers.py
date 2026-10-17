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


async def save_pair(pool, game_id, user_message, assistant_message, *, cycle=1, time="",
                    game_date=None, location_ref=None, narrator_deltas=None,
                    engine_snapshot=None):
    """repos.turns.save_turn_messages with an explicit state; returns (user_id, assistant_id).

    `time` defaults to "" like a narration without a time block (NarrationState.time is a str).
    """
    from domain.turn import NarrationState
    from repos import turns

    state = NarrationState(cycle=cycle, time=time, location=location_ref, npcs_present=[],
                           date=game_date)
    async with pool.acquire() as conn:
        return await turns.save_turn_messages(
            conn, game_id, user_message=user_message, assistant_message=assistant_message,
            state=state, narrator_deltas=narrator_deltas or {}, engine_snapshot=engine_snapshot,
        )


async def log_roll(pool, game_id, roll, *, message_id=None, engine="fate_core", cycle=1):
    """repos.turns.log_mechanic_roll on its own connection; returns the roll id."""
    from repos import turns

    async with pool.acquire() as conn:
        return await turns.log_mechanic_roll(conn, game_id, message_id=message_id,
                                             engine=engine, roll=roll, cycle=cycle)


async def insert_llm_model(pool, model_id, **kw):
    """One llm_models row; keyword overrides for provider, label, status, roles, rank, prices."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO llm_models (provider, model_id, label, status, roles, default_rank,
                   input_price, output_price, cache_write_price, cache_read_price, profile)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            kw.get("provider", "p"), model_id, kw.get("label", model_id),
            kw.get("status", "enabled"), kw.get("roles", ["narration"]), kw.get("rank"),
            kw.get("inp"), kw.get("out"), kw.get("cw"), kw.get("cr"), kw.get("profile", {}),
        )


# =============================================================================
# Fate turns: engine state snapshot and stress-ticking rolls
# =============================================================================

STRESS = {"stress_type": "physical", "stress_amount": 1}


async def engine_state(pool, game_id) -> dict:
    """Everything a turn may write for a Fate game: stress, cycle, engine lock, message/roll counts."""
    async with pool.acquire() as conn:
        game = await conn.fetchrow(
            "SELECT current_cycle, engine_locked FROM games WHERE id = $1", game_id)
        return {
            "stress": list(await conn.fetchval(
                "SELECT stress_physical FROM character_fate WHERE game_id = $1", game_id)),
            "cycle": game["current_cycle"],
            "engine_locked": game["engine_locked"],
            "messages": await conn.fetchval(
                "SELECT count(*) FROM messages WHERE game_id = $1", game_id),
            "rolls": await conn.fetchval(
                "SELECT count(*) FROM mechanic_rolls WHERE game_id = $1", game_id),
        }


def stress_on_every_roll(monkeypatch):
    """Successful Fate rolls (all +1) whose details also check a physical stress box."""
    from types import SimpleNamespace

    from services.engine import fate_core

    monkeypatch.setattr(fate_core, "random", SimpleNamespace(choice=lambda seq: 1))
    original = fate_core.FateCoreEngine.roll_dice

    def roll_with_stress(self, decision):
        roll = original(self, decision)
        roll.details.update(STRESS)
        return roll

    monkeypatch.setattr(fate_core.FateCoreEngine, "roll_dice", roll_with_stress)
