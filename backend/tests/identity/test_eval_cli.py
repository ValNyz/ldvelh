"""The identity eval runner, the legacy and v2 resolver adapters and their offline paths
(#151, #154)."""

import json
import math
import re
import shutil
from pathlib import Path

import pytest
import yaml

from evals.identity import coref, leaks, runner
from evals.identity.adapters import legacy_resolver
from evals.identity.adapters.legacy_resolver import LegacyResolverAdapter
from evals.identity.adapters.resolver_v2 import ResolverV2Adapter
from evals.identity.calls import Call, Tap, request_token
from evals.identity.corpus import Scene, load_scenes, load_sequences
from evals.identity.report import FAIL, OK
from evals.identity.run import Decision, RunResult
from evals.identity.scorer import score_scene
from llm.session import LLMCall, LLMSession, Purpose
from scripts import eval_identity
from services.extraction.resolver import MentionMapping, ResolutionMap, resolve_entities
from tests.characterization.scripted_llm import ScriptedLLMProvider
from tests.conftest import TEST_DB_URL
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


async def _main(argv: list[str]) -> int:
    """`eval_identity.main` without `asyncio.run`, which would unset the test's loop."""
    return await eval_identity._run(eval_identity._parser().parse_args(argv))


class ScriptedAdapter:
    name = "scripted"
    sequence_note = ""
    needs_db = False
    candidates_note = ""

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
    world = {e.id: e for e in scene.world}
    annotations = [
        [m.start, m.start + len(m.surface), world[i].label, world[i].type]
        for m in last.mentions
        if m.parsed.decision == "MATCH" and (i := m.parsed.entity_id)
    ]
    provider = eval_identity.resolver_provider("anthropic", "offline", {})
    session = LLMSession.from_provider(legacy_resolver.OfflineProvider(provider))
    await resolve_entities(None, None, last.text, annotations, scene.narration, session)

    assert sent["purpose"] is Purpose.IDENTITY
    assert emitted["system"] == sent["system"]
    assert emitted["messages"] == [{"role": "user", "content": sent["user"]}]
    assert "Oskar Venn [= Oskar Venn]" in sent["user"]
    wire = provider._request_options(sent["max_tokens"], sent["temperature"])
    options = {
        k: v for k, v in emitted.items() if k not in ("scene_id", "system", "messages")
    }
    assert options == wire  # model, max_tokens, thinking; temperature only if sent
    assert emitted["model"] == provider.model_name(Purpose.IDENTITY.value)
    assert ("temperature" in emitted) == ("temperature" in wire)


async def test_emit_then_import_round_trips_on_two_scenes(tmp_path, monkeypatch):
    root = _corpus(tmp_path, WITH_HISTORY, WITHOUT_HISTORY)
    prompts, out = tmp_path / "prompts", tmp_path / "out"
    base = ["--root", str(root), "--split", "test"]
    assert await _main([*base, "--emit-prompts", str(prompts)]) == 0
    assert sorted(p.name for p in prompts.iterdir()) == [
        f"{WITHOUT_HISTORY}.json",
        f"{WITH_HISTORY}.json",
    ]
    fenced = f"```json\n{json.dumps(RESPONSE, ensure_ascii=False)}\n```"
    (prompts / f"{WITH_HISTORY}.txt").write_text(fenced, encoding="utf-8")
    (prompts / f"{WITHOUT_HISTORY}.txt").write_text("no json here", encoding="utf-8")

    scored = []
    real_score = runner.score

    def spy(scenes, results):
        scored.extend(results)
        return real_score(scenes, results)

    monkeypatch.setattr(runner, "score", spy)
    args = [*base, "--import-responses", str(prompts), "--out", str(out)]
    responder = "subagent:claude-sonnet"
    with pytest.raises(SystemExit, match="--responder"):
        await _main(args)
    assert await _main([*args, "--responder", responder, "--iterations", "20"]) == 0
    (report,) = out.glob("*.md")
    assert report.name.endswith("-test-anthropic-claude-sonnet-5-5-subagent.md")
    assert f"answers of {responder}" in report.read_text("utf-8")
    data = json.loads(report.with_suffix(".json").read_text("utf-8"))
    assert data["scenes"] == 2 and data["models"] == {"resolver": "claude-sonnet-5-5"}
    assert data["responder"] == responder

    by_scene = {r.scene_id: r for r in scored}
    assert by_scene[WITHOUT_HISTORY].decisions == []  # unparsable answer
    decisions = {d.start: d for d in by_scene[WITH_HISTORY].decisions}
    oskar, salle = decisions[0], decisions[44]
    assert (oskar.decision, oskar.entity_id) == ("MATCH", "character_oskar_venn")
    assert (salle.surface, salle.entity_id) == (
        "la Salle des Cartes",
        "location_salle_des_cartes",
    )
    pivert = decisions[450]
    assert (pivert.decision, pivert.entity_id) == ("NEW", f"new:{WITH_HISTORY}:450")
    assert data["cost"]["calls"] == 2 and data["cost"]["failed_calls"] == 1
    assert data["c_at_10_source"] == "dev + test, 1 run"


