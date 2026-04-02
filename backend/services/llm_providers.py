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

logger = logging.getLogger(__name__)


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


@dataclass
class ModelPricing:
    """Cost per million tokens (USD)."""

    input: float = 0.0
    output: float = 0.0
    cache_write: float = 0.0
    cache_read: float = 0.0


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
    MODELS: dict[str, str] = {}

    def model_name(self, purpose: str) -> str:
        """Return model ID for a given purpose. Default: MODEL_MAIN for all."""
        return self.MODEL_MAIN

    @abstractmethod
    def get_pricing(self, model: str) -> ModelPricing:
        """Return pricing for a specific model."""
        ...

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

    PRICING: dict[str, ModelPricing] = {
        "claude-sonnet-4-5": ModelPricing(
            input=3.0, output=15.0, cache_write=3.75, cache_read=0.30
        ),
        "claude-sonnet-4-6": ModelPricing(
            input=3.0, output=15.0, cache_write=3.75, cache_read=0.30
        ),
        "claude-haiku-4-5": ModelPricing(
            input=1.0, output=5.0, cache_write=1.25, cache_read=0.1
        ),
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

    def get_pricing(self, model: str) -> ModelPricing:
        return self.PRICING.get(model, self.PRICING["claude-sonnet-4-6"])

    @property
    def provider_name(self) -> str:
        return "anthropic"


# =============================================================================
# MISTRAL PROVIDER
# =============================================================================


class MistralProvider(LLMProvider):
    """Mistral AI provider."""

    MODEL_MAIN = "mistral-large-latest"

    MODELS: dict[str, str] = {
        "mistral-large-latest": "Mistral Large",
    }

    PRICING: dict[str, ModelPricing] = {
        "mistral-large-latest": ModelPricing(input=0.5, output=1.5),
    }

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model and model in self.MODELS:
            self.MODEL_MAIN = model
        key = api_key or get_settings().mistral_api_key
        self.client = Mistral(api_key=key)

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

    def get_pricing(self, model: str) -> ModelPricing:
        return self.PRICING.get(model, self.PRICING["mistral-large-latest"])

    @property
    def provider_name(self) -> str:
        return "mistral"


# =============================================================================
# OPENAI-COMPATIBLE PROVIDER (base for wandb, Nebius, Nous Research, etc.)
# =============================================================================


class OpenAICompatibleProvider(LLMProvider):
    """Base class for any provider exposing an OpenAI-compatible API."""

    PRICING: dict[str, ModelPricing] = {}
    FORCE_JSON: bool = False

    def __init__(
        self,
        base_url: str,
        api_key: str,
        pricing: dict[str, ModelPricing],
    ):
        self.client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._pricing = pricing

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

    def get_pricing(self, model: str) -> ModelPricing:
        return self._pricing.get(model, ModelPricing())

    @property
    def provider_name(self) -> str:
        return "openai_compatible"


class WandbProvider(OpenAICompatibleProvider):
    """W&B Inference provider (Qwen 3 235B)."""

    MODEL_MAIN = "Qwen/Qwen3-235B-A22B-Instruct-2507"

    MODELS: dict[str, str] = {
        "Qwen/Qwen3-235B-A22B-Instruct-2507": "Qwen 3 235B",
    }

    PRICING = {
        "Qwen/Qwen3-235B-A22B-Instruct-2507": ModelPricing(input=0.10, output=0.10),
    }

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model and model in self.MODELS:
            self.MODEL_MAIN = model
        key = api_key or get_settings().wandb_api_key
        super().__init__(
            base_url="https://api.inference.wandb.ai/v1",
            api_key=key,
            pricing=self.PRICING,
        )

    @property
    def provider_name(self) -> str:
        return "wandb"


class NebiusProvider(OpenAICompatibleProvider):
    """Nebius Token Factory provider (Qwen 3 235B)."""

    MODEL_MAIN = "Qwen/Qwen3-235B-A22B-Instruct-2507"

    MODELS: dict[str, str] = {
        "Qwen/Qwen3-235B-A22B-Instruct-2507": "Qwen 3 235B",
    }

    PRICING = {
        "Qwen/Qwen3-235B-A22B-Instruct-2507": ModelPricing(input=0.20, output=0.60),
    }

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model and model in self.MODELS:
            self.MODEL_MAIN = model
        key = api_key or get_settings().nebius_api_key
        super().__init__(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=key,
            pricing=self.PRICING,
        )

    @property
    def provider_name(self) -> str:
        return "nebius"


# =============================================================================
# NOUS RESEARCH PROVIDER
# =============================================================================


class NousResearchProvider(OpenAICompatibleProvider):
    """Nous Research inference provider (Hermes 4)."""

    MODEL_MAIN = "Hermes-4-405B"
    FORCE_JSON = True
    STRUCTURED_OUTPUT = StructuredOutputMode.JSON_SCHEMA

    MODELS: dict[str, str] = {
        "Hermes-4-405B": "Hermes 4 405B",
        "Hermes-4-70B": "Hermes 4 70B",
    }

    PRICING = {
        "Hermes-4-405B": ModelPricing(input=0.09, output=0.37),
        "Hermes-4-70B": ModelPricing(input=0.05, output=0.2),
    }

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model and model in self.MODELS:
            self.MODEL_MAIN = model
        key = api_key or get_settings().nous_api_key
        super().__init__(
            base_url="https://inference-api.nousresearch.com/v1",
            api_key=key,
            pricing=self.PRICING,
        )

    @property
    def provider_name(self) -> str:
        return "nous"


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
    """Return available providers with their models for frontend discovery."""
    catalog = {}
    for name, cls in _CLASSES.items():
        models = getattr(cls, "MODELS", {})
        catalog[name] = {
            "models": [{"id": mid, "label": label} for mid, label in models.items()],
            "default_model": cls.MODEL_MAIN,
            "structured_output": cls.STRUCTURED_OUTPUT.value,
        }
    return {"providers": catalog}
