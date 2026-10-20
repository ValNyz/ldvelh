"""
Shared helpers for integration tests.
"""

from llm.usage import UsageLedger


def auth_headers(token: str) -> dict:
    """Build Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


# Each wizard part fits WIZARD_FORM_MAX_CHARS, the three together do not: /chat and
# /world/enhance must refuse it alike (one bounded form type, api/request_types.py).
OVERSIZED_WIZARD_FORM = {part: {"lore": "x" * 9_000}
                         for part in ("world_config", "character_data", "manual_entities")}


class RecordingLedger(UsageLedger):
    """Usage ledger that remembers the purpose of every call it records."""

    def __init__(self):
        super().__init__()
        self.purposes: list[str] = []

    def record(self, purpose, *args, **kwargs) -> dict:
        self.purposes.append(purpose)
        return super().record(purpose, *args, **kwargs)


# =============================================================================
# Turn writes for test setup (repos.turns and services.turn_effects on a pooled connection)
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


async def apply_state(pool, game_id, narration, current_cycle, *, turn_id=None):
    """turn_effects.apply_narration_state on its own connection, journaled under `turn_id`."""
    from repos.uow import uow
    from services import turn_effects

    async with pool.acquire() as conn, uow(conn, turn_id):
        return await turn_effects.apply_narration_state(conn, game_id, narration,
                                                        current_cycle)


async def apply_deltas(pool, game_id, narration, cycle, *, turn_id=None):
    """turn_effects.apply_narrator_deltas on its own connection, journaled under `turn_id`."""
    from repos.uow import uow
    from services import turn_effects

    async with pool.acquire() as conn, uow(conn, turn_id):
        return await turn_effects.apply_narrator_deltas(conn, game_id, narration, cycle)


async def open_turn(pool, game_id):
    """A new open turn of the game (repos.turns.open_turn on its own connection)."""
    from repos import turns

    async with pool.acquire() as conn:
        return await turns.open_turn(conn, game_id)


async def store_requests(pool, game_id, requests):
    """repos.turns.store_info_requests on its own connection."""
    from repos import turns

    async with pool.acquire() as conn:
        await turns.store_info_requests(conn, game_id, requests)


async def resolve_place(conn, game_id, state):
    """The state with its place resolved for the message stamp, as the commit does it: a
    live location, else counted (`ref_dropped`, identity_events) and stamped None."""
    from dataclasses import replace

    from kg import refs
    from services.identity.service import IdentityService

    if state.location_resolved:
        return state
    identity = await IdentityService.for_game(conn, game_id)
    location_id = await refs.optional(
        identity, conn, [], "message location", state.location, "location", live=True
    )
    return replace(state, location_id=location_id, location_resolved=True)


async def save_pair(pool, game_id, user_message, assistant_message, *, cycle=1, time="",
                    game_date=None, location_ref=None, narrator_deltas=None,
                    engine_snapshot=None, turn_id=None):
    """repos.turns.save_turn_messages with an explicit state, journaled under `turn_id`
    (`location_ref` resolved by resolve_place); returns (user_id, assistant_id).

    `time` defaults to "" like a narration without a time block (NarrationState.time is a str).
    """
    from domain.turn import NarrationState
    from repos import turns
    from repos.uow import uow

    state = NarrationState(cycle=cycle, time=time, location=location_ref, npcs_present=[],
                           date=game_date)
    async with pool.acquire() as conn, uow(conn, turn_id):
        state = await resolve_place(conn, game_id, state)
        return await turns.save_turn_messages(
            conn, game_id, user_message=user_message, assistant_message=assistant_message,
            state=state, narrator_deltas=narrator_deltas or {}, engine_snapshot=engine_snapshot,
            turn_id=turn_id,
        )


async def log_roll(pool, game_id, roll, *, message_id=None, engine="fate_core", cycle=1,
                   turn_id=None):
    """repos.turns.log_mechanic_roll on its own connection, journaled under `turn_id`;
    returns the roll id."""
    from repos import turns
    from repos.uow import uow

    async with pool.acquire() as conn, uow(conn, turn_id):
        return await turns.log_mechanic_roll(conn, game_id, message_id=message_id,
                                             engine=engine, roll=roll, cycle=cycle,
                                             turn_id=turn_id)


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


# =============================================================================
# Harness turns: narration payloads and rollback
# =============================================================================


def narration_with(**extra) -> str:
    """The characterization NARRATION payload with some top-level keys replaced or added."""
    import json

    from tests.characterization import payloads

    data = json.loads(payloads.NARRATION)
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


async def last_user_message_id(harness, game_id):
    """Id of the game's latest player message."""
    async with harness.pool.acquire() as conn:
        return await conn.fetchval(
            """SELECT id FROM messages WHERE game_id = $1 AND role = 'user'
               ORDER BY created_at DESC, sequence DESC LIMIT 1""", game_id)


async def rollback_last_turn(harness, game_id):
    """Roll back to before the latest player message, through the API."""
    user_msg = await last_user_message_id(harness, game_id)
    r = await harness.client.post(f"/api/games/{game_id}/rollback",
                                  json={"messageId": str(user_msg)}, headers=harness.headers)
    assert r.status_code == 200, r.text


# =============================================================================
# Extractor test setup
# =============================================================================


async def extractor_for(test_pool, test_user, raw_result):
    """A CharactersExtractor on a fresh game whose LLM call answers `raw_result`."""
    from llm.session import LLMSession
    from services.extraction.characters import CharactersExtractor
    from services.game_service import GameService
    from tests.test_llm_session import FakeProvider

    game_id = await GameService(test_pool).create_game(test_user["id"])
    extractor = CharactersExtractor(test_pool, game_id,
                                    LLMSession.from_provider(FakeProvider()))

    async def fake_call(*_args, **_kwargs):
        return raw_result, {"cost_usd": 0.001}

    extractor._call_llm = fake_call
    return extractor, game_id


async def character_names(test_pool, game_id):
    async with test_pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM characters WHERE game_id = $1", game_id)
    return {r["name"] for r in rows}
