"""
LDVELH - LLM Provider Abstraction

Abstract interface + implementations for Anthropic, Mistral,
OpenAI-compatible providers (wandb, Nebius), and Nous Research.
Each provider handles raw API calls and exposes pricing.
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import Enum

import anthropic
import openai
from mistralai.client import Mistral

from config import get_settings
from llm.profile import ModelProfile
from services.pricing import ModelPricing  # re-exported for backward compat

logger = logging.getLogger(__name__)

__all__ = ["ModelPricing"]  # silence unused-import warning

# SDK clients keyed by (provider, sha256(api key)): one connection pool per user key
# instead of one per call (#42). Provider instances stay per call and carry the model.
CLIENT_CACHE_SIZE = 256
_client_cache: "OrderedDict[tuple[str, str], object]" = OrderedDict()


def shared_client(provider_name: str, api_key: str, factory: Callable[[], object]) -> object:
    """Return the cached SDK client for this provider and key, creating it once."""
    key = (provider_name, hashlib.sha256((api_key or "").encode()).hexdigest())
    client = _client_cache.get(key)
    if client is None:
        client = factory()
        _client_cache[key] = client
        # Evicted clients are not closed here: an in-flight call may still use them.
        while len(_client_cache) > CLIENT_CACHE_SIZE:
            _client_cache.popitem(last=False)
    else:
        _client_cache.move_to_end(key)
    return client


async def close_shared_clients() -> None:
    """Close every cached SDK client (application shutdown)."""
    clients = list(_client_cache.values())
    _client_cache.clear()
    for client in clients:
        closer = getattr(client, "close", None) or getattr(client, "aclose", None)
        if closer is None and hasattr(client, "__aexit__"):  # e.g. Mistral client
            closer = lambda c=client: c.__aexit__(None, None, None)
        if closer is None:
            continue
        try:
            result = closer()
            if hasattr(result, "__await__"):
                await result
        except Exception as e:  # shutdown must not fail on one client
            logger.warning(f"[LLM] Failed to close client: {e}")


# =============================================================================
# SHARED DATA TYPES
# =============================================================================


def _content_text(content) -> str:
    """Text of a message/delta content: str, None, or a list of content blocks.

    Reasoning models (e.g. Mistral zai-glm, some OpenAI-compatible hosts)
    return lists of blocks or an empty content; only text blocks are kept.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
        if kind in (None, "text") and isinstance(text, str):
            parts.append(text)
    return "".join(parts)


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
    profile: ModelProfile | None = None

    def _temperature_kwargs(self, temperature: float) -> dict:
        """`temperature` kwarg unless the model profile says it is rejected."""
        if self.profile is not None and not self.profile.send_temperature:
            return {}
        return {"temperature": temperature}

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

    # Optional cheaper model for the mechanical (dice) decision. None: use MODEL_MAIN.
    MODEL_MECHANICAL: str | None = None

    def model_name(self, purpose: str) -> str:
        """Return model ID for a given purpose. Default: MODEL_MAIN for all."""
        if purpose == "mechanical" and self.MODEL_MECHANICAL:
            return self.MODEL_MECHANICAL
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

    MODEL_MAIN = "claude-sonnet-5-5"
    MODEL_MECHANICAL = "claude-haiku-5-5"
    STRUCTURED_OUTPUT = StructuredOutputMode.TOOL_USE

    MODELS: dict[str, str] = {
        "claude-sonnet-5-5": "Sonnet 5.5",
        "claude-opus-5-5": "Opus 5.5",
        "claude-haiku-5-5": "Haiku 5.5",
        "claude-fable-5-1": "Fable 5.1",
    }

    # Claude 5 request rules (Anthropic model docs): non-default sampling
    # parameters are rejected, forced tool_choice is rejected, responses can
    # start with thinking blocks, and thinking counts toward max_tokens.
    # Per-model thinking: Sonnet 5.5 can skip up-front thinking ("between_tools"),
    # Haiku 5.5 can disable it; Opus 5.5 and Fable 5.1 always think, so they get
    # extra output room on top of the caller's budget.
    THINKING_HEADROOM = 16_000
    FALLBACK_PROFILES: dict[str, ModelProfile] = {
        "claude-sonnet-5-5": ModelProfile(
            send_temperature=False, force_tool=False, thinking={"type": "between_tools"}
        ),
        "claude-haiku-5-5": ModelProfile(
            send_temperature=False, force_tool=False, thinking={"type": "disabled"}
        ),
        "claude-opus-5-5": ModelProfile(
            send_temperature=False, force_tool=False, thinking_headroom=THINKING_HEADROOM
        ),
        "claude-fable-5-1": ModelProfile(
            send_temperature=False, force_tool=False, thinking_headroom=THINKING_HEADROOM
        ),
    }

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        profile: ModelProfile | None = None,
    ):
        # A catalog profile vouches for the model, so unknown ids are accepted then.
        if model and (model in self.MODELS or profile is not None):
            self.MODEL_MAIN = model
        self.profile = profile
        key = api_key or get_settings().anthropic_api_key
        self.client = shared_client("anthropic", key, lambda: anthropic.AsyncAnthropic(api_key=key))

    def model_name(self, purpose: str) -> str:
        # Built from a catalog profile, this instance is one catalog model (the
        # session picked it per purpose): every call goes to MODEL_MAIN.
        if self.profile is not None:
            return self.MODEL_MAIN
        return super().model_name(purpose)

    @property
    def _effective_profile(self) -> ModelProfile:
        """Catalog profile, else the built-in Claude 5 rules for this model."""
        if self.profile is not None:
            return self.profile
        return self.FALLBACK_PROFILES.get(
            self.MODEL_MAIN, self.FALLBACK_PROFILES["claude-sonnet-5-5"]
        )

    def _request_options(self, max_tokens: int, temperature: float | None = None) -> dict:
        """Model, output budget, thinking and (if allowed) temperature for one request."""
        profile = self._effective_profile
        options: dict = {
            "model": self.MODEL_MAIN,
            "max_tokens": max_tokens + profile.thinking_headroom,
        }
        if profile.send_temperature and temperature is not None:
            options["temperature"] = temperature
        if profile.thinking:
            # Sent as extra_body so older SDK versions do not reject the field.
            options["extra_body"] = {"thinking": profile.thinking}
        return options

    async def stream(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str | LLMUsage]:
        # temperature is accepted for interface compatibility but not sent (rejected by Claude 5)
        async with self.client.messages.stream(
            **self._request_options(max_tokens, temperature),
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
                # Only text deltas: thinking deltas carry `.thinking`, not `.text`
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
            **self._request_options(max_tokens, temperature),
            system=system_prompt,
            messages=messages,
        )
        usage = response.usage
        # The reply can start with thinking blocks: read the first text block
        text = next((b.text for b in response.content if b.type == "text"), "")
        return CompletionResult(
            content=text,
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
        # Claude 5 rejects a forced tool_choice (profile.force_tool False): offer the tool with "auto".
        # If the model answers in text instead, the ValueError below triggers the
        # caller's text fallback.
        response = await self.client.messages.create(
            **self._request_options(max_tokens, temperature),
            system=system_prompt,
            messages=messages,
            tools=tools,
            tool_choice=(
                tool_choice if self._effective_profile.force_tool else {"type": "auto"}
            ),
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

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        profile: ModelProfile | None = None,
    ):
        self.profile = profile
        if model:
            self.MODEL_MAIN = model
        key = api_key or get_settings().mistral_api_key
        self.client = shared_client("mistral", key, lambda: Mistral(api_key=key))

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
            **self._temperature_kwargs(temperature),
            messages=full_messages,
        )

        total_usage = LLMUsage()
        async for event in response:
            chunk = event.data
            text = _content_text(chunk.choices[0].delta.content) if chunk.choices else ""
            if text:
                yield text

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
            **self._temperature_kwargs(temperature),
            messages=full_messages,
        )

        usage = response.usage
        return CompletionResult(
            content=_content_text(response.choices[0].message.content),
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

    def __init__(self, base_url: str, api_key: str, profile: ModelProfile | None = None):
        self.profile = profile
        self.client = shared_client(
            self.provider_name,
            api_key,
            lambda: openai.AsyncOpenAI(base_url=base_url, api_key=api_key),
        )

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
            **self._temperature_kwargs(temperature),
            messages=full_messages,
            stream=True,
            stream_options={"include_usage": True},
            **extra,
        )

        total_usage = LLMUsage()
        async for chunk in response:
            text = _content_text(chunk.choices[0].delta.content) if chunk.choices else ""
            if text:
                yield text

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
            **self._temperature_kwargs(temperature),
            messages=full_messages,
            **extra,
        )

        usage = response.usage
        return CompletionResult(
            content=_content_text(response.choices[0].message.content),
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
            **self._temperature_kwargs(temperature),
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
            content=_content_text(response.choices[0].message.content),
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

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        profile: ModelProfile | None = None,
    ):
        self.profile = profile
        if model:
            self.MODEL_MAIN = model
        key = api_key or get_settings().wandb_api_key
        super().__init__(base_url="https://api.inference.wandb.ai/v1", api_key=key, profile=profile)

    @property
    def provider_name(self) -> str:
        return "wandb"


