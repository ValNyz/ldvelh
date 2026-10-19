"""One LLM session per /chat request (#10, #18, #42).

It picks the provider instance and model for each purpose, exposes the
provider capabilities, and returns the cost of every call to its caller.
Given a pool, it also logs every call in llm_calls under its game and turn (#106).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

import asyncpg

from llm.usage import UsageLedger, get_usage_ledger, is_unpriced
from repos import llm_calls
from services.llm_providers import (
    LLMProvider,
    LLMUsage,
    StructuredOutputMode,
    _CLASSES,
    get_provider,
)
from repos.llm_models import ModelCatalog
from utils import parse_json_response, replace_lone_surrogates
from utils.log_safe import log_exception, safe_repr, safe_text

logger = logging.getLogger(__name__)


class Purpose(str, Enum):
    NARRATION = "narration"
    WORLD_GEN = "world_gen"
    MECHANICAL = "mechanical"
    RESOLVER = "resolver"
    EXTRACTION = "extraction"
    DIRECTOR = "director"
    SUMMARY = "summary"


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
                self.cost = await self._session._record(self._purpose, provider, self.usage)
            except Exception as e:
                raise UsageRecordingFailed("usage ledger failed") from e


class LLMSession:
    """Provider, models and usage for one game request. Holds no request resources.

    One session per request, hence per turn: the background jobs of the turn (extraction,
    hooks, Director) receive this same session, so they log their calls under its turn.
    """

    def __init__(self, provider_name: str, api_key: str | None,
                 user_model: str | None = None, ledger: UsageLedger | None = None,
                 catalog: ModelCatalog | None = None, *, user_id: UUID,
                 pool: asyncpg.Pool | None = None, game_id: UUID | None = None):
        # A request session is always a user's: its usage is attributed to the account.
        self._setup(provider_name, api_key, user_model, ledger, catalog, user_id)
        self.pool = pool
        self.game_id = game_id

    def _setup(self, provider_name: str, api_key: str | None, user_model: str | None,
               ledger: UsageLedger | None, catalog: ModelCatalog | None,
               user_id: UUID | None) -> None:
        self.user_id = user_id  # None only for from_provider() sessions (tests)
        # Call log (#106): no pool, nothing logged (from_provider() sessions, tests).
        self.pool: asyncpg.Pool | None = None
        self.game_id: UUID | None = None
        self.turn_id: UUID | None = None  # None before the turn opens: world generation
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
                return user_model or cat.default_model(name, "narration")
            if purpose is Purpose.MECHANICAL:
                chosen = cat.default_model(name, "mechanical")
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
            return cat.default_model(name, "narration")
        if purpose in (Purpose.NARRATION, Purpose.WORLD_GEN):
            return self.user_model
        if purpose is Purpose.MECHANICAL:
            # The user's model picks the tier; the provider maps it to its
            # mechanical model (Haiku on Anthropic, the same model elsewhere).
            return get_provider(self.provider_name, api_key=self._api_key,
                                model=self.user_model).model_name("mechanical")
        return None  # resolver, extraction, director, summary: provider default

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
        """Log the calls made from now on under `turn_id` (set once the turn opens)."""
        self.turn_id = turn_id

    async def _record(self, purpose: Purpose, provider: LLMProvider, usage: LLMUsage) -> dict:
        """This call's cost; logged in llm_calls when the session has a pool.

        The insert runs on its own connection, outside any turn transaction; its failure is
        logged, never raised: the narration does not fail for a counter."""
        provider_name, model = provider.provider_name, provider.model_name(purpose.value)
        cost = self.ledger.record(purpose.value, provider_name, model, usage)
        if self.pool is None:
            return cost
        try:
            async with self.pool.acquire() as conn:
                await llm_calls.insert_call(
                    conn, turn_id=self.turn_id, game_id=self.game_id, user_id=self.user_id,
                    purpose=purpose.value, provider=provider_name, model=model,
                    usage={k: cost[k] for k in ("input_tokens", "output_tokens",
                                                "cache_creation_input_tokens",
                                                "cache_read_input_tokens")},
                    cost_usd=cost["cost_usd"], cost_unknown=is_unpriced(provider_name, model),
                )
        except Exception as e:
            log_exception(logger, logging.ERROR,
                          f"[COST] llm_calls insert failed purpose={purpose.value}", e)
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
        return LLMCall(result.content, await self._record(purpose, provider, result.usage))

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
        cost = await self._record(purpose, provider, result.usage)
        return LLMCall(parse_json_response(result.content), cost)

    async def extract_structured(self, system_prompt: str, user_message: str, tool_name: str,
                                 tool_description: str, schema: dict, temperature: float,
                                 max_tokens: int) -> LLMCall:
        """Structured extraction dispatched on the provider's mode, with a text fallback."""
        purpose = Purpose.EXTRACTION
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
                cost = await self._record(purpose, provider, result.usage)
                return LLMCall(replace_lone_surrogates(result.tool_input), cost)
            if mode == StructuredOutputMode.JSON_SCHEMA:
                result = await provider.complete_with_schema(
                    system_prompt=system_prompt, messages=messages,
                    schema_name=tool_name, schema=schema,
                    temperature=temperature, max_tokens=max_tokens,
                )
                cost = await self._record(purpose, provider, result.usage)  # billed even if unparsable
                return LLMCall(replace_lone_surrogates(json.loads(result.content)), cost)
        except NotImplementedError:
            logger.info(f"[LLM] {self.provider_name} has no {mode.value} support, using text")
        except Exception as e:
            logger.warning(f"[LLM] {mode.value} extraction failed: {safe_repr(e)}, falling back to text")
        return await self.complete_json(purpose, system_prompt, user_message,
                                        temperature, max_tokens)