def test_spans_keep_the_longest_at_a_start_and_drop_nested_repeats():
    text = "Le capitaine Abasi salue. Abasi sourit."
    resolution = ResolutionMap([
        MentionMapping("Le capitaine", "Capitaine", "character", False),
        MentionMapping("le capitaine Abasi", "Jorund Abasi", "character", False),
        MentionMapping("Abasi", "Jorund Abasi", "character", False),
        MentionMapping("capitaine", "Capitaine", "character", False),
    ])  # fmt: skip
    found = [(s, e, m.canonical) for s, e, m in legacy_resolver.spans(text, resolution)]
    assert found == [
        (0, 18, "Jorund Abasi"),  # longest at start 0
        (3, 12, "Capitaine"),  # nested, another canonical: kept
        (26, 31, "Jorund Abasi"),  # the nested "Abasi" at 13 is dropped
    ]


def test_world_label_prefers_the_resolver_type_and_unknown_is_wrong():
    label = "Bureau des Résidences"
    world = [
        {"id": "location_bureau", "type": "location", "label": label, "known": True},
        {"id": "organization_bureau", "type": "organization", "label": label, "known": True},
    ]  # fmt: skip
    scene = Scene.model_validate({**_scene(), "world": [*_scene()["world"], *world]})
    lexicon = legacy_resolver.load_lexicon(scene.language)
    find = legacy_resolver._world_id
    assert find(scene.world, lexicon, "le Bureau des Résidences", "organization") == (
        "organization_bureau"
    )
    assert find(scene.world, lexicon, "Bureau des Résidences", "location") == (
        "location_bureau"
    )
    assert find(scene.world, lexicon, "Bureau inconnu", "location") is None


async def test_a_new_entity_chains_within_a_turn_and_across_turns(monkeypatch):
    (sequence,) = [q for q in load_sequences(ROOT) if q.id == "seq-df-homonymes"]
    first, second = sequence.turns[:2]
    answers = {
        first.narration: [MentionMapping(m, "Anneau sigillaire", "object", True)
                          for m in ("un anneau sigillaire", "l'anneau")],
        second.narration: [
            MentionMapping("l'anneau", "Anneau sigillaire", "object", False)
        ],
    }  # fmt: skip

    async def fake_resolve(pool, game_id, previous, annotations, current, session):
        return ResolutionMap(answers[current]), {}

    monkeypatch.setattr(legacy_resolver, "resolve_entities", fake_resolve)
    two_turns = sequence.model_copy(update={"turns": [first, second]})
    ((_, results),) = await runner.run_sequences(
        LegacyResolverAdapter(), [two_turns], lambda _: None
    )

    born = f"new:{first.id}:89"
    head, repeat = results[0].decisions
    assert (head.start, head.decision, head.entity_id) == (89, "NEW", born)
    assert (repeat.start, repeat.decision, repeat.entity_id) == (302, "MATCH", born)
    outcomes = {
        m.start: o for m, o in zip(first.gold, score_scene(first, results[0]).outcomes)
    }
    assert outcomes[89].correct and outcomes[302].correct  # NEW + its SAME repeat
    (later,) = results[1].decisions  # the world label loses to the system's own entity
    assert (later.start, later.entity_id) == (300, born)
    clusters = coref.system_clusters(two_turns, results)
    assert clusters[born] == {f"{first.id}:89", f"{first.id}:302", f"{second.id}:300"}


