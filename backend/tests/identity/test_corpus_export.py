"""Skeleton export of real games for the identity corpus: pure conversion (#151)."""

import yaml

from evals.identity.corpus import Scene
from evals.identity.lexicon import load_lexicon
from scripts.identity_corpus_export import (
    DUMP_SQL,
    build_scene,
    context_to_mentions,
    entity_id,
    fetch_dump,
    main,
    slugify,
    surfaces_only,
    unresolved_canonicals,
)

TURN_1 = (
    "Une Kethari âgée attend. Le Kethari au tablier pose son terminal sous sa paume."
)
TURN_2 = "Il attend. La Kethari âgée se lève. Pervenche se tait."


def _dump() -> dict:
    return {
        "game": {"id": "f134", "name": "Relais", "character_data": None},
        "registry": [{"entity_type": "protagonist", "name": "Valentin"}],
        "companions": [{"name": "Pervenche", "voice": "basse"}],
        "characters": [
            {
                "id": "c1",
                "name": "Tesk Vahrun-Oo",
                "descriptor": "Le Kethari au tablier",
                "known_by_protagonist": False,
                "occupation": "gérant",
                "workplace_id": "l1",
            },
            {
                "id": "c2",
                "name": "Kethari âgée",
                "descriptor": "La Kethari âgée",
                "known_by_protagonist": False,
            },
        ],
        "locations": [{"id": "l1", "name": "Cantine du Puits"}],
        "organizations": [],
        "objects": [{"id": "o1", "name": "Terminal personnel"}],
        "arcs": [{"title": "Cargaison manquante"}],
        "messages": [
            {"role": "user", "content": "__ARRIVEE__"},
            {
                "role": "assistant",
                "content": TURN_1,
                "location_id": "l1",
                "narrator_context": [
                    [0, 16, "Kethari âgée", "character"],
                    [25, 46, "Le Kethari de la cantine", "character"],
                    [70, 78, "Le Kethari de la cantine", "character"],
                ],
            },
            {"role": "user", "content": "Bonjour"},
            {
                "role": "assistant",
                "content": TURN_2,
                "location_id": "l1",
                "narrator_context": [
                    [0, 2, "Tesk Vahrun-Oo", "character"],
                    [11, 26, "La Kethari âgée", "character"],
                    [11, 22, "La Kethari âgée", "character"],
                    [36, 45, "Pervenche", "character"],
                ],
                "entity_reveals": [
                    {"current_name": "La Kethari âgée", "real_name": "Nahle Irun-Sa"}
                ],
            },
        ],
    }


def test_slug_drops_article_accents_and_punctuation():
    fr = load_lexicon("fr")
    assert slugify("La Kethari âgée", fr) == "kethari_agee"
    assert slugify("L'audit de la Serre Quatre", fr) == "audit_de_la_serre_quatre"
    assert entity_id("location", "Hall d'Arrivée Quai Sud", fr) == (
        "location_hall_d_arrivee_quai_sud"
    )


def test_context_spans_become_history_mentions_to_review():
    index = {("character", "kethari_agee"): "character_kethari_agee"}
    text = TURN_2
    context = _dump()["messages"][3]["narrator_context"]
    mentions = context_to_mentions(text, context, index, load_lexicon("fr"))
    # the pronoun « Il » is dropped; of two spans at one start the longest is kept
    assert [(m["surface"], m["expected"]) for m in mentions] == [
        ("La Kethari âgée", "MATCH character_kethari_agee"),
        ("Pervenche", "MATCH character_pervenche"),
    ]


def test_skeleton_scene_is_loadable_and_carries_the_history():
    scene = build_scene(_dump(), 2, "f134", genre="sf")
    Scene.model_validate(scene)  # the shape is right; the gold is left to the annotator
    assert scene["id"] == "real-f134-t02"
    assert (scene["genre"], scene["language"]) == ("sf", "fr")
    assert scene["campaign"] == "real-f134"
    assert scene["narration"] == TURN_2
    assert scene["gold"] == []
    assert [h["text"] for h in scene["history"]] == [TURN_1]
    ids = {e["id"] for e in scene["world"]}
    assert {
        "protagonist_valentin",
        "companion_pervenche",
        "arc_cargaison_manquante",
    } <= ids
    tesk = next(e for e in scene["world"] if e["id"] == "character_tesk_vahrun_oo")
    assert tesk["location"] == "location_cantine_du_puits"
    assert tesk["last_seen_turn"] is None  # only tagged under an invented canonical
    assert {"ref": "La Kethari âgée", "real_name": "Nahle Irun-Sa"} in scene["scene"][
        "reveals"
    ]
    assert {
        "ref": "character_tesk_vahrun_oo",
        "kind": "name",
        "state": "unknown",
        "text": "Tesk Vahrun-Oo",
    } in scene["gold_knowledge"]


