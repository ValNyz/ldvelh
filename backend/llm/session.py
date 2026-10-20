"""One LLM session per /chat request (#10, #18, #42).

It picks the provider instance and model for each purpose, exposes the
provider capabilities, and returns the cost of every call to its caller.
Given a pool, it also logs every call in llm_calls under its game and turn: rows are
buffered (llm/call_log.py) and flushed once per phase by its owner (#106).
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

import asyncpg

from llm.call_log import CallLog
from llm.usage import UsageLedger, get_usage_ledger, is_unpriced
from services.llm_providers import (
    LLMProvider,
    LLMUsage,
    StructuredOutputMode,
    _CLASSES,
    get_provider,
)
from repos.llm_models import (
    IDENTITY_ROLE,
    IDENTITY_STRONG_ROLE,
    MECHANICAL_ROLE,
    NARRATION_ROLE,
    ModelCatalog,
)
from utils import parse_json_response, replace_lone_surrogates
from utils.log_safe import safe_repr, safe_text

logger = logging.getLogger(__name__)


class Purpose(str, Enum):
    NARRATION = "narration"
    WORLD_GEN = "world_gen"
    MECHANICAL = "mechanical"
    IDENTITY = "identity"
    IDENTITY_STRONG = "identity_strong"
    EXTRACTION = "extraction"
    DIRECTOR = "director"
    SUMMARY = "summary"


# Purposes with a catalog role of their own (no holder: the narration default).
_CATALOG_ROLES = {
    Purpose.IDENTITY: IDENTITY_ROLE,
    Purpose.IDENTITY_STRONG: IDENTITY_STRONG_ROLE,
}


@dataclass(frozen=True)
class Caps:
    cache_control: bool
    structured_output: StructuredOutputMode


@dataclass(frozen=True)
class LLMCall:
    value: Any  # parsed JSON, text, or None when the call failed
    cost: dict | None  # this call's ledger snapshot; None when nothing was billed


class UsageRecordingFailed(Exception):
    """The usage ledger failed after a stream ended: our bug, not a provider failure."""


class StreamCall:
    """Async iterator of text deltas; usage and cost are set once it is exhausted."""

    def __init__(self, session: "LLMSession", purpose: Purpose, system_prompt: str,
                 messages: list[dict], temperature: float, max_tokens: int):
        self._session = session
        self._purpose = purpose
        self._args = dict(system_prompt=system_prompt, messages=messages,
                          temperature=temperature, max_tokens=max_tokens)
        self.usage: LLMUsage | None = None
        self.cost: dict | None = None

    def __aiter__(self):
        return self._run()

    async def _run(self):
        provider = self._session.provider_for(self._purpose)
        async for item in provider.stream(**self._args):
            if isinstance(item, LLMUsage):
                self.usage = item
                continue
            yield item
        if self.usage is not None:
            try:
                self.cost = self._session._record(self._purpose, provider, self.usage)
            except Exception as e:
                raise UsageRecordingFailed("usage ledger failed") from e


class LLMSession:
    """Provider, models and usage for one game request. Holds no request resources.

    One session per request, hence per turn. The turn's background job (extraction, hooks,
    Director) gets `for_background()`: same turn, its own call buffer, flushed by the job.
    """

    def __init__(self, provider_name: str, api_key: str | None,
                 user_model: str | None = None, ledger: UsageLedger | None = None,
                 catalog: ModelCatalog | None = None, *, user_id: UUID,
                 pool: asyncpg.Pool | None = None, game_id: UUID | None = None):
        # A request session is always a user's: its usage is attributed to the account.
        self._setup(provider_name, api_key, user_model, ledger, catalog, user_id,
                    pool=pool, game_id=game_id)

    def _setup(self, provider_name: str, api_key: str | None, user_model: str | None,
               ledger: UsageLedger | None, catalog: ModelCatalog | None,
               user_id: UUID | None, pool: asyncpg.Pool | None = None,
               game_id: UUID | None = None) -> None:
        self.user_id = user_id  # None only for from_provider() sessions (tests)
        # Call log (#106): no pool, nothing logged (from_provider() sessions, tests).
        self.calls = CallLog(pool, game_id=game_id, user_id=user_id)
        self.catalog = catalog
        self.provider_name = provider_name
        self._api_key = api_key
        self.user_model = user_model
        self.ledger = ledger or get_usage_ledger()
        self._providers: dict[Purpose, LLMProvider] = {}

    @classmethod
    def from_provider(cls, provider: LLMProvider, ledger: UsageLedger | None = None) -> "LLMSession":
        """Session that uses one given provider instance for every purpose (tests).

        Not a user's request: its usage is recorded without a user.
        """
        session = cls.__new__(cls)
        session._setup(provider.provider_name, api_key=None, user_model=None, ledger=ledger,
                       catalog=None, user_id=None)
        session._providers = {purpose: provider for purpose in Purpose}
        return session

    @classmethod
    def from_providers(cls, default: LLMProvider, by_purpose: dict[Purpose, LLMProvider],
                       ledger: UsageLedger | None = None) -> "LLMSession":
        """`from_provider(default)`, with its own provider instance for the purposes of
        `by_purpose` (an evaluation that taps the identity calls per model)."""
        session = cls.from_provider(default, ledger)
        session._providers.update(by_purpose)
        return session

    # -- model selection (unchanged from before P2, see the plan) -------------

    def _catalog_active(self) -> bool:
        return self.catalog is not None and bool(self.catalog.enabled(self.provider_name))

    def _model_argument(self, purpose: Purpose) -> str | None:
        cat, name = self.catalog, self.provider_name
        user_model = self.user_model
        if self._catalog_active():
            # Never pass through a user model the catalog does not have enabled.
            entry = cat.entry(name, user_model) if user_model else None
            if entry is None or entry.status != "enabled":
                user_model = None
            if purpose in (Purpose.NARRATION, Purpose.WORLD_GEN):
                return user_model or cat.default_model(name, NARRATION_ROLE)
            if purpose in _CATALOG_ROLES:
                # The identity resolver's own models (Haiku, Sonnet), else the narration one.
                return (cat.default_model(name, _CATALOG_ROLES[purpose])
                        or cat.default_model(name, NARRATION_ROLE))
            if purpose is Purpose.MECHANICAL:
                chosen = cat.default_model(name, MECHANICAL_ROLE)
                if chosen:
                    return chosen
                return get_provider(name, api_key=self._api_key,
                                    model=user_model).model_name("mechanical")
            # Other purposes: the provider default, explicit so its catalog
            # profile applies; a non-enabled default gives way to the narration default.
            main = _CLASSES[name].MODEL_MAIN
            main_entry = cat.entry(name, main)
            if main_entry is not None and main_entry.status == "enabled":
                return main
            return cat.default_model(name, NARRATION_ROLE)
        if purpose in (Purpose.NARRATION, Purpose.WORLD_GEN):
            return self.user_model
        if purpose is Purpose.MECHANICAL:
            # The user's model picks the tier; the provider maps it to its
            # mechanical model (Haiku on Anthropic, the same model elsewhere).
            return get_provider(self.provider_name, api_key=self._api_key,
                                model=self.user_model).model_name("mechanical")
        return None  # identity, extraction, director, summary: provider default

    def provider_for(self, purpose: Purpose) -> LLMProvider:
        if purpose not in self._providers:
            model = self._model_argument(purpose)
            profile = None
            if self._catalog_active() and model:
                profile = self.catalog.profile(self.provider_name, model)
            self._providers[purpose] = get_provider(
                self.provider_name, api_key=self._api_key, model=model, profile=profile,
            )
        return self._providers[purpose]

    def model_for(self, purpose: Purpose) -> str:
        return self.provider_for(purpose).model_name(purpose.value)

    @property
    def caps(self) -> Caps:
        provider = self.provider_for(Purpose.NARRATION)
        return Caps(provider.supports_cache_control, provider.structured_output_mode)

    def bind_turn(self, turn_id: UUID | None) -> None:
        """Log the calls made from now on under `turn_id` (set once the turn opens; calls
        before it, world generation and the initial Director, have no turn)."""
        self.calls.turn_id = turn_id

    def for_background(self) -> LLMSession:
        """This session for a background job: same providers and turn, its own call buffer
        (the job flushes it, the request flushes its own)."""
        job = copy.copy(self)
        job.calls = self.calls.fork()
        return job

    async def flush_calls(self) -> None:
        """Write this phase's buffered call rows (one insert); never raises."""
        await self.calls.flush()

    def _record(self, purpose: Purpose, provider: LLMProvider, usage: LLMUsage) -> dict:
        """This call's cost, buffered for the call log. No pool access here: the owner of
        the phase flushes, and must hold no pool connection across a call (#94, #96)."""
        provider_name, model = provider.provider_name, provider.model_name(purpose.value)
        cost = self.ledger.record(purpose.value, provider_name, model, usage)
        self.calls.add(
            purpose=purpose.value, provider=provider_name, model=model,
            usage={k: cost[k] for k in ("input_tokens", "output_tokens",
                                        "cache_creation_input_tokens",
                                        "cache_read_input_tokens")},
            cost_usd=cost["cost_usd"], cost_unknown=is_unpriced(provider_name, model),
        )
        return cost

    # -- calls ----------------------------------------------------------------

    def stream(self, purpose: Purpose, system_prompt: str, messages: list[dict],
               temperature: float, max_tokens: int) -> StreamCall:
        return StreamCall(self, purpose, system_prompt, messages, temperature, max_tokens)

    async def complete_text(self, purpose: Purpose, system_prompt: str, messages: list[dict],
                            temperature: float, max_tokens: int) -> LLMCall:
        """Plain completion; provider errors propagate to the caller."""
        provider = self.provider_for(purpose)
        result = await provider.complete(system_prompt=system_prompt, messages=messages,
                                         temperature=temperature, max_tokens=max_tokens)
        return LLMCall(result.content, self._record(purpose, provider, result.usage))

    async def complete_json(self, purpose: Purpose, system_prompt: str, user_message: str,
                            temperature: float, max_tokens: int) -> LLMCall:
        """JSON-in-text call; a provider error gives LLMCall(None, None)."""
        provider = self.provider_for(purpose)
        try:
            result = await provider.complete(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                temperature=temperature, max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"[LLM] {purpose.value} call failed ({self.provider_name}): {safe_text(e)}")
            return LLMCall(None, None)
        cost = self._record(purpose, provider, result.usage)
        return LLMCall(parse_json_response(result.content), cost)

    async def extract_structured(self, system_prompt: str, user_message: str, tool_name: str,
                                 tool_description: str, schema: dict, temperature: float,
                                 max_tokens: int, *,
                                 purpose: Purpose = Purpose.EXTRACTION,
                                 text_fallback: bool = True) -> LLMCall:
        """Structured extraction dispatched on the provider's mode, with a text fallback.

        `text_fallback=False`: no plain-text retry when the structured call fails; the
        failure reaches the caller, and a JSON_SCHEMA answer comes back as its raw text
        (billed even if unparsable, the caller parses it)."""
        provider = self.provider_for(purpose)
        messages = [{"role": "user", "content": user_message}]
        mode = provider.structured_output_mode
        try:
            if mode == StructuredOutputMode.TOOL_USE:
                result = await provider.complete_with_tools(
                    system_prompt=system_prompt, messages=messages,
                    tools=[{"name": tool_name, "description": tool_description,
                            "input_schema": schema}],
                    tool_choice={"type": "tool", "name": tool_name},
                    temperature=temperature, max_tokens=max_tokens,
                )
                cost = self._record(purpose, provider, result.usage)
                return LLMCall(replace_lone_surrogates(result.tool_input), cost)
            if mode == StructuredOutputMode.JSON_SCHEMA:
                result = await provider.complete_with_schema(
                    system_prompt=system_prompt, messages=messages,
                    schema_name=tool_name, schema=schema,
                    temperature=temperature, max_tokens=max_tokens,
                )
                cost = self._record(purpose, provider, result.usage)  # billed even if unparsable
                if not text_fallback:
                    return LLMCall(result.content, cost)
                return LLMCall(replace_lone_surrogates(json.loads(result.content)), cost)
        except NotImplementedError:
            if not text_fallback:
                raise
            logger.info(f"[LLM] {self.provider_name} has no {mode.value} support, using text")
        except Exception as e:
            if not text_fallback:
                raise
            logger.warning(f"[LLM] {mode.value} extraction failed: {safe_repr(e)}, falling back to text")
        return await self.complete_json(purpose, system_prompt, user_message,
                                        temperature, max_tokens)
