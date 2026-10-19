"""GET /session/cost: the requesting user's all-time spend (GHSA-w889), read from llm_calls
(#106)."""

import pytest

from tests.helpers import auth_headers

pytestmark = pytest.mark.usefixtures("seeded_random")


async def test_session_cost_is_per_user(harness, world_game, second_user, monkeypatch):
    from services import pricing
    monkeypatch.setitem(
        pricing._DYNAMIC_PRICING, "scripted/scripted-model",
        pricing.ModelPricing(input=3.0, output=15.0))
    await harness.chat(world_game, "Je regarde autour de moi.")
    await harness.drain()

    mine = (await harness.client.get("/api/session/cost", headers=harness.headers)).json()
    other = (await harness.client.get(
        "/api/session/cost", headers=auth_headers(second_user["token"]))).json()
    assert mine["total_cost_usd"] > 0
    assert other["total_cost_usd"] == 0
    assert other["purposes"] == {}


async def test_session_cost_survives_a_restart(harness, world_game, monkeypatch):
    # The account total is read from llm_calls (#106): a fresh process ledger loses nothing.
    import llm.usage
    from llm.usage import UsageLedger
    from services import pricing
    monkeypatch.setitem(
        pricing._DYNAMIC_PRICING, "scripted/scripted-model",
        pricing.ModelPricing(input=3.0, output=15.0))
    await harness.chat(world_game, "Je regarde autour de moi.")
    await harness.drain()

    before = (await harness.client.get("/api/session/cost", headers=harness.headers)).json()
    monkeypatch.setattr(llm.usage, "_ledger", UsageLedger())  # the "restart"
    after = (await harness.client.get("/api/session/cost", headers=harness.headers)).json()
    assert before["total_cost_usd"] > 0
    assert after == before