async def test_needs_db_reports_the_adapter_attribute(capsys):
    assert await _main(["--split", "test", "--needs-db"]) == 0
    assert capsys.readouterr().out.strip() == str(int(LegacyResolverAdapter.needs_db))


# --- resolver v2 (#154) ------------------------------------------------------------------

V2_SCENE = "audit-objet-nomme"  # dev, no history
TOKEN = request_token(V2_SCENE)  # its request files: no scene id shows through


def _handle_of(prompt: str, label: str) -> str:
    """The handle of the candidate card that shows `label`."""
    for line in prompt.splitlines():
        if f'"{label}"' in line and re.match(r"E\d+ ", line):
            return line.split(" ", 1)[0]
    raise AssertionError(f"no card for {label!r}")


def _first_pass(prompt: str) -> dict:
    """The small model's answer: what the prepass leaves (« Olbert » also names the
    shop, « ta lame » is left open)."""
    return {
        "mentions": [
            {"surface": "Olbert", "before": "coffret, dit", "decision": "MATCH",
             "handle": _handle_of(prompt, "Maître Olbert")},
            {"surface": "ta lame", "before": "Tu reprends", "decision": "UNSURE"},
            {"surface": "la garde", "before": "et frotte", "decision": "SKIP"},
        ]
    }  # fmt: skip


def _second_opinion(prompt: str) -> dict:
    """The strong model's answer: « Olbert » confirmed (it would also name the shop),
    « ta lame » not an identity."""
    return {
        "mentions": [
            {"surface": "Olbert", "before": "coffret, dit", "decision": "MATCH",
             "handle": _handle_of(prompt, "Maître Olbert")},
            {"surface": "ta lame", "before": "Tu reprends", "decision": "SKIP"},
        ]
    }  # fmt: skip


async def test_v2_adapter_runs_a_scene_with_a_scripted_session(test_pool):
    (scene,) = _scenes(V2_SCENE)
    responses = {"identity": [_first_pass], "identity_strong": [_second_opinion]}
    provider = ScriptedLLMProvider(responses)
    adapter = ResolverV2Adapter(test_pool)
    result = await adapter.run_scene(
        scene, session=LLMSession.from_provider(provider), pool=None
    )

    assert provider.purposes() == ["identity", "identity_strong"]
    by_start = {d.start: d for d in result.decisions}
    olbert = by_start[0]  # « Maître Olbert », a unique exact name
    assert (olbert.decision, olbert.entity_id) == ("MATCH", "character_maitre_olbert")
    assert olbert.deterministic
    short = by_start[scene.narration.index("Olbert", 500)]  # the model's link
    assert (short.decision, short.entity_id) == ("MATCH", "character_maitre_olbert")
    assert not short.deterministic and short.escalated
    escalated = by_start[scene.narration.index("ta lame")]
    assert (escalated.decision, escalated.escalated) == ("SKIP", True)
    assert by_start[scene.narration.index("la garde")].decision == "SKIP"
    assert "character_maitre_olbert" in result.candidates[0]
    assert result.usage["identity_calls"] == 1
    assert result.usage["identity_strong_calls"] == 1
    assert result.usage["calls"] == 2 and result.usage["escalated"] == 1
    assert result.usage["input_tokens"] == 200  # the scripted usage, both stages
    score = score_scene(scene, result)
    assert score.escalated and score.deterministic >= 1

    # The cheap tier: the small model's UNSURE stands, no second opinion.
    provider = ScriptedLLMProvider({"identity": [_first_pass]})
    cheap = await ResolverV2Adapter(test_pool, tier="cheap").run_scene(
        scene, session=LLMSession.from_provider(provider), pool=None
    )
    assert provider.purposes() == ["identity"]
    unsure = {d.start: d for d in cheap.decisions}[escalated.start]
    assert (unsure.decision, unsure.escalated) == ("UNSURE", False)
    assert "identity_strong_calls" not in cheap.usage
    assert cheap.usage["escalated"] == 0

    # Its C@10 ranking: each gold mention's own candidates, as world ids.
    ranking = await adapter.candidates(scene)
    assert ranking[0][0] == "character_maitre_olbert"


def _v2_args(root: Path, *extra: str) -> list[str]:
    return ["--adapter", "v2", "--root", str(root), "--split", "test", *extra]


