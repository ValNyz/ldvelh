"""SDK clients are shared per (provider, key); models stay per instance (#42)."""

import hashlib

import pytest

from services import llm_providers
from services.llm_providers import get_provider


@pytest.fixture(autouse=True)
def _empty_cache(monkeypatch):
    monkeypatch.setattr(llm_providers, "_client_cache", llm_providers.OrderedDict(), raising=False)


def test_same_key_shares_the_client():
    a = get_provider("anthropic", api_key="k1")
    b = get_provider("anthropic", api_key="k1")
    assert a is not b
    assert a.client is b.client


def test_different_keys_get_different_clients():
    assert get_provider("mistral", api_key="k1").client is not get_provider("mistral", api_key="k2").client


def test_raw_key_is_never_a_cache_key():
    get_provider("nebius", api_key="secret-key")
    keys = list(llm_providers._client_cache)
    assert all("secret-key" not in str(k) for k in keys)
    assert ("nebius", hashlib.sha256(b"secret-key").hexdigest()) in keys


def test_shared_client_keeps_models_apart():
    sonnet = get_provider("anthropic", api_key="k1", model="claude-sonnet-4-6")
    haiku = get_provider("anthropic", api_key="k1", model="claude-haiku-4-5")
    assert sonnet.client is haiku.client
    assert (sonnet.MODEL_MAIN, haiku.MODEL_MAIN) == ("claude-sonnet-4-6", "claude-haiku-4-5")


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(llm_providers, "CLIENT_CACHE_SIZE", 2, raising=False)
    for i in range(3):
        get_provider("wandb", api_key=f"k{i}")
    assert len(llm_providers._client_cache) == 2


async def test_close_shared_clients_closes_and_empties():
    closed = []

    class FakeClient:
        async def close(self):
            closed.append(self)

    llm_providers.shared_client("anthropic", "k", FakeClient)
    await llm_providers.close_shared_clients()
    assert len(closed) == 1 and not llm_providers._client_cache


async def test_close_shared_clients_falls_back_to_aexit():
    exited = []

    class AexitOnlyClient:  # e.g. the Mistral SDK client
        async def __aexit__(self, *exc):
            exited.append(exc)

    llm_providers.shared_client("mistral", "k", AexitOnlyClient)
    await llm_providers.close_shared_clients()
    assert exited == [(None, None, None)] and not llm_providers._client_cache
