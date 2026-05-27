"""
LDVELH - LLM Provider Abstraction

Abstract interface + implementations for Anthropic, Mistral,
OpenAI-compatible providers (wandb, Nebius), and Nous Research.
Each provider handles raw API calls and exposes pricing.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

import anthropic
import openai
from mistralai.client import Mistral

from config import get_settings
from services.pricing import ModelPricing  # re-exported for backward compat

logger = logging.getLogger(__name__)

__all__ = ["ModelPricing"]  # silence unused-import warning


# =============================================================================
# SHARED DATA TYPES
# =============================================================================


@dataclass
class LLMUsage:
    """Provider-agnostic token usage."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class CompletionResult:
    """Result from a non-streaming completion call."""

    content: str
    usage: LLMUsage


@dataclass
class ToolResult:
    """Result from a tool_use completion call."""

    tool_name: str
    tool_input: dict  # Already parsed by the SDK
    usage: LLMUsage


class StructuredOutputMode(str, Enum):
    """How a provider handles structured (JSON schema) extraction."""

    TOOL_USE = "tool_use"  # Anthropic native tool_use
    JSON_SCHEMA = "json_schema"  # OpenAI Structured Outputs (schema-enforced)
    TEXT = "text"  # Raw JSON, schema in prompt only


# =============================================================================
# ABSTRACT PROVIDER
# =============================================================================


class LLMProvider(ABC):
    """Abstract LLM provider interface.

    stream() yields str deltas, then a final LLMUsage as last item.
    complete() returns content + usage in a single call.
    """

    @abstractmethod
    async def stream(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str | LLMUsage]:
        """Yield text deltas, then a final LLMUsage."""
        ...

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> CompletionResult:
        """Single completion call."""
        ...

    async def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict,
        temperature: float,
        max_tokens: int,
    ) -> ToolResult:
        """Completion with tool_use for structured output.

        Default: raises NotImplementedError (provider doesn't support it).
        """
        raise NotImplementedError(f"{self.provider_name} does not support tool_use")

    async def complete_with_schema(
        self,
        system_prompt: str,
        messages: list[dict],
        schema_name: str,
        schema: dict,
        temperature: float,
        max_tokens: int,
    ) -> CompletionResult:
        """Completion with OpenAI Structured Outputs (json_schema).

        Default: raises NotImplementedError (provider doesn't support it).
        """
        raise NotImplementedError(f"{self.provider_name} does not support json_schema")

    # Per-provider structured output capability
    STRUCTURED_OUTPUT: StructuredOutputMode = StructuredOutputMode.TEXT

    @property
    def structured_output_mode(self) -> StructuredOutputMode:
        return self.STRUCTURED_OUTPUT

    @property
    @abstractmethod
    def supports_cache_control(self) -> bool:
        """Whether this provider supports ephemeral cache control."""
        ...

    # Subclasses must define MODEL_MAIN as a class constant
    MODEL_MAIN: str

    # Subclasses should define MODELS: dict[str, str] mapping model_id -> label
    # (used as the fallback model list when no live discovery is possible).
    MODELS: dict[str, str] = {}

    def model_name(self, purpose: str) -> str:
        """Return model ID for a given purpose. Default: MODEL_MAIN for all."""
        return self.MODEL_MAIN

    async def list_models(self) -> list[dict]:
        """Return models available on this provider.

        Default: returns the hardcoded MODELS dict (used by Anthropic which has
        no live discovery endpoint). Subclasses with a `/v1/models` endpoint
        should override to fetch from the provider.

        Returns: [{"id": "model-id", "label": "Display Name"}, ...]
        """
        return [{"id": mid, "label": label} for mid, label in self.MODELS.items()]

    @staticmethod
    def _dedup_by_id(entries: list[dict]) -> list[dict]:
        """Drop entries whose `id` was already seen, preserving first-seen order.

        Several providers list aliases as separate entries that reuse the
        canonical id (Mistral returns ~10 such duplicates) and we want the
        dropdown to show each model once.
        """
        seen: set[str] = set()
        out: list[dict] = []
        for e in entries:
            mid = e.get("id")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append(e)
        return out

    @property
    @abstractmethod
    def provider_name(self) -> str: ...