async def test_v2_staged_replay_asks_each_stage_then_scores(
    tmp_path, test_pool, monkeypatch, capsys
):
    monkeypatch.setenv("TEST_DATABASE_URL", TEST_DB_URL)
    root = _corpus(tmp_path, V2_SCENE)
    io, out = tmp_path / "io", tmp_path / "out"
    responder = "subagent:claude-haiku+claude-sonnet"
    replay = _v2_args(
        root, "--import-responses", str(io), "--responder", responder,
        "--out", str(out), "--iterations", "20", "--milestone", "pr2",
    )  # fmt: skip

    assert await _main(_v2_args(root, "--emit-prompts", str(io))) == 0
    first = json.loads((io / f"{TOKEN}.1.json").read_text("utf-8"))
    assert (first["purpose"], first["model"]) == ("identity", "claude-haiku-5-5")
    assert first["call"] == 1 and "scene_id" not in first
    assert V2_SCENE not in json.dumps(first) and len(TOKEN) == 12
    assert first["tools"][0]["name"] and first["messages"][0]["role"] == "user"
    pending = json.loads((io / "pending.json").read_text("utf-8"))
    assert pending == [
        {
            "file": f"{TOKEN}.1.json",
            "purpose": "identity",
            "model": "claude-haiku-5-5",
        }
    ]
    assert "1 requests pending (identity 1)" in capsys.readouterr().out

    prompt = first["messages"][0]["content"]
    (io / f"{TOKEN}.1.txt").write_text(json.dumps(_first_pass(prompt)), "utf-8")
    assert await _main(replay) == eval_identity.PENDING_EXIT
    second = json.loads((io / f"{TOKEN}.2.json").read_text("utf-8"))
    assert (second["purpose"], second["model"]) == (
        "identity_strong",
        "claude-sonnet-5-5",
    )
    assert "identity_strong 1" in capsys.readouterr().out
    assert not list(out.glob("*.md"))  # nothing scored while a scene is pending

    strong = _second_opinion(second["messages"][0]["content"])
    fenced = f"```json\n{json.dumps(strong)}\n```"
    (io / f"{TOKEN}.2.txt").write_text(fenced, "utf-8")
    assert await _main(replay) == 0
    assert json.loads((io / "pending.json").read_text("utf-8")) == []
    (report,) = out.glob("*.md")
    assert report.name.endswith(
        "-test-anthropic-claude-haiku-5-5+claude-sonnet-5-5-subagent.md"
    )
    text = report.read_text("utf-8")
    assert eval_identity.SUBAGENT_NOTE.lower() in text.lower()
    assert "Gate du jalon PR 2" in text
    data = json.loads(report.with_suffix(".json").read_text("utf-8"))
    assert data["models"] == {
        "identity": "claude-haiku-5-5",
        "identity_strong": "claude-sonnet-5-5",
    }
    assert _row(data, "L")["value"] == 0
    assert data["cost_estimated"] is True and data["cost"]["per_turn_escalated"] == 1
    milestone = {r["name"]: r for r in data["milestone"]["rows"]}
    assert set(milestone) == {"hard_pool", "W", "L"}
    assert milestone["hard_pool"]["threshold"] == 0.85
    assert (
        data["cheap_tier"] is not None
    )  # the same answers, replayed without escalation

    # The cheap tier replays the same answers: no new request, no escalation.
    for stale in out.glob("*"):
        stale.unlink()
    assert await _main([*replay, "--tier", "cheap"]) == 0
    (report,) = out.glob("*.json")
    cheap = json.loads(report.read_text("utf-8"))
    assert cheap["models"] == {"identity": "claude-haiku-5-5"}
    assert (
        eval_identity.CHEAP_REPLAY_NOTE in cheap["header_note"]
    )  # a cascade's answers

    # An answer to a request the code no longer builds is refused.
    stored = io / f"{TOKEN}.1.json"
    stored.write_text(stored.read_text("utf-8").replace("NARRATION", "NARRATIVE"))
    with pytest.raises(SystemExit, match="stale answers"):
        await _main(replay)
    assert json.loads((io / "pending.json").read_text("utf-8")) == []

    # So is an answer whose request file is gone.
    (io / f"{TOKEN}.2.json").unlink()
    stored.write_text(stored.read_text("utf-8").replace("NARRATIVE", "NARRATION"))
    with pytest.raises(SystemExit, match="stale answers"):
        await _main(replay)


