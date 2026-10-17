"""Credits: what is stored is what the ledger applied (#33)."""

import json

import pytest_asyncio

from schema.narration import CREDIT_DELTA_CAP, CreditDelta
from tests.characterization import payloads
from tests.characterization.conftest import harness, llm_mode, scripted_llm  # noqa: F401
from tests.characterization.harness import spy_narration


@pytest_asyncio.fixture
async def game(harness):  # noqa: F811
    """Game with arrival played and a balance of 50."""
    game_id = await harness.create_game("none")
    await harness.init_world(game_id)
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    async with harness.pool.acquire() as conn:
        await conn.execute("UPDATE protagonists SET credits = 50 WHERE game_id = $1", game_id)
    return game_id


async def _balance(harness, game_id) -> int:
    async with harness.pool.acquire() as conn:
        return await conn.fetchval("SELECT credits FROM protagonists WHERE game_id = $1", game_id)


async def _debit(harness, game_id, amount: int) -> None:
    data = json.loads(payloads.NARRATION)
    data["credit_delta"] = {"amount": amount, "description": "Achat"}
    harness.llm._responses["narration"] = json.dumps(data, ensure_ascii=False)
    await harness.chat(game_id, "J'achète.")
    await harness.drain()


async def _last_credit_delta(harness, game_id) -> dict:
    async with harness.pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT narrator_deltas FROM messages WHERE game_id = $1 AND role = 'assistant'"
            " ORDER BY sequence DESC LIMIT 1", game_id)
    return (json.loads(raw) if isinstance(raw, str) else raw)["credit_delta"]


async def _rollback_last_turn(harness, game_id) -> None:
    r = await harness.client.get(f"/api/games/{game_id}", headers=harness.headers)
    last_user = [m for m in r.json()["messages"] if m["role"] == "user"][-1]
    r = await harness.client.post(f"/api/games/{game_id}/rollback",
                                  json={"messageId": last_user["id"]}, headers=harness.headers)
    assert r.status_code == 200, r.text


async def test_refused_debit_is_stored_as_not_applied(harness, game):
    await _debit(harness, game, -2000)
    stored = await _last_credit_delta(harness, game)
    assert stored["applied"] is False
    assert stored["error"]
    assert await _balance(harness, game) == 50


async def test_rollback_of_a_refused_debit_keeps_the_balance(harness, game):
    await _debit(harness, game, -2000)
    await _rollback_last_turn(harness, game)
    assert await _balance(harness, game) == 50


async def test_rollback_of_an_applied_debit_restores_the_balance(harness, game):
    await _debit(harness, game, -10)
    assert await _balance(harness, game) == 40
    assert (await _last_credit_delta(harness, game))["applied"] is True
    await _rollback_last_turn(harness, game)
    assert await _balance(harness, game) == 50


def test_huge_credit_delta_is_clamped():
    assert CREDIT_DELTA_CAP == 100_000
    assert CreditDelta(amount=10**12, description="x").amount == 100_000
    assert CreditDelta(amount=-10**12, description="x").amount == -100_000


async def test_next_turn_context_has_the_refusal_notice(harness, game, monkeypatch):
    await _debit(harness, game, -2000)
    calls = spy_narration(monkeypatch)
    await harness.chat(game, "Je continue.")
    await harness.drain()
    prompt = json.dumps(calls[-1]["messages"], ensure_ascii=False)
    assert "Transaction refusée" in prompt
    assert "AVIS DU SYSTÈME" in prompt
