"""The identity eval runner, the legacy resolver adapter and its offline path (#151)."""

import json
import math
import shutil
from pathlib import Path

import yaml

from evals.identity import runner
from evals.identity.adapters import legacy_resolver
from evals.identity.adapters.legacy_resolver import LegacyResolverAdapter
from evals.identity.corpus import Scene, load_scenes
from evals.identity.report import FAIL, OK
from evals.identity.run import Decision, RunResult
from llm.session import LLMCall, LLMSession, Purpose
from scripts import eval_identity
from services.extraction.resolver import MentionMapping, ResolutionMap, resolve_entities
from tests.identity.test_corpus import ROOT, _scene

WITH_HISTORY = "syn-sf-easy-01"
WITHOUT_HISTORY = "audit-objet-nomme"


def _scenes(*ids: str) -> list[Scene]:
    by_id = {s.id: s for s in load_scenes(ROOT)}
    return [by_id[i] for i in ids]


def _gold_decisions(scene: Scene) -> list[Decision]:
    """The decisions the gold expects (SKIP: none; SAME: a MATCH to the NEW's id)."""
    decisions = []
    for m in scene.gold:
        e = m.parsed
        if e.decision == "SKIP":
            continue
        if e.decision == "NEW":
            d = Decision(m.surface, m.start, "NEW", f"sys:{m.start}", None, e.new_type)
        elif e.decision == "SAME":
            d = Decision(m.surface, m.start, "MATCH", f"sys:{e.same_start}", None, None)
        else:
            d = Decision(
                m.surface, m.start, e.decision, e.entity_id, e.alias_kind, None
            )
        decisions.append(d)
    return decisions


class ScriptedAdapter:
    name = "scripted"

    def __init__(self, decisions_by_scene: dict[str, list[Decision]]) -> None:
        self.decisions_by_scene = decisions_by_scene

    def begin_sequence(self) -> None:
        pass

    async def candidates(self, scene: Scene) -> dict[int, list[str]]:
        return {m.start: [m.parsed.entity_id] for m in scene.gold if m.parsed.entity_id}

    async def run_scene(self, scene: Scene, *, session, pool) -> RunResult:
        candidates = await self.candidates(scene)
        return RunResult(scene.id, self.decisions_by_scene[scene.id], candidates, {})


def _row(data: dict, name: str) -> dict:
    return next(r for r in data["gate"] if r["name"] == name)


async def test_eval_runs_on_a_scripted_adapter(tmp_path):
    easy, named = _scenes(WITH_HISTORY, WITHOUT_HISTORY)
    wrong = [
        Decision(d.surface, d.start, "MATCH", "object_coffret_de_fer", None, None)
        if d.surface == "Olbert"
        else d
        for d in _gold_decisions(named)
    ]
    adapter = ScriptedAdapter({easy.id: _gold_decisions(easy), named.id: wrong})
    results = await runner.run_scenes(adapter, [easy, named], lambda _: None)
    scores = runner.score([easy, named], results)
    markdown, data = runner.build_report(
        [scores], provider="scripted", models={}, split="dev", iterations=50
    )
    path = runner.write_report(tmp_path, "report", markdown, data)

    assert path.read_text(encoding="utf-8") == markdown
    assert json.loads((tmp_path / "report.json").read_text())["split"] == "dev"
    golds = len(easy.gold) + len(named.gold)
    w = _row(data, "W")
    assert math.isclose(w["value"], 1 / golds) and w["verdict"] == FAIL
    assert _row(data, "easy_pool")["verdict"] == OK
    assert _row(data, "c_at_10")["value"] == 1.0
    assert _row(data, "hard_macro")["verdict"] == FAIL  # hard categories missing
    assert data["gate_passed"] is False

    perfect = ScriptedAdapter({easy.id: _gold_decisions(easy)})
    scores = runner.score(
        [easy], await runner.run_scenes(perfect, [easy], lambda _: None)
    )
    _, data = runner.build_report(
        [scores], provider="s", models={}, split="dev", iterations=50
    )
    assert _row(data, "W")["value"] == 0.0 and _row(data, "W")["verdict"] == OK


async def test_legacy_adapter_maps_canonicals_to_world_ids(monkeypatch):
    scene = Scene.model_validate(_scene())  # no history: first-turn reference
    calls = []
    resolution = ResolutionMap([
        MentionMapping("la kethari âgée", "Kethari âgée", "character", False),
        MentionMapping("Le terminal", "Terminal du quai", "object", False),
        MentionMapping("Nahle", "Nahle", "character", True),
    ])  # fmt: skip

    async def fake_resolve(pool, game_id, previous, annotations, current, session):
        calls.append((previous, annotations, current))
        return resolution, {"input_tokens": 7, "output_tokens": 2}

    monkeypatch.setattr(legacy_resolver, "resolve_entities", fake_resolve)
    result = await LegacyResolverAdapter().run_scene(scene, session=None, pool=None)

    by_start = {d.start: d for d in result.decisions}
    narration = scene.narration
    kethari = by_start[0]
    assert (kethari.decision, kethari.entity_id) == ("MATCH", "character_kethari_agee")
    terminal = by_start[narration.index("Le terminal")]
    assert (terminal.decision, terminal.entity_id) == (
        "MATCH",
        "unknown:Terminal du quai",
    )
    nahle = by_start[narration.index("Nahle")]
    assert (nahle.decision, nahle.new_type) == ("NEW", "character")
    assert nahle.entity_id == f"new:{scene.id}:{nahle.start}"
    previous, _annotations, current = calls[0]
    assert previous == "La Kethari âgée [= La Kethari âgée]"  # protagonist not listed
    assert current == narration
    assert result.candidates[0] == ["character_kethari_agee"]
    assert result.usage["input_tokens"] == 7 and result.usage["failed_calls"] == 0