# =============================================================================
# ANTHROPIC PROVIDER
# =============================================================================


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    MODEL_MAIN = "claude-sonnet-4-6"
    STRUCTURED_OUTPUT = StructuredOutputMode.TOOL_USE

    MODELS: dict[str, str] = {
        "claude-sonnet-4-6": "Sonnet 4.6",
        "claude-haiku-4-5": "Haiku 4.5",
    }

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model and model in self.MODELS:
            self.MODEL_MAIN = model
        key = api_key or get_settings().anthropic_api_key
        self.client = anthropic.AsyncAnthropic(api_key=key)

    async def stream(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str | LLMUsage]:
        async with self.client.messages.stream(
            model=self.MODEL_MAIN,
            max_tokens=max_tokens,
            temperature=temperature,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        ) as stream:
            async for event in stream:
                if hasattr(event, "delta") and hasattr(event.delta, "text"):
                    yield event.delta.text

            final_msg = await stream.get_final_message()
            usage = final_msg.usage
            yield LLMUsage(
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_creation_input_tokens=getattr(
                    usage, "cache_creation_input_tokens", 0
                )
                or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0)
                or 0,
            )

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> CompletionResult:
        response = await self.client.messages.create(
            model=self.MODEL_MAIN,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        )
        usage = response.usage
        return CompletionResult(
            content=response.content[0].text,
            usage=LLMUsage(
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_creation_input_tokens=getattr(
                    usage, "cache_creation_input_tokens", 0
                )
                or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0)
                or 0,
            ),
        )

    async def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict,
        temperature: float,
        max_tokens: int,
    ) -> ToolResult:
        response = await self.client.messages.create(
            model=self.MODEL_MAIN,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        usage = response.usage

        # Find the tool_use block in response content
        for block in response.content:
            if block.type == "tool_use":
                return ToolResult(
                    tool_name=block.name,
                    tool_input=block.input,
                    usage=LLMUsage(
                        input_tokens=getattr(usage, "input_tokens", 0),
                        output_tokens=getattr(usage, "output_tokens", 0),
                        cache_creation_input_tokens=getattr(
                            usage, "cache_creation_input_tokens", 0
                        )
                        or 0,
                        cache_read_input_tokens=getattr(
                            usage, "cache_read_input_tokens", 0
                        )
                        or 0,
                    ),
                )

        raise ValueError("No tool_use block in response")

    @property
    def supports_cache_control(self) -> bool:
        return True

    @property
    def provider_name(self) -> str:
        return "anthropic"


# =============================================================================
# MISTRAL PROVIDER
# =============================================================================


class MistralProvider(LLMProvider):
    """Mistral AI provider."""

    MODEL_MAIN = "mistral-large-latest"

    # MODELS is no longer maintained: model list is fetched live via the
    # provider's /v1/models endpoint. Kept empty for backward compat (tests).
    MODELS: dict[str, str] = {}

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model:
            self.MODEL_MAIN = model
        key = api_key or get_settings().mistral_api_key
        self.client = Mistral(api_key=key)

    async def list_models(self) -> list[dict]:
        """Fetch the live model list from Mistral's /v1/models endpoint."""
        try:
            resp = await self.client.models.list_async()
        except Exception as e:
            logger.warning(f"[mistral] list_models failed: {e}")
            return []
        return self._dedup_by_id([{"id": m.id, "label": m.id} for m in resp.data])

    async def stream(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str | LLMUsage]:
        # Mistral uses system message in the messages array
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        response = await self.client.chat.stream_async(
            model=self.MODEL_MAIN,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
        )

        total_usage = LLMUsage()
        async for event in response:
            chunk = event.data
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

            # Capture usage from the final chunk
            if chunk.usage:
                total_usage = LLMUsage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )

        yield total_usage

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> CompletionResult:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        response = await self.client.chat.complete_async(
            model=self.MODEL_MAIN,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
        )

        usage = response.usage
        return CompletionResult(
            content=response.choices[0].message.content,
            usage=LLMUsage(
                input_tokens=usage.prompt_tokens or 0 if usage else 0,
                output_tokens=usage.completion_tokens or 0 if usage else 0,
            ),
        )

    @property
    def supports_cache_control(self) -> bool:
        return False

    @property
    def provider_name(self) -> str:
        return "mistral"


