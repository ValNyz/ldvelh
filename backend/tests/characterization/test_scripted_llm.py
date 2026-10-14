"""Unit tests for the characterization LLM double."""

import pytest

from services.extraction.resolver import RESOLVER_SYSTEM_PROMPT
from services.llm_providers import LLMUsage, StructuredOutputMode
from tests.characterization.scripted_llm import (
    ScriptedLLMProvider,
    classify_call,
    make_provider_class,
)


@pytest.mark.parametrize("prompt,expected", [
    ("Tu es un créateur de mondes pour un jeu de rôle narratif solo.\n...", "world_gen"),
    ("Tu es le **Maître du Jeu** d'un jeu de rôle narratif solo.\n...", "narration"),
    ("Tu es le **Directeur de scénario** d'un jeu de rôle narratif solo.", "director"),
    ("## YOUR ROLE\nYou decide whether a test is needed", "mechanical"),
    (RESOLVER_SYSTEM_PROMPT, "resolver"),
    ("something else", "unknown"),
])
def test_classify_by_system_prompt(prompt, expected):
    assert classify_call(prompt) == expected


def test_classify_tool_name_wins():
    assert classify_call("anything", tool_name="extract_characters") == "extract:extract_characters"


async def test_stream_returns_scripted_text_then_usage():
    p = ScriptedLLMProvider({"narration": '{"narrative_text": "Bonjour."}'})
    out = [x async for x in p.stream("Tu es le **Maître du Jeu** ...", [], 0.7, 100)]
    texts = [x for x in out if isinstance(x, str)]
    assert "".join(texts) == '{"narrative_text": "Bonjour."}'
    assert len(texts) == 2
    assert isinstance(out[-1], LLMUsage)
    assert p.purposes() == ["narration"]


async def test_list_response_is_consumed_in_order_and_last_repeats():
    p = ScriptedLLMProvider({"mechanical": ['{"a": 1}', '{"a": 2}']})
    r1 = await p.complete("## YOUR ROLE", [], 0.3, 100)
    r2 = await p.complete("## YOUR ROLE", [], 0.3, 100)
    r3 = await p.complete("## YOUR ROLE", [], 0.3, 100)
    assert [r1.content, r2.content, r3.content] == ['{"a": 1}', '{"a": 2}', '{"a": 2}']


async def test_fail_on_raises_for_that_purpose():
    p = ScriptedLLMProvider({})
    p.fail_on["narration"] = RuntimeError("provider down")
    with pytest.raises(RuntimeError, match="provider down"):
        async for _ in p.stream("Tu es le **Maître du Jeu**", [], 0.7, 100):
            pass


async def test_tools_use_tool_name_purpose():
    p = ScriptedLLMProvider({"extract:extract_characters": {"characters": []}})
    r = await p.complete_with_tools(
        "sys", [], [{"name": "extract_characters"}], {"name": "extract_characters"}, 0.3, 100
    )
    assert r.tool_input == {"characters": []}
    assert p.purposes() == ["extract:extract_characters"]


def test_provider_class_returns_shared_instance():
    p = ScriptedLLMProvider({}, mode=StructuredOutputMode.TEXT)
    cls = make_provider_class(p)
    assert cls(api_key="k", model=None) is p
    assert cls() is p
    assert p.structured_output_mode == StructuredOutputMode.TEXT
