"""Credits: what is stored is what the ledger applied (#33)."""

import json
from uuid import uuid4

import pytest
import pytest_asyncio

from schema.narration import CREDIT_DELTA_CAP, CreditDelta
from services.context_builder import ContextBuilder
from tests.characterization import payloads
from tests.characterization.harness import spy_narration
from tests.helpers import narration_with, rollback_last_turn


@pytest_asyncio.fixture
async def game(harness):
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
    harness.llm._responses["narration"] = narration_with(
        credit_delta={"amount": amount, "description": "Achat"})
    await harness.chat(game_id, "J'achète.")
    await harness.drain()


async def _last_credit_delta(harness, game_id) -> dict:
    async with harness.pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT narrator_deltas FROM messages WHERE game_id = $1 AND role = 'assistant'"
            " ORDER BY sequence DESC LIMIT 1", game_id)
    return (json.loads(raw) if isinstance(raw, str) else raw)["credit_delta"]


async def test_refused_debit_is_stored_as_not_applied(harness, game):
    await _debit(harness, game, -2000)
    stored = await _last_credit_delta(harness, game)
    assert stored["applied"] is False
    assert stored["error"]
    assert await _balance(harness, game) == 50


async def test_rollback_of_a_refused_debit_keeps_the_balance(harness, game):
    await _debit(harness, game, -2000)
    await rollback_last_turn(harness, game)
    assert await _balance(harness, game) == 50


async def test_rollback_of_an_applied_debit_restores_the_balance(harness, game):
    await _debit(harness, game, -10)
    assert await _balance(harness, game) == 40
    assert (await _last_credit_delta(harness, game))["applied"] is True
    await rollback_last_turn(harness, game)
    assert await _balance(harness, game) == 50


def test_huge_credit_delta_is_clamped():
    assert CREDIT_DELTA_CAP == 100_000
    assert CreditDelta(amount=10**12, description="x").amount == 100_000
    assert CreditDelta(amount=-10**12, description="x").amount == -100_000


async def _narration_prompt(harness, game_id, monkeypatch) -> str:
    """Play one plain turn; the messages sent to the narrator, as text."""
    harness.llm._responses["narration"] = payloads.NARRATION
    calls = spy_narration(monkeypatch)
    await harness.chat(game_id, "Je continue.")
    await harness.drain()
    return json.dumps(calls[-1]["messages"], ensure_ascii=False)


async def test_next_turn_context_has_the_refusal_notice(harness, game, monkeypatch):
    await _debit(harness, game, -2000)
    prompt = await _narration_prompt(harness, game, monkeypatch)
    assert "Transaction refusée" in prompt
    assert "AVIS DU SYSTÈME" in prompt


async def test_refusal_notice_lasts_one_turn(harness, game, monkeypatch):
    await _debit(harness, game, -2000)
    assert "Transaction refusée" in await _narration_prompt(harness, game, monkeypatch)
    assert "Transaction refusée" not in await _narration_prompt(harness, game, monkeypatch)


class _LastMessageReader:
    def __init__(self, credit: dict):
        self.credit = credit

    async def get_last_assistant_message(self, conn):
        return {"narrator_deltas": {"credit_delta": self.credit}}


REFUSED = "Transaction refusée au tour précédent : Achat (-5 cr)"


@pytest.mark.parametrize("error, expected", [
    ("Fonds insuffisants", f"{REFUSED} — Fonds insuffisants"),
    (None, REFUSED),
])
async def test_refused_debit_notice_omits_a_missing_error(error, expected):
    builder = ContextBuilder(None, uuid4())
    builder.reader = _LastMessageReader(
        {"amount": -5, "description": "Achat", "applied": False, "error": error})
    assert await builder._build_notices(None) == [expected]


@pytest.mark.parametrize("credit", [
    {"amount": -5, "description": "Achat", "applied": True, "error": None},
    {"amount": -5, "description": "Achat"},  # legacy row: no "applied" key
], ids=["applied", "legacy"])
async def test_applied_or_legacy_debit_yields_no_notice(credit):
    builder = ContextBuilder(None, uuid4())
    builder.reader = _LastMessageReader(credit)
    assert await builder._build_notices(None) == []
