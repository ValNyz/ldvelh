"""
Mock LLM Provider for integration tests.
Returns canned responses without hitting any real API.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from services.llm_providers import (
    CompletionResult,
    LLMProvider,
    LLMUsage,
    ModelPricing,
    ToolResult,
)

EMPTY_USAGE = LLMUsage(input_tokens=100, output_tokens=50)


@dataclass
class MockLLMProvider(LLMProvider):
    """LLM provider that returns configurable canned responses."""

    _responses: dict[str, str] = field(default_factory=dict)
    _tool_responses: dict[str, dict] = field(default_factory=dict)
    _calls: list[dict] = field(default_factory=list)

    async def stream(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str | LLMUsage]:
        self._calls.append({
            "method": "stream",
            "system_prompt_len": len(system_prompt),
            "messages_count": len(messages),
        })
        content = self._responses.get("stream", '{"narrative_text": "Test response."}')
        yield content
        yield EMPTY_USAGE

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> CompletionResult:
        self._calls.append({
            "method": "complete",
            "system_prompt_len": len(system_prompt),
            "messages_count": len(messages),
        })
        content = self._responses.get("complete", "{}")
        return CompletionResult(content=content, usage=EMPTY_USAGE)

    async def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict,
        temperature: float,
        max_tokens: int,
    ) -> ToolResult:
        self._calls.append({
            "method": "complete_with_tools",
            "tools_count": len(tools),
        })
        tool_name = tool_choice.get("name", tools[0]["name"])
        tool_input = self._tool_responses.get(
            tool_name,
            {"segment_summary": "Test extraction summary."},
        )
        return ToolResult(tool_name=tool_name, tool_input=tool_input, usage=EMPTY_USAGE)

    @property
    def supports_cache_control(self) -> bool:
        return False

    def model_name(self, purpose: str) -> str:
        return "mock-model"

    def get_pricing(self, model: str) -> ModelPricing:
        return ModelPricing(input=0.0, output=0.0)

    @property
    def provider_name(self) -> str:
        return "mock"
