"""The live smoke script itself (no network): probe verdicts, model selection, report."""

from types import SimpleNamespace

from scripts import smoke_providers as smoke
from services.llm_providers import (
    CompletionResult, LLMProvider, LLMUsage, StructuredOutputMode, ToolResult,
)


class StubProvider(LLMProvider):
    MODEL_MAIN = "stub-main"
    STRUCTURED_OUTPUT = StructuredOutputMode.TOOL_USE

    def __init__(self, text="Une taverne enfumée.", json_text='{"requires_test": false, "reason": "x"}',
                 tool_input=None, fail=None):
        self.text, self.json_text, self.fail = text, json_text, fail
        self.tool_input = {"characters": [{"name": "Mira", "occupation": "forgeronne"}]} \
            if tool_input is None else tool_input

    async def stream(self, system_prompt, messages, temperature, max_tokens):
        if self.fail:
            raise self.fail
        yield self.text
        yield LLMUsage(10, 5)

    async def complete(self, system_prompt, messages, temperature, max_tokens):
        return CompletionResult(content=self.json_text, usage=LLMUsage(10, 5))

    async def complete_with_tools(self, system_prompt, messages, tools, tool_choice, temperature, max_tokens):
        return ToolResult(tool_name=tools[0]["name"], tool_input=self.tool_input, usage=LLMUsage(10, 5))

    @property
    def supports_cache_control(self):
        return False

    @property
    def provider_name(self):
        return "stub"


async def test_all_probes_pass_on_a_compliant_provider():
    provider = StubProvider()
    for name, probe in smoke.PROBES.items():
        assert (await probe(provider)).ok, name


async def test_probe_failures_are_reported_not_raised(monkeypatch):
    monkeypatch.setattr(smoke, "get_provider", lambda *a, **k: StubProvider(fail=RuntimeError("400 temperature")))
    report = await smoke.run_model("stub", "k", "stub-main", is_default=True)
    assert not report.probes["stream"].ok and "400 temperature" in report.probes["stream"].detail
    assert report.probes["json"].ok and not report.ok


async def test_unparseable_json_and_empty_extraction_fail():
    assert not (await smoke.probe_json(StubProvider(json_text="Bien sûr !"))).ok
    assert not (await smoke.probe_structured(StubProvider(tool_input={"characters": []}))).ok


def test_non_chat_models_are_skipped():
    assert smoke.is_chat_model("mistral-large-latest")
    assert not smoke.is_chat_model("mistral-embed")
    assert not smoke.is_chat_model("mistral-ocr-latest")


async def test_defaults_first_then_listed_models(monkeypatch):
    class Listing(StubProvider):
        async def list_models(self):
            return [{"id": "stub-main"}, {"id": "stub-embed"}, {"id": "stub-a"}, {"id": "stub-b"}]

    monkeypatch.setattr(smoke, "get_provider", lambda *a, **k: Listing())
    args = SimpleNamespace(model=None, all_models=True, max_models=1)
    assert await smoke.models_to_test("stub", "k", args) == [("stub-main", True), ("stub-a", False)]


async def test_exit_code_fails_only_on_default_models(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "KEY_FIELDS", {"anthropic": "anthropic_api_key"})
    monkeypatch.setattr(smoke, "get_settings", lambda: SimpleNamespace(anthropic_api_key="k"))
    monkeypatch.setattr(smoke, "get_provider", lambda *a, **k: StubProvider(fail=RuntimeError("down")))
    assert await smoke.main(["--provider", "anthropic"]) == 1
    assert "KO" in capsys.readouterr().out
