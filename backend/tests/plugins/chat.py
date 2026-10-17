"""Chat fixtures: scripted LLM in every provider slot, HTTP harness, prepared games."""

import random

import pytest
import pytest_asyncio

from services import llm_providers
from services.llm_providers import StructuredOutputMode
from tests.characterization import payloads
from tests.characterization.harness import ChatHarness
from tests.characterization.scripted_llm import ScriptedLLMProvider, make_provider_class

DEFAULT_RESPONSES = {
    "world_gen": payloads.WORLD_GEN,
    "narration": payloads.NARRATION,
    "mechanical": payloads.mechanical(requires_test=False),
    "resolver": payloads.RESOLVER_EMPTY,
    "director": payloads.DIRECTOR,
}


@pytest.fixture
def llm_mode():
    """Override via parametrize to run a scenario under another structured-output mode."""
    return StructuredOutputMode.TOOL_USE


@pytest.fixture
def scripted_llm(monkeypatch, llm_mode):
    provider = ScriptedLLMProvider(dict(DEFAULT_RESPONSES), mode=llm_mode)
    factory = make_provider_class(provider)
    for name in list(llm_providers._CLASSES):
        monkeypatch.setitem(llm_providers._CLASSES, name, factory)
    monkeypatch.setattr(llm_providers, "_providers", {})

    async def _fake_key(pool, user_id, provider_name):
        return "test-api-key"

    from api import routes
    monkeypatch.setattr(routes, "_resolve_user_api_key", _fake_key)
    return provider


@pytest.fixture
def seeded_random():
    """Deterministic dice; global random state restored on teardown."""
    state = random.getstate()
    random.seed(1234)
    yield
    random.setstate(state)


@pytest.fixture
def no_api_key(monkeypatch):
    """Make the API-key lookup return None (no user key, no server key)."""
    from api import routes

    async def _no_key(pool, user_id, provider_name):
        return None

    monkeypatch.setattr(routes, "_resolve_user_api_key", _no_key)


@pytest_asyncio.fixture
async def harness(client, test_pool, test_user, seeded_genres, scripted_llm):
    return ChatHarness(client, test_pool, test_user["token"], scripted_llm)


@pytest_asyncio.fixture
async def world_game(harness):
    """Game (engine none) with world generated and arrival played; LLM call log reset."""
    game_id = await harness.create_game("none")
    await harness.init_world(game_id)
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    harness.llm.calls.clear()
    return game_id


@pytest_asyncio.fixture
async def fate_game(harness):
    """Fate game with world generated and arrival played; LLM call log reset."""
    game_id = await harness.create_game("fate_core")
    await harness.init_world(game_id, engine="fate_core",
                             character_data=payloads.CHARACTER_DATA["fate_core"])
    await harness.chat(game_id, "__ARRIVEE__")
    await harness.drain()
    harness.llm.calls.clear()
    return game_id