# =============================================================================
# OPENAI-COMPATIBLE PROVIDER (base for wandb, Nebius, Nous Research, etc.)
# =============================================================================


class OpenAICompatibleProvider(LLMProvider):
    """Base class for any provider exposing an OpenAI-compatible API."""

    FORCE_JSON: bool = False

    def __init__(self, base_url: str, api_key: str):
        self.client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def list_models(self) -> list[dict]:
        """Fetch the live model list from the provider's /v1/models endpoint."""
        try:
            resp = await self.client.models.list()
        except Exception as e:
            logger.warning(f"[{self.provider_name}] list_models failed: {e}")
            return []
        return self._dedup_by_id([{"id": m.id, "label": m.id} for m in resp.data])

    async def stream(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str | LLMUsage]:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        extra = {}
        if self.FORCE_JSON:
            extra["response_format"] = {"type": "json_object"}
            logger.info(f"[LLM] {self.provider_name}: FORCE_JSON active (stream)")

        response = await self.client.chat.completions.create(
            model=self.MODEL_MAIN,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
            stream=True,
            stream_options={"include_usage": True},
            **extra,
        )

        total_usage = LLMUsage()
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

            if chunk.usage:
                total_usage = LLMUsage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )

        yield total_usage

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> CompletionResult:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        extra = {}
        if self.FORCE_JSON:
            extra["response_format"] = {"type": "json_object"}
            logger.info(f"[LLM] {self.provider_name}: FORCE_JSON active (complete)")

        response = await self.client.chat.completions.create(
            model=self.MODEL_MAIN,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
            **extra,
        )

        usage = response.usage
        return CompletionResult(
            content=response.choices[0].message.content,
            usage=LLMUsage(
                input_tokens=usage.prompt_tokens or 0 if usage else 0,
                output_tokens=usage.completion_tokens or 0 if usage else 0,
            ),
        )

    async def complete_with_schema(
        self,
        system_prompt: str,
        messages: list[dict],
        schema_name: str,
        schema: dict,
        temperature: float,
        max_tokens: int,
    ) -> CompletionResult:
        """Completion with OpenAI Structured Outputs (json_schema)."""
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        response = await self.client.chat.completions.create(
            model=self.MODEL_MAIN,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    "strict": False,
                },
            },
        )

        usage = response.usage
        return CompletionResult(
            content=response.choices[0].message.content,
            usage=LLMUsage(
                input_tokens=usage.prompt_tokens or 0 if usage else 0,
                output_tokens=usage.completion_tokens or 0 if usage else 0,
            ),
        )

    @property
    def supports_cache_control(self) -> bool:
        return False

    @property
    def provider_name(self) -> str:
        return "openai_compatible"


# Model lists below are fetched live via /v1/models in list_models().
# Subclasses just declare their default model + provider-specific endpoint.

class WandbProvider(OpenAICompatibleProvider):
    """W&B Inference provider."""

    MODEL_MAIN = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    MODELS: dict[str, str] = {}

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model:
            self.MODEL_MAIN = model
        key = api_key or get_settings().wandb_api_key
        super().__init__(base_url="https://api.inference.wandb.ai/v1", api_key=key)

    @property
    def provider_name(self) -> str:
        return "wandb"


