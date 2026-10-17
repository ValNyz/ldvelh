"""The narration cost shown to the player is its own, even if another call lands meanwhile (#18)."""

from llm.session import LLMSession, Purpose
from llm.usage import UsageLedger
from pipeline.narration_stream import stream_narration
from services.llm_providers import LLMUsage
from tests.test_llm_session import FakeProvider


class _NullSink:
    async def send_chunk(self, content):
        return None


async def test_narration_cost_is_not_overwritten_by_an_interleaved_call():
    ledger = UsageLedger()
    narration = LLMSession.from_provider(
        FakeProvider(text='{"narrative_text": "Bonjour."}', usage=LLMUsage(1000, 100)), ledger)
    other = LLMSession.from_provider(FakeProvider(usage=LLMUsage(7, 7)), ledger)

    result = await stream_narration(
        narration, _NullSink(), system_prompt="sys",
        messages=[{"role": "user", "content": "x"}], world_gen=False,
    )
    # A background extraction finishes between the narration record and the read.
    await other.complete_json(Purpose.EXTRACTION, "sys", "user", 0.3, 100)
    assert result.cost["input_tokens"] == 1000

from services.llm_providers import ToolResult


class PerToolUsageProvider(FakeProvider):
    """Each tool reports a different usage, and the calls finish out of order."""

    USAGE = {"extract_characters": 111, "extract_locations": 222, "extract_organizations": 333}
    DELAY = {"extract_characters": 0.03, "extract_locations": 0.01, "extract_organizations": 0.02}

    async def complete_with_tools(self, system_prompt, messages, tools, tool_choice, temperature, max_tokens):
        import asyncio
        name = tools[0]["name"]
        await asyncio.sleep(self.DELAY[name])
        # Non-empty payload: an empty one is reported as "empty_response" without a cost.
        return ToolResult(tool_name=name, tool_input={"noop": True}, usage=LLMUsage(self.USAGE[name], 0))


async def test_three_parallel_extractors_bill_exactly(test_pool, test_user):
    import asyncio
    from services.extraction.orchestrator import EXTRACTOR_MAP
    from services.game_service import GameService

    game_id = await GameService(test_pool).create_game(test_user["id"])
    session = LLMSession.from_provider(PerToolUsageProvider(), UsageLedger())
    names = ["characters", "locations", "organizations"]
    results = await asyncio.gather(*[
        EXTRACTOR_MAP[n](test_pool, game_id, session).run("Texte.", {}, 1) for n in names
    ])
    assert [r["cost"]["input_tokens"] for r in results] == [111, 222, 333]


async def test_failed_resolver_returns_no_cost(test_pool, test_user):
    from services.extraction.resolver import resolve_entities
    from services.game_service import GameService
    game_id = await GameService(test_pool).create_game(test_user["id"])
    session = LLMSession.from_provider(FakeProvider(fail=RuntimeError("down")))
    resolution, cost = await resolve_entities(test_pool, game_id, "Avant.", [], "Après.", session)
    assert resolution is None and cost is None
