"""Language and genre packs: schema, fallback and synchronisation to lang_packs (#152)."""

import pytest
import yaml
from pydantic import ValidationError

from packs.loader import (
    PACKS_DIR,
    GenreIdentity,
    LangPack,
    PackNotFound,
    all_negative_answers,
    available_langs,
    load_genre,
    load_lang,
    misnamed_packs,
    norm_params,
    sync_lang_packs,
)


def _raw(lang: str) -> dict:
    return yaml.safe_load(
        (PACKS_DIR / "lang" / f"{lang}.yaml").read_text(encoding="utf-8")
    )


def test_fr_and_en_packs_load_and_validate():
    assert {"fr", "en"} <= set(available_langs())
    fr, en = load_lang("fr"), load_lang("en")
    assert fr.lang == "fr" and en.lang == "en"
    assert fr.proper_name_uses_capitals and fr.min_distinctive_token_len >= 1
    assert len(fr.stop_words) >= 100
    assert fr.prompt_examples.identity and en.prompt_examples.identity
    assert set(norm_params(fr)) == {
        "articles",
        "elisions",
        "ordinal_markers",
        "apostrophes",
    }


def test_missing_key_is_a_validation_error():
    raw = _raw("fr")
    LangPack.model_validate(raw)
    for key in ("articles", "pronouns", "proper_name_uses_capitals", "prompt_examples"):
        broken = {k: v for k, v in raw.items() if k != key}
        with pytest.raises(ValidationError):
            LangPack.model_validate(broken)
    with pytest.raises(ValidationError):
        LangPack.model_validate({**raw, "unknown_key": []})


def test_unknown_language_raises_pack_not_found():
    with pytest.raises(PackNotFound):
        load_lang("xx")
    with pytest.raises(PackNotFound):
        load_lang("../lang/fr")


def test_genre_falls_back_to_neutral():
    neutral = load_genre(None)
    assert neutral.slug == "_neutral"
    assert neutral.identity.titles_extra == []
    assert load_genre("no_such_genre").slug == "_neutral"


async def test_sync_lang_packs_is_idempotent(test_pool):
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM lang_packs")
        await conn.execute(
            "INSERT INTO lang_packs (lang, version, params) VALUES ('fr', 'old', '{}')"
        )
        first = await sync_lang_packs(conn)
        rows = await conn.fetch(
            "SELECT lang, version, params FROM lang_packs ORDER BY lang"
        )
        second = await sync_lang_packs(conn)
        again = await conn.fetch(
            "SELECT lang, version, params FROM lang_packs ORDER BY lang"
        )
    assert first == second == len(available_langs())
    assert [dict(r) for r in rows] == [dict(r) for r in again]
    by_lang = {r["lang"]: r for r in again}
    assert by_lang["fr"]["version"] == load_lang("fr").version
    assert by_lang["fr"]["params"] == norm_params(load_lang("fr"))


@pytest.mark.parametrize(
    "key, entry",
    [
        ("articles", "de la"),
        ("titles", "grand maitre"),
        ("ordinal_markers", "numero de"),
        ("articles", " "),
        ("stop_words", ""),
        ("reveal_cues", "  "),
    ],
)
def test_entries_the_code_cannot_match_are_rejected(key, entry):
    raw = _raw("fr")
    with pytest.raises(ValidationError, match=key):
        LangPack.model_validate({**raw, key: [*raw[key], entry]})


def test_genre_titles_extra_must_be_single_words():
    with pytest.raises(ValidationError):
        GenreIdentity(titles_extra=["grand pater"])


def test_norm_params_are_folded_and_longest_first():
    params = norm_params(load_lang("fr"))
    assert params["ordinal_markers"][0] == "numero"
    assert all(e == e.lower() for e in params["articles"])
    lengths = [len(e) for e in params["elisions"]]
    assert lengths == sorted(lengths, reverse=True)


def test_negative_answers_gather_every_pack():
    assert {"non", "aucune", "no"} <= all_negative_answers()


def test_pack_files_are_well_named():
    assert misnamed_packs() == []
