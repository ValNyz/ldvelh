"""LLMSession: per-purpose provider/model, explicit per-call cost, structured dispatch."""

import asyncio
import logging
from uuid import uuid4

import pytest

from llm.call_log import CallLog
from llm.session import LLMCall, LLMSession, Purpose
from llm.usage import UsageLedger
from tests.helpers import RecordingLedger
from services.llm_providers import (
    CompletionResult, LLMProvider, LLMUsage, StructuredOutputMode, ToolResult,
)

USER = uuid4()


class FakeProvider(LLMProvider):
    MODEL_MAIN = "fake-main"
    STRUCTURED_OUTPUT = StructuredOutputMode.TOOL_USE

    def __init__(self, text='{"ok": true}', usage=None, fail=None, mode=None, cache=False):
        self.text, self.usage, self.fail, self._cache = text, usage or LLMUsage(10, 5), fail, cache
        if mode:
            self.STRUCTURED_OUTPUT = mode
        self.calls = []

    async def stream(self, system_prompt, messages, temperature, max_tokens):
        self.calls.append("stream")
        yield self.text[:3]
        if self.fail:
            raise self.fail
        yield self.text[3:]
        yield self.usage

    async def complete(self, system_prompt, messages, temperature, max_tokens):
        self.calls.append("complete")
        if self.fail:
            raise self.fail
        return CompletionResult(content=self.text, usage=self.usage)

    async def complete_with_tools(self, system_prompt, messages, tools, tool_choice, temperature, max_tokens):
        self.calls.append("tools")
        return ToolResult(tool_name=tools[0]["name"], tool_input={"tool": True}, usage=self.usage)

    @property
    def supports_cache_control(self):
        return self._cache

    @property
    def provider_name(self):
        return "fake"


async def test_complete_json_returns_value_and_its_own_cost():
    ledger = RecordingLedger()
    call = await LLMSession.from_provider(FakeProvider(), ledger).complete_json(
        Purpose.MECHANICAL, "sys", "user", 0.2, 500)
    assert call.value == {"ok": True}
    assert call.cost["input_tokens"] == 10 and call.cost["provider"] == "fake"
    assert ledger.purposes == ["mechanical"]


async def test_failed_call_has_no_cost():
    call = await LLMSession.from_provider(FakeProvider(fail=RuntimeError("down"))).complete_json(
        Purpose.IDENTITY, "sys", "user", 0.3, 100)
    assert call == LLMCall(value=None, cost=None)


async def test_concurrent_calls_keep_their_own_cost():
    ledger = UsageLedger()

    async def one(tokens):
        session = LLMSession.from_provider(FakeProvider(usage=LLMUsage(tokens, 0)), ledger)
        return await session.extract_structured("sys", "user", "t", "d", {}, 0.3, 100)

    calls = await asyncio.gather(one(100), one(200), one(300))
    assert [c.cost["input_tokens"] for c in calls] == [100, 200, 300]


async def test_stream_yields_text_then_exposes_cost():
    stream = LLMSession.from_provider(FakeProvider(text="abcdef")).stream(
        Purpose.NARRATION, "sys", [], 0.7, 100)
    assert [x async for x in stream] == ["abc", "def"]
    assert stream.cost["output_tokens"] == 5


async def test_stream_failure_records_nothing():
    ledger = RecordingLedger()
    stream = LLMSession.from_provider(FakeProvider(fail=RuntimeError("down")), ledger).stream(
        Purpose.NARRATION, "sys", [], 0.7, 100)
    with pytest.raises(RuntimeError):
        async for _ in stream:
            pass
    assert stream.cost is None and ledger.purposes == []