class NebiusProvider(OpenAICompatibleProvider):
    """Nebius Token Factory provider."""

    MODEL_MAIN = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    MODELS: dict[str, str] = {}

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        profile: ModelProfile | None = None,
    ):
        self.profile = profile
        if model:
            self.MODEL_MAIN = model
        key = api_key or get_settings().nebius_api_key
        super().__init__(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=key, profile=profile)

    @property
    def provider_name(self) -> str:
        return "nebius"


# =============================================================================
# NOUS RESEARCH PROVIDER
# =============================================================================


class NousResearchProvider(OpenAICompatibleProvider):
    """Nous Research inference provider."""

    MODEL_MAIN = "Hermes-4-405B"
    STRUCTURED_OUTPUT = StructuredOutputMode.JSON_SCHEMA
    MODELS: dict[str, str] = {}
    BASE_URL = "https://inference-api.nousresearch.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        profile: ModelProfile | None = None,
    ):
        self.profile = profile
        if model:
            self.MODEL_MAIN = model
        self._api_key = api_key or get_settings().nous_api_key
        super().__init__(base_url=self.BASE_URL, api_key=self._api_key, profile=profile)

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
            if cache_write:
                entry["cache_write_price"] = cache_write * 1_000_000
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
    profile: ModelProfile | None = None,
) -> LLMProvider:
    """Get or create a provider instance.

    If api_key is provided, creates a fresh (non-cached) instance.
    Otherwise returns a cached singleton using the server-level key.
    """
    cls = _CLASSES.get(provider_name)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {provider_name}")

    if api_key:
        return cls(api_key=api_key, model=model, profile=profile)

    if profile is not None:
        # A catalog profile is model-specific: never share the default singleton.
        return cls(model=model, profile=profile)

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
import time