def test_invented_canonicals_are_reported():
    assert unresolved_canonicals(_dump(), load_lexicon("fr")) == [
        "Le Kethari de la cantine (character)"
    ]


def test_surfaces_only_keeps_no_decision():
    scene = {
        "id": "s",
        "narration": "x",
        "gold": [{"surface": "x", "start": 0, "category": "EASY", "expected": "SKIP"}],
    }
    assert surfaces_only(scene) == {
        "id": "s",
        "narration": "x",
        "mentions": [{"surface": "x", "start": 0}],
    }


def test_export_never_overwrites_an_annotated_scene(tmp_path):
    import json

    dump = tmp_path / "dump.json"
    dump.write_text(json.dumps(_dump()), encoding="utf-8")
    game = "f1340000-0000-0000-0000-000000000000"
    args = ["--from-json", str(dump), "--game", game, "--out", str(tmp_path),
            "--genre", "dark_fantasy"]  # fmt: skip
    assert main(args) == 0
    path = tmp_path / "real-f134-t01.yaml"
    exported = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert (exported["narration"], exported["genre"]) == (TURN_1, "dark_fantasy")
    path.write_text("annotated", encoding="utf-8")
    main(args)
    assert path.read_text(encoding="utf-8") == "annotated"


def test_the_dump_is_read_only():
    assert DUMP_SQL.startswith("SET default_transaction_read_only = on;")


class _FakeConnection:
    def __init__(self):
        self.calls: list[str] = []

    async def execute(self, sql):
        self.calls.append(sql)

    async def fetch(self, sql, *args):
        self.calls.append(sql)
        return []

    async def close(self):
        self.calls.append("close")


async def test_the_live_export_sets_read_only_before_any_query(monkeypatch):
    import sys
    import types

    conn = _FakeConnection()

    async def connect(url):
        return conn

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=connect))
    await fetch_dump("postgresql://x", "f1340000-0000-0000-0000-000000000000")
    assert conn.calls[0] == "SET default_transaction_read_only = on"
    assert len(conn.calls) > 2 and conn.calls[-1] == "close"


def test_a_dump_without_protagonist_is_refused():
    import pytest

    dump = _dump()
    dump["registry"] = []
    with pytest.raises(ValueError):
        build_scene(dump, 1, "f134", genre="sf")


async def test_the_dump_spans_come_from_the_stored_mentions(test_pool):
    """Both dump queries (live export, psql script) on a real schema: a message's spans
    are its stored mentions, [start, end, registry name, type] in text order."""
    import json

    from tests.conftest import TEST_DB_URL
    from tests.characterization.test_c19_legacy import (
        IDENTITY_MIGRATION,
        _legacy_spans,
        load_legacy_game,
    )

    game_id, _ = await load_legacy_game(
        test_pool, before={IDENTITY_MIGRATION: _legacy_spans}
    )
    expected = [
        [0, 5, "Ossek", "character"],
        [14, 29, "Escale Méridienne", "location"],
        [30, 38, "Célimène", "companion"],
    ]
    live = await fetch_dump(TEST_DB_URL, game_id)
    select = DUMP_SQL.replace("{game}", game_id).split("SELECT json_build_object", 1)[1]
    async with test_pool.acquire() as conn:
        raw = await conn.fetchval("SELECT json_build_object" + select.rstrip().rstrip(";"))
    scripted = json.loads(raw) if isinstance(raw, str) else raw
    for dump in (live, scripted):
        spans = [m["narrator_context"] for m in dump["messages"] if m["narrator_context"]]
        assert spans == [expected]