async def test_v2_runs_have_their_own_responses_directories(
    tmp_path, test_pool, monkeypatch
):
    monkeypatch.setenv("TEST_DATABASE_URL", TEST_DB_URL)
    root = _corpus(tmp_path, V2_SCENE)
    io = tmp_path / "io"
    assert await _main(_v2_args(root, "--runs", "2", "--emit-prompts", str(io))) == 0
    pending = json.loads((io / "pending.json").read_text("utf-8"))
    assert [p["file"] for p in pending] == [
        f"run1/{TOKEN}.1.json",
        f"run2/{TOKEN}.1.json",
    ]
    with pytest.raises(SystemExit, match="identity, identity_strong"):
        await _main(_v2_args(root, "--models", "resolver=x", "--emit-prompts", str(io)))


def test_leak_check_counts_cards_always_and_other_text_outside_the_narration():
    data = _scene()
    agent = {"id": "character_agent", "type": "character", "label": "Le passeur",
             "known": False, "secret": True, "true_name": "Ilse Varn",
             "aliases": [{"text": "Ilse Varn", "kind": "true_name", "known": False,
                          "secret": True}]}  # fmt: skip
    scene = Scene.model_validate(
        {**data, "world": [*data["world"], agent],
         "scene": {**data["scene"], "secrets": ["character_agent"]}}
    )  # fmt: skip
    assert leaks.secret_names(scene) == ["Ilse Varn"]
    assert leaks.leak_count(scene, ['E4 · "Le passeur"'], ["nothing"]) == 0
    assert leaks.leak_count(scene, [], ['{"evidence": "ILSE VARN entre"}']) == 1
    open_name = [{"handle": "character_agent", "kind": "name"}]
    dumped = scene.model_dump()
    disclosed = Scene.model_validate(
        {**dumped, "scene": {**dumped["scene"], "open_disclosures": open_name}}
    )
    assert leaks.secret_names(disclosed) == []
    told = Scene.model_validate({**scene.model_dump(), "narration": "Ilse Varn rit."})
    echo = ['{"surface": "Ilse Varn"}']
    assert leaks.leak_count(told, [], echo) == 0  # an echo of the narration
    # A card showing the secret alias leaks it, even when the narration holds it.
    assert leaks.leak_count(told, ['E4 · "Le passeur" · aliases: "Ilse Varn"'], []) == 1


def test_a_tap_tells_card_lines_from_the_rest_of_a_request():
    request = {"messages": [{"role": "user", "content": (
        '## NARRATION\nE7 arrive.\n\n## CANDIDATES\nE7 · character · "Le passeur"\n'
        "\n## SCENE\npresent: E7"
    )}]}  # fmt: skip
    tap = Tap("scene", calls=[Call("identity", request, '{"mentions": []}')])
    assert tap.card_lines() == ['E7 · character · "Le passeur"']
    assert "E7 arrive." in tap.texts() and '{"mentions": []}' in tap.texts()


async def test_a_cheap_only_directory_is_not_called_a_cascade(
    tmp_path, test_pool, monkeypatch
):
    monkeypatch.setenv("TEST_DATABASE_URL", TEST_DB_URL)
    root = _corpus(tmp_path, V2_SCENE)
    io, out = tmp_path / "io", tmp_path / "out"
    cheap = ["--tier", "cheap"]
    assert await _main(_v2_args(root, *cheap, "--emit-prompts", str(io))) == 0
    first = json.loads((io / f"{TOKEN}.1.json").read_text("utf-8"))
    answer = _first_pass(first["messages"][0]["content"])
    (io / f"{TOKEN}.1.txt").write_text(json.dumps(answer), "utf-8")
    args = _v2_args(
        root, *cheap, "--import-responses", str(io), "--responder",
        "subagent:claude-haiku", "--out", str(out), "--iterations", "20",
    )  # fmt: skip
    assert await _main(args) == 0
    (report,) = out.glob("*.json")
    note = json.loads(report.read_text("utf-8"))["header_note"]
    assert eval_identity.CHEAP_NOTE in note
    assert eval_identity.CHEAP_REPLAY_NOTE not in note