@pytest.mark.parametrize("mode,expected_call", [
    (StructuredOutputMode.TOOL_USE, "tools"),
    (StructuredOutputMode.TEXT, "complete"),
])
async def test_extract_structured_dispatches_on_mode(mode, expected_call):
    provider = FakeProvider(mode=mode)
    await LLMSession.from_provider(provider).extract_structured("sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == [expected_call]


async def test_json_schema_without_support_falls_back_to_text():
    provider = FakeProvider(mode=StructuredOutputMode.JSON_SCHEMA)
    call = await LLMSession.from_provider(provider).extract_structured("sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == ["complete"] and call.value == {"ok": True}


def test_caps_come_from_the_narration_provider():
    caps = LLMSession.from_provider(FakeProvider(cache=True)).caps
    assert caps.cache_control is True and caps.structured_output == StructuredOutputMode.TOOL_USE


def test_model_per_purpose_matches_before_p2():
    session = LLMSession("anthropic", api_key="k", user_model="claude-sonnet-5-5", user_id=USER)
    assert session.model_for(Purpose.NARRATION) == "claude-sonnet-5-5"
    assert session.model_for(Purpose.MECHANICAL) == "claude-haiku-5-5"
    assert session.model_for(Purpose.IDENTITY) == "claude-sonnet-5-5"  # provider default
    mistral = LLMSession("mistral", api_key="k", user_model="mistral-small-latest", user_id=USER)
    assert mistral.model_for(Purpose.MECHANICAL) == "mistral-small-latest"
    assert mistral.model_for(Purpose.DIRECTOR) == "mistral-large-latest"  # provider default


def test_a_request_session_belongs_to_a_user():
    # Usage is attributed to the account (#78): only from_provider (tests) has no user.
    with pytest.raises(TypeError):
        LLMSession("anthropic", api_key="k")
    assert LLMSession("anthropic", api_key="k", user_id=USER).user_id == USER
    assert LLMSession.from_provider(FakeProvider()).user_id is None


def test_session_has_no_request_lifecycle():
    # Background tasks keep using the session after the SSE response ends:
    # it must not own or close clients.
    session = LLMSession("anthropic", api_key="k", user_id=USER)
    assert not hasattr(session, "close") and not hasattr(session, "__aexit__")


class _ToolFailsProvider(FakeProvider):
    def __init__(self, error, **kw):
        super().__init__(**kw)
        self.error = error

    async def complete_with_tools(self, *a, **kw):
        self.calls.append("tools")
        raise self.error


@pytest.mark.parametrize("error", [NotImplementedError("no tool_use"), RuntimeError("API error")])
async def test_tool_use_failure_falls_back_to_text(error):
    provider = _ToolFailsProvider(error, text='{"facts": []}')
    ledger = UsageLedger()
    call = await LLMSession.from_provider(provider, ledger).extract_structured(
        "sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == ["tools", "complete"]
    assert call.value == {"facts": []} and call.cost["input_tokens"] == 10


class _SchemaProvider(FakeProvider):
    STRUCTURED_OUTPUT = StructuredOutputMode.JSON_SCHEMA

    def __init__(self, schema_text, **kw):
        super().__init__(**kw)
        self.schema_text = schema_text

    async def complete_with_schema(self, system_prompt, messages, schema_name, schema,
                                   temperature, max_tokens):
        self.calls.append("schema")
        return CompletionResult(content=self.schema_text, usage=self.usage)


async def test_json_schema_success_returns_value_and_cost():
    ledger = RecordingLedger()
    provider = _SchemaProvider('{"facts": [1]}')
    call = await LLMSession.from_provider(provider, ledger).extract_structured(
        "sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == ["schema"]
    assert call.value == {"facts": [1]} and call.cost["input_tokens"] == 10
    assert ledger.purposes == ["extraction"]


async def test_json_schema_invalid_json_is_still_recorded_then_text_fallback():
    ledger = RecordingLedger()
    provider = _SchemaProvider("not json", text='{"ok": true}')
    call = await LLMSession.from_provider(provider, ledger).extract_structured(
        "sys", "user", "t", "d", {}, 0.3, 100)
    assert provider.calls == ["schema", "complete"]
    assert call.value == {"ok": True}
    assert ledger.purposes == ["extraction", "extraction"]


class _SurrogateProvider(FakeProvider):
    """Structured payloads carrying a model-written lone surrogate (#90)."""

    async def complete_with_tools(self, system_prompt, messages, tools, tool_choice, temperature, max_tokens):
        return ToolResult(tool_name="t", tool_input={"t": "x\ud83d", "n": ["\ude00"]}, usage=self.usage)

    async def complete_with_schema(self, system_prompt, messages, schema_name, schema, temperature, max_tokens):
        return CompletionResult(content='{"t": "x\\ud83d", "n": ["\\ude00"]}', usage=self.usage)


@pytest.mark.parametrize("mode", [StructuredOutputMode.TOOL_USE, StructuredOutputMode.JSON_SCHEMA])
async def test_structured_extraction_replaces_lone_surrogates(mode):
    session = LLMSession.from_provider(_SurrogateProvider(mode=mode))
    call = await session.extract_structured("sys", "user", "t", "d", {}, 0.3, 100)
    assert call.value == {"t": "x�", "n": ["�"]}


async def test_text_extraction_replaces_lone_surrogates():
    provider = _SurrogateProvider(text='{"t": "x\\ud83d"}', mode=StructuredOutputMode.TEXT)
    call = await LLMSession.from_provider(provider).extract_structured("sys", "user", "t", "d", {}, 0.3, 100)
    assert call.value == {"t": "x�"}


class _CapturingPool:
    """Pool whose connection records each llm_calls insert: (rows) per execute."""

    def __init__(self, fail: Exception | None = None):
        self.inserts: list[list[dict]] = []
        self.acquired = 0
        self.fail = fail
        pool = self

        class _Conn:
            async def execute(self, sql, *columns):
                assert "INSERT INTO llm_calls" in sql
                fields = ("turn_id", "game_id", "user_id", "purpose", "provider", "model",
                          "usage", "cost_usd", "cost_unknown", "created_at")
                pool.inserts.append([dict(zip(fields, row)) for row in zip(*columns)])

        self._conn = _Conn()

    def acquire(self, timeout=None):
        self.acquired += 1
        if self.fail:
            raise self.fail
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool._conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _logged_session(pool, provider=None) -> LLMSession:
    session = LLMSession.from_provider(provider or FakeProvider())
    session.calls = CallLog(pool, game_id=GAME, user_id=USER)
    return session


GAME = uuid4()


async def test_calls_are_buffered_until_the_phase_flushes():
    pool = _CapturingPool()
    session = _logged_session(pool)
    await session.complete_json(Purpose.MECHANICAL, "sys", "user", 0.2, 100)
    await session.complete_json(Purpose.IDENTITY, "sys", "user", 0.3, 100)
    assert pool.acquired == 0 and session.calls.pending == 2  # no pool access per call
    await session.flush_calls()
    await session.flush_calls()  # nothing left: no second insert
    assert pool.acquired == 1 and len(pool.inserts) == 1
    assert [(r["purpose"], r["provider"], r["model"]) for r in pool.inserts[0]] == [
        ("mechanical", "fake", "fake-main"), ("identity", "fake", "fake-main")]
    row = pool.inserts[0][0]
    assert (row["game_id"], row["user_id"], row["turn_id"]) == (GAME, USER, None)
    assert row["usage"] == {"input_tokens": 10, "output_tokens": 5,
                            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    assert row["cost_usd"] == 0 and row["cost_unknown"] is True
    # Stamped at call time, in order.
    stamps = [r["created_at"] for r in pool.inserts[0]]
    assert stamps == sorted(stamps) and stamps[0].tzinfo is not None


async def test_each_row_carries_the_turn_bound_when_its_call_was_made():
    pool = _CapturingPool()
    session = _logged_session(pool)
    await session.complete_json(Purpose.WORLD_GEN, "sys", "user", 1.0, 100)
    turn_id = uuid4()
    session.bind_turn(turn_id)
    await session.complete_json(Purpose.NARRATION, "sys", "user", 0.7, 100)
    await session.flush_calls()
    assert [(r["purpose"], r["turn_id"]) for r in pool.inserts[0]] == [
        ("world_gen", None), ("narration", turn_id)]


async def test_a_background_session_keeps_the_turn_with_its_own_buffer():
    pool = _CapturingPool()
    session = _logged_session(pool)
    turn_id = uuid4()
    session.bind_turn(turn_id)
    await session.complete_json(Purpose.NARRATION, "sys", "user", 0.7, 100)
    job = session.for_background()
    await job.complete_json(Purpose.IDENTITY, "sys", "user", 0.3, 100)
    assert (session.calls.pending, job.calls.pending) == (1, 1)
    await job.flush_calls()
    await session.flush_calls()
    assert [[(r["purpose"], r["turn_id"]) for r in rows] for rows in pool.inserts] == [
        [("identity", turn_id)], [("narration", turn_id)]]


async def test_a_session_without_pool_buffers_nothing():
    session = LLMSession.from_provider(FakeProvider())
    call = await session.complete_json(Purpose.IDENTITY, "sys", "user", 0.3, 100)
    assert call.cost["input_tokens"] == 10
    assert session.calls.pending == 0
    await session.flush_calls()  # no pool: a no-op


async def test_flush_failure_is_logged_not_raised_and_not_retried(caplog):
    pool = _CapturingPool(fail=ConnectionError("pool closed"))
    session = _logged_session(pool)
    call = await session.complete_json(Purpose.IDENTITY, "sys", "user", 0.3, 100)
    with caplog.at_level(logging.ERROR, logger="llm.call_log"):
        await session.flush_calls()
        await session.flush_calls()
    assert call.cost["input_tokens"] == 10  # the caller still got its cost
    assert pool.acquired == 1 and session.calls.pending == 0  # dropped, never inserted twice
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == ["[COST] llm_calls insert failed rows=1"]