_MODEL_CACHE: dict[tuple[str, str], tuple[list[dict], float]] = {}
_MODEL_CACHE_TTL_SECONDS = 24 * 3600  # 24h
_WARNED_UNSUPPORTED: set[str] = set()


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


async def get_provider_catalog_async(user_keys: dict[str, str] | None = None,
                                     catalog=None) -> dict:
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

    When `catalog` has enabled models for a provider (and, except for
    Anthropic, the user has a key), that list is offered instead of the live
    one: catalog rows without catalog prices fall back to lookup_pricing, and
    rows still unpriced are hidden (ruling R7).
    """
    user_keys = user_keys or {}
    model_catalog = catalog
    catalog: dict = {}
    for name, cls in _CLASSES.items():
        entry = {
            "models": [],
            "default_model": cls.MODEL_MAIN,
            "structured_output": cls.STRUCTURED_OUTPUT.value,
        }

        enabled = model_catalog.enabled(name) if model_catalog is not None else []
        if enabled and (name == "anthropic" or user_keys.get(name)):
            # DB catalog drives the list; unpriced models are still dropped.
            from services.pricing import lookup_pricing
            models = []
            for e in enabled:
                if name == "anthropic" and e.model_id not in cls.MODELS and e.profile is None:
                    # The session would silently swap such a model for MODEL_MAIN.
                    if e.model_id not in _WARNED_UNSUPPORTED:
                        _WARNED_UNSUPPORTED.add(e.model_id)
                        logger.warning(f"[catalog] anthropic {e.model_id} has no profile "
                                       "and is not a known model, hiding it")
                    continue
                price = e.prices or lookup_pricing(e.model_id, name)
                if price.input == 0 and price.output == 0:
                    continue
                models.append({"id": e.model_id, "label": e.label,
                               "input_price": price.input, "output_price": price.output})
            entry["models"] = models
            entry["default_model"] = model_catalog.default_model(name, "narration") or cls.MODEL_MAIN
            catalog[name] = entry
            continue

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
