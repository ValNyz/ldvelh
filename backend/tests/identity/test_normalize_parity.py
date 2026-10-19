"""ldvelh_norm (SQL) and Normalizer.norm (Python) agree on every pack (#152)."""

from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from packs.loader import load_lang, norm_params
from services.identity.normalize import (
    _UNACCENT_RULES,
    Normalizer,
    _parse_unaccent_rules,
    unaccent,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity"


def _lines(lang: str) -> list[str]:
    text = (FIXTURES / f"norm_parity_{lang}.txt").read_text(encoding="utf-8")
    return [line for line in text.split("\n") if line != ""]


def test_parity_files_have_their_size():
    assert len(_lines("fr")) == 200
    assert len(_lines("en")) == 40


@pytest.mark.parametrize("lang", ["fr", "en"])
async def test_sql_and_python_normalization_agree_per_pack(test_pool, lang):
    pack = load_lang(lang)
    normalizer = Normalizer(pack)
    lines = _lines(lang)
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT s, ldvelh_norm(s, $2::text::jsonb) AS n FROM unnest($1::text[]) AS s",
            lines,
            _json(norm_params(pack)),
        )
    sql = {r["s"]: r["n"] for r in rows}
    diverging = {
        s: (sql[s], normalizer.norm(s)) for s in lines if sql[s] != normalizer.norm(s)
    }
    assert diverging == {}


def _json(value) -> str:
    import json

    return json.dumps(value)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("La Kethari âgée", "kethari agee"),
        ("Quai n°9", "quai 9"),
        ("L'Œil", "oeil"),
        ("Dr. Elara Voss", "dr elara voss"),
        ("L’Ordre", "ordre"),
        ("Tesk Vahrun-Oo", "tesk vahrun-oo"),
        ("« Le Byte Bar »", "byte bar"),
        ("Le Le", "le"),
    ],
)
def test_norm_examples_fr(text, expected):
    assert Normalizer(load_lang("fr")).norm(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("The Old Mill", "old mill"),
        ("an Engineer", "engineer"),
        ("Dock No. 4", "dock 4"),
    ],
)
def test_norm_examples_en(text, expected):
    assert Normalizer(load_lang("en")).norm(text) == expected


async def test_norm_examples_match_sql(test_pool):
    fr = load_lang("fr")
    async with test_pool.acquire() as conn:
        out = await conn.fetchval(
            "SELECT ldvelh_norm('La Kethari âgée', $1::text::jsonb)",
            _json(norm_params(fr)),
        )
    assert out == "kethari agee"


async def test_norm_for_game_raises_without_pack(test_pool):
    async with test_pool.acquire() as conn:
        with pytest.raises(asyncpg.RaiseError, match="missing lang pack"):
            await conn.fetchval("SELECT ldvelh_norm_for_game($1, 'La Guilde')", uuid4())


async def test_unaccent_mirror_matches_every_rule_of_the_database(test_pool):
    """The vendored unaccent.rules still matches the database's dictionary, rule by rule."""
    sources = sorted(_parse_unaccent_rules(_UNACCENT_RULES))
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT s, unaccent('unaccent', s) AS u FROM unnest($1::text[]) AS s",
            sources,
        )
    assert len(rows) == len(sources)
    assert {r["s"]: r["u"] for r in rows if r["u"] != unaccent(r["s"])} == {}


@pytest.mark.parametrize("lang", ["fr", "en"])
async def test_pack_entries_fold_alike_in_sql_and_python(test_pool, lang):
    """norm_params sends the entries folded by Python; SQL would fold them the same way."""
    pack = load_lang(lang)
    entries = [*pack.articles, *pack.elisions, *pack.ordinal_markers, *pack.titles]
    async with test_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT s, btrim(ldvelh_norm_fold(s, $2::text::jsonb), ' ') AS f"
            " FROM unnest($1::text[]) AS s",
            entries,
            _json(norm_params(pack)),
        )
    normalizer = Normalizer(pack)
    assert {
        r["s"]: r["f"] for r in rows if r["f"] != normalizer.fold(r["s"]).strip(" ")
    } == {}
