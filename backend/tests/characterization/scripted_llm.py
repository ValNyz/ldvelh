"""Deterministic LLM double for characterization tests.

Every LLM call is classified by purpose (from its system prompt or tool name),
answered with a scripted payload, and recorded so tests can assert the call sequence.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from prompts.extraction import (
    characters_prompt,
    inventory_prompt,
    locations_prompt,
    narrative_arcs_prompt,
    organizations_prompt,
)
from prompts.identity_prompt import IDENTITY_PROMPT_MARKER, IDENTITY_STRONG_MARKER
from services.extraction.resolver import RESOLVER_SYSTEM_PROMPT
from services.llm_providers import (
    CompletionResult,
    LLMProvider,
    LLMUsage,
    ModelPricing,
    StructuredOutputMode,
    ToolResult,
)

USAGE = LLMUsage(input_tokens=100, output_tokens=50)

_MARKERS = [
    ("Tu es un créateur de mondes", "world_gen"),
    ("Tu es le **Maître du Jeu**", "narration"),
    ("Tu es le **Directeur de scénario**", "director"),
    ("## YOUR ROLE", "mechanical"),
    ("**assistant de création de partie**", "world_enhance"),
]

# Extractor system prompts -> the same label the tool_use / json_schema paths derive
# from the tool name, so a TEXT-mode (plain complete()) extraction is labelled alike.
_EXTRACTOR_PROMPTS = {
    characters_prompt.SYSTEM_PROMPT: "extract:extract_characters",
    locations_prompt.SYSTEM_PROMPT: "extract:extract_locations",
    organizations_prompt.SYSTEM_PROMPT: "extract:extract_organizations",
    inventory_prompt.SYSTEM_PROMPT: "extract:extract_inventory",
    narrative_arcs_prompt.SYSTEM_PROMPT: "extract:extract_narrative_arcs",
}


def classify_call(system_prompt: str, tool_name: str | None = None) -> str:
    """Map an LLM call to a stable purpose label."""
    # The identity decision is told by its prompt, whatever its tool (or schema) name.
    if system_prompt.startswith(IDENTITY_PROMPT_MARKER):
        strong = IDENTITY_STRONG_MARKER in system_prompt
        return "identity_strong" if strong else "identity"
    if tool_name:
        return f"extract:{tool_name}"
    if system_prompt == RESOLVER_SYSTEM_PROMPT:
        return "resolver"
    if system_prompt in _EXTRACTOR_PROMPTS:
        return _EXTRACTOR_PROMPTS[system_prompt]
    head = system_prompt[:600]
    for marker, purpose in _MARKERS:
        if marker in head:
            return purpose
    return "unknown"


@dataclass
class CallRecord:
    method: str
    purpose: str
    model: str | None = None


class ScriptedLLMProvider(LLMProvider):
    """LLM provider returning scripted payloads per purpose."""

    def __init__(self, responses: dict, mode: StructuredOutputMode = StructuredOutputMode.TOOL_USE):
        self._responses = dict(responses)
        self._cursor: dict[str, int] = {}
        self.STRUCTURED_OUTPUT = mode
        self.calls: list[CallRecord] = []
        self.fail_on: dict[str, Exception] = {}
        # When set, stream() waits on this event after its first chunk (disconnect tests).
        self.stream_gate: asyncio.Event | None = None

    def _next(self, purpose: str, default):
        value = self._responses.get(purpose, default)
        if isinstance(value, list):
            i = self._cursor.get(purpose, 0)
            self._cursor[purpose] = i + 1
            return value[min(i, len(value) - 1)]
        return value

    def _record(self, method: str, purpose: str) -> None:
        self.calls.append(CallRecord(method=method, purpose=purpose))
        if purpose in self.fail_on:
            raise self.fail_on[purpose]

    def purposes(self) -> list[str]:
        return [c.purpose for c in self.calls]

    async def stream(self, system_prompt, messages, temperature, max_tokens) -> AsyncIterator[str | LLMUsage]:
        purpose = classify_call(system_prompt)
        self._record("stream", purpose)
        content = self._next(purpose, "{}")
        # Split in two chunks so SSE chunk reassembly is exercised.
        mid = len(content) // 2
        yield content[:mid]
        if self.stream_gate is not None:
            await self.stream_gate.wait()
        yield content[mid:]
        yield USAGE

    async def complete(self, system_prompt, messages, temperature, max_tokens) -> CompletionResult:
        purpose = classify_call(system_prompt)
        self._record("complete", purpose)
        content = self._next(purpose, "{}")
        if not isinstance(content, str):
            content = json.dumps(content)
        return CompletionResult(content=content, usage=USAGE)

    async def complete_with_tools(self, system_prompt, messages, tools, tool_choice, temperature, max_tokens) -> ToolResult:
        tool_name = tool_choice.get("name", tools[0]["name"])
        purpose = classify_call(system_prompt, tool_name=tool_name)
        self._record("complete_with_tools", purpose)
        payload = self._next(purpose, {})
        if isinstance(payload, str):
            payload = json.loads(payload)
        return ToolResult(tool_name=tool_name, tool_input=payload, usage=USAGE)

    async def complete_with_schema(self, system_prompt, messages, schema_name, schema, temperature, max_tokens) -> CompletionResult:
        purpose = classify_call(system_prompt, tool_name=schema_name)
        self._record("complete_with_schema", purpose)
        payload = self._next(purpose, {})
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        return CompletionResult(content=payload, usage=USAGE)

    @property
    def supports_cache_control(self) -> bool:
        return False

    def model_name(self, purpose: str) -> str:
        return "scripted-model"

    def get_pricing(self, model: str) -> ModelPricing:
        return ModelPricing(input=0.0, output=0.0)

    @property
    def provider_name(self) -> str:
        return "scripted"


def make_provider_class(instance: ScriptedLLMProvider) -> type:
    """Class whose constructor always returns the shared scripted instance."""

    class _Factory:
        # Class-level attributes read by services.llm_providers catalog functions.
        MODEL_MAIN = "scripted-model"
        MODELS: dict[str, str] = {}
        STRUCTURED_OUTPUT = instance.STRUCTURED_OUTPUT

        def __new__(cls, *args, **kwargs):
            return instance

    return _Factory
