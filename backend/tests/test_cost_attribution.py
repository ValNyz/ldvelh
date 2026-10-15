"""The narration cost shown to the player is its own, even if another call lands meanwhile (#18)."""

from api.streaming import SSEWriter
from llm.session import LLMSession, Purpose
from llm.usage import UsageLedger
from services.llm_providers import LLMUsage
from services.llm_service import LLMService
from tests.test_llm_session import FakeProvider


class _NullWriter(SSEWriter):
    def __init__(self):
        pass

    async def send(self, *args, **kwargs):
        return None


async def test_narration_cost_is_not_overwritten_by_an_interleaved_call():
    ledger = UsageLedger()
    narration = LLMSession.from_provider(
        FakeProvider(text='{"narrative_text": "Bonjour."}', usage=LLMUsage(1000, 100)), ledger)
    other = LLMSession.from_provider(FakeProvider(usage=LLMUsage(7, 7)), ledger)
    seen = {}

    async def on_complete(parsed, display_text, raw_json, cost):
        # A background extraction finishes between the narration record and the read.
        await other.complete_json(Purpose.EXTRACTION, "sys", "user", 0.3, 100)
        seen["cost"] = cost

    await LLMService().stream_narration(
        narration, "sys", [{"role": "user", "content": "x"}], _NullWriter(),
        on_complete=on_complete,
    )
    assert seen["cost"]["input_tokens"] == 1000
