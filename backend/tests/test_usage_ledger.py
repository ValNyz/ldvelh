"""Usage ledger: each call gets its own cost, priced on its own provider (#18, #65)."""

from llm.usage import UsageLedger, call_cost, is_unpriced
from services import pricing
from services.llm_providers import LLMUsage


def _price(monkeypatch, provider, model, inp, out):
    monkeypatch.setitem(pricing._DYNAMIC_PRICING, f"{provider}/{model}",
                        pricing.ModelPricing(input=inp, output=out))


def test_record_returns_this_call_cost(monkeypatch):
    _price(monkeypatch, "mistral", "m-large", 2.0, 6.0)
    ledger = UsageLedger()
    snap = ledger.record("narration", "mistral", "m-large", LLMUsage(input_tokens=1000, output_tokens=100))
    assert snap["cost_usd"] == round(1000 * 2.0 / 1e6 + 100 * 6.0 / 1e6, 6)
    assert (snap["provider"], snap["model"]) == ("mistral", "m-large")


def test_call_cost_matches_record(monkeypatch):
    _price(monkeypatch, "anthropic", "claude-x", 3.0, 15.0)
    usage = LLMUsage(input_tokens=100, output_tokens=50)
    assert UsageLedger().record("director", "anthropic", "claude-x", usage)["cost_usd"] == round(
        call_cost(usage, "anthropic", "claude-x"), 6)


def test_is_unpriced_when_every_rate_is_zero(monkeypatch):
    _price(monkeypatch, "mistral", "m-large", 2.0, 6.0)
    assert is_unpriced("mistral", "m-large") is False
    assert is_unpriced("scripted", "no-such-model") is True