class NebiusProvider(OpenAICompatibleProvider):
    """Nebius Token Factory provider."""

    MODEL_MAIN = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    MODELS: dict[str, str] = {}

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model:
            self.MODEL_MAIN = model
        key = api_key or get_settings().nebius_api_key
        super().__init__(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=key)

    @property
    def provider_name(self) -> str:
        return "nebius"


# =============================================================================
# NOUS RESEARCH PROVIDER
# =============================================================================


class NousResearchProvider(OpenAICompatibleProvider):
    """Nous Research inference provider."""

    MODEL_MAIN = "Hermes-4-405B"
    FORCE_JSON = True
    STRUCTURED_OUTPUT = StructuredOutputMode.JSON_SCHEMA
    MODELS: dict[str, str] = {}
    BASE_URL = "https://inference-api.nousresearch.com/v1"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model:
            self.MODEL_MAIN = model
        self._api_key = api_key or get_settings().nous_api_key
        super().__init__(base_url=self.BASE_URL, api_key=self._api_key)

    @property
    def provider_name(self) -> str:
        return "nous"

    async def list_models(self) -> list[dict]:
        """Fetch live model list with inline pricing from Nous's /v1/models.

        Unlike most OpenAI-compatible providers, Nous returns per-token
        pricing directly on each model entry. We use that as the source of
        truth instead of the vendored litellm pricing table.
        """
        import httpx
        url = f"{self.BASE_URL}/models"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.warning(f"[nous] list_models failed: {e}")
            return []

        from services.pricing import ModelPricing, register_pricing

        out: list[dict] = []
        for m in data.get("data", []):
            price = m.get("pricing") or {}
            try:
                prompt = float(price.get("prompt") or 0)
                completion = float(price.get("completion") or 0)
                cache_read = float(price.get("input_cache_read") or 0)
                cache_write = float(price.get("input_cache_write") or 0)
            except (TypeError, ValueError):
                continue
            # Convert per-token rates to USD per million tokens
            in_pm = prompt * 1_000_000
            out_pm = completion * 1_000_000
            entry: dict = {
                "id": m["id"],
                "label": m.get("name") or m["id"],
                "input_price": in_pm,
                "output_price": out_pm,
            }
            if cache_read:
                entry["cache_read_price"] = cache_read * 1_000_000
            # Register so later cost computations don't need to consult litellm
            register_pricing(
                m["id"],
                "nous",
                ModelPricing(
                    input=in_pm,
                    output=out_pm,
                    cache_read=cache_read * 1_000_000,
                    cache_write=cache_write * 1_000_000,
                ),
            )
            out.append(entry)
        return self._dedup_by_id(out)


# =============================================================================
# PROVIDER REGISTRY & FACTORY
# =============================================================================

_CLASSES: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "mistral": MistralProvider,
    "wandb": WandbProvider,
    "nebius": NebiusProvider,
    "nous": NousResearchProvider,
}

_providers: dict[str, LLMProvider] = {}