def _corpus(tmp_path: Path, *ids: str) -> Path:
    root = tmp_path / "corpus"
    (root / "scenes").mkdir(parents=True)
    for scene_id in ids:
        shutil.copy(ROOT / "scenes" / f"{scene_id}.yaml", root / "scenes")
    split = {"dev": [], "test": list(ids)}
    (root / "split.yaml").write_text(yaml.safe_dump(split), encoding="utf-8")
    return root


RESPONSE = {
    "existing": [
        {"mentions": ["Oskar Venn"], "canonical": "Oskar Venn", "entity_type": "character"},
        {"mentions": ["la Salle des Cartes"], "canonical": "Salle des Cartes",
         "entity_type": "location"},
    ],
    "new": [{"mentions": ["Pivert"], "suggested_name": "Pivert", "entity_type": "character"}],
}  # fmt: skip


async def test_emitted_request_is_what_resolve_entities_sends(tmp_path, monkeypatch):
    root = _corpus(tmp_path, WITH_HISTORY)
    prompts = tmp_path / "prompts"
    args = ["--root", str(root), "--split", "test", "--emit-prompts", str(prompts)]
    assert await eval_identity._run(eval_identity._parser().parse_args(args)) == 0
    emitted = json.loads((prompts / f"{WITH_HISTORY}.json").read_text("utf-8"))

    sent = {}

    async def capture(
        self, purpose, system_prompt, user_message, temperature, max_tokens
    ):
        sent.update(purpose=purpose, system=system_prompt, user=user_message,
                    temperature=temperature, max_tokens=max_tokens)  # fmt: skip
        return LLMCall(None, None)

    monkeypatch.setattr(LLMSession, "complete_json", capture)
    (scene,) = _scenes(WITH_HISTORY)
    last = scene.history[-1]
    labels = {e.id: e.label for e in scene.world}
    annotations = [
        [m.start, m.start + len(m.surface), labels[m.parsed.entity_id], "x"]
        for m in last.mentions
        if m.parsed.decision == "MATCH"
    ]
    session = LLMSession.from_provider(legacy_resolver.OfflineProvider(
        eval_identity.resolver_provider("anthropic", "offline", {})))  # fmt: skip
    await resolve_entities(None, None, last.text, annotations, scene.narration, session)

    assert sent["purpose"] is Purpose.RESOLVER
    assert emitted["system"] == sent["system"]
    assert emitted["messages"] == [{"role": "user", "content": sent["user"]}]
    assert "Oskar Venn [= Oskar Venn]" in sent["user"]
    assert emitted["model"] == "claude-sonnet-5-5"
    assert emitted["max_tokens"] == sent["max_tokens"]


def test_emit_then_import_round_trips_on_two_scenes(tmp_path):
    root = _corpus(tmp_path, WITH_HISTORY, WITHOUT_HISTORY)
    prompts, out = tmp_path / "prompts", tmp_path / "out"
    base = ["--root", str(root), "--split", "test"]
    assert eval_identity.main([*base, "--emit-prompts", str(prompts)]) == 0
    assert sorted(p.name for p in prompts.iterdir()) == [
        f"{WITHOUT_HISTORY}.json",
        f"{WITH_HISTORY}.json",
    ]
    fenced = f"```json\n{json.dumps(RESPONSE, ensure_ascii=False)}\n```"
    (prompts / f"{WITH_HISTORY}.txt").write_text(fenced, encoding="utf-8")
    (prompts / f"{WITHOUT_HISTORY}.txt").write_text("no json here", encoding="utf-8")

    args = [*base, "--import-responses", str(prompts), "--out", str(out)]
    assert eval_identity.main([*args, "--iterations", "20"]) == 0
    (report,) = out.glob("*.md")
    assert report.name.endswith("-test-anthropic-claude-sonnet-5-5.md")
    assert "subagent responses (not the API path)" in report.read_text("utf-8")
    data = json.loads(report.with_suffix(".json").read_text("utf-8"))
    assert data["scenes"] == 2 and data["models"] == {"resolver": "claude-sonnet-5-5"}
    assert data["cost"]["calls"] == 2 and data["cost"]["failed_calls"] == 1
    assert data["c_at_10_source"] == "dev + test, 1 run"