def get_provider(
    provider_name: str = "anthropic",
    api_key: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    """Get or create a provider instance.

    If api_key is provided, creates a fresh (non-cached) instance.
    Otherwise returns a cached singleton using the server-level key.
    """
    cls = _CLASSES.get(provider_name)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {provider_name}")

    if api_key:
        return cls(api_key=api_key, model=model)

    # Server-level key: cached singleton (default model)
    if provider_name not in _providers:
        _providers[provider_name] = cls()
        logger.info(f"[LLM] Created {provider_name} provider")
    return _providers[provider_name]


def get_provider_catalog() -> dict:
    """Return static provider metadata (no live model lookup).

    Use get_provider_catalog_async(user_keys=...) if you have user-scoped
    API keys and want live model discovery.
    """
    catalog = {}
    for name, cls in _CLASSES.items():
        models = getattr(cls, "MODELS", {})
        catalog[name] = {
            "models": [{"id": mid, "label": label} for mid, label in models.items()],
            "default_model": cls.MODEL_MAIN,
            "structured_output": cls.STRUCTURED_OUTPUT.value,
        }
    return {"providers": catalog}


# Live model-list cache: (provider, key_hash) -> (models, expires_at_epoch).
# Single-process in-memory; refresh window controls staleness.
import hashlib
import time

_MODEL_CACHE: dict[tuple[str, str], tuple[list[dict], float]] = {}
_MODEL_CACHE_TTL_SECONDS = 24 * 3600  # 24h


def _cache_key(provider_name: str, api_key: str | None) -> tuple[str, str]:
    digest = hashlib.sha256((api_key or "").encode()).hexdigest()[:16]
    return (provider_name, digest)


def _enrich_with_pricing(
    models: list[dict], provider_name: str
) -> list[dict]:
    """Attach input/output pricing to each model entry; drop unpriced models.

    If a model entry already carries `input_price`/`output_price` (e.g. Nous,
    which returns pricing inline in /v1/models), trust those values and skip
    the vendored litellm lookup.

    UI policy: only show models we can compute cost for. Models missing from
    the vendored pricing table are silently dropped (logged at debug).
    """
    from services.pricing import lookup_pricing

    enriched = []
    dropped = []
    for m in models:
        if "input_price" in m and "output_price" in m:
            if m["input_price"] == 0 and m["output_price"] == 0:
                dropped.append(m["id"])
                continue
            enriched.append(m)
            continue
        price = lookup_pricing(m["id"], provider_name)
        if price.input == 0 and price.output == 0:
            dropped.append(m["id"])
            continue
        enriched.append({
            **m,
            "input_price": price.input,   # USD per million input tokens
            "output_price": price.output,  # USD per million output tokens
        })
    if dropped:
        logger.debug(
            f"[catalog] {provider_name}: dropped {len(dropped)} unpriced models: "
            f"{dropped[:5]}{'...' if len(dropped) > 5 else ''}"
        )
    return enriched


async def get_provider_catalog_async(user_keys: dict[str, str] | None = None) -> dict:
    """Return providers with live-fetched model lists where possible.

    For each provider:
      - Anthropic: returns the hardcoded MODELS (no live API)
      - Mistral / wandb / Nebius / Nous: if the user has a stored API key,
        fetch /v1/models live (cached 24h per provider+key)
      - No key: returns an empty models list so the UI can prompt the user
        to configure their key first.

    Each model in the response includes input_price and output_price (USD
    per million tokens). Models for which we don't have pricing data in
    the vendored pricing table are filtered out — the UI never shows a
    model whose cost can't be computed.
    """
    user_keys = user_keys or {}
    catalog: dict = {}
    for name, cls in _CLASSES.items():
        entry = {
            "models": [],
            "default_model": cls.MODEL_MAIN,
            "structured_output": cls.STRUCTURED_OUTPUT.value,
        }

        raw_models: list[dict] = []
        if name == "anthropic":
            raw_models = [
                {"id": mid, "label": label} for mid, label in cls.MODELS.items()
            ]
        else:
            key = user_keys.get(name)
            if not key:
                catalog[name] = entry  # empty; UI prompts user
                continue

            cache_k = _cache_key(name, key)
            cached = _MODEL_CACHE.get(cache_k)
            if cached and cached[1] > time.time():
                raw_models = cached[0]
            else:
                try:
                    provider = cls(api_key=key)
                    raw_models = await provider.list_models()
                    _MODEL_CACHE[cache_k] = (
                        raw_models, time.time() + _MODEL_CACHE_TTL_SECONDS,
                    )
                except Exception as e:
                    logger.warning(f"[catalog] {name} list_models failed: {e}")

        entry["models"] = _enrich_with_pricing(raw_models, name)
        catalog[name] = entry

    return {"providers": catalog}
