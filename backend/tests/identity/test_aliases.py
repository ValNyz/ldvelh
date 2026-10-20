"""Deterministic alias derivation and the proper-name heuristic, driven by the packs (#152)."""

import pytest

from packs.loader import GenreIdentity, GenrePack, load_genre, load_lang
from services.identity import lexicon as lexicon_mod
from domain.identity import AliasSpec
from services.identity.aliases import derive
from services.identity.lexicon import Lexicon
from services.identity.normalize import Normalizer


def _tools(lang: str = "fr", genre: GenrePack | None = None):
    pack = load_lang(lang)
    return Normalizer(pack), Lexicon(pack, genre or load_genre(None))


def test_derive_aliases_for_a_proper_name():
    normalizer, lexicon = _tools()
    aliases = derive(
        "Dr. Elara Voss",
        kind="true_name",
        known=True,
        normalizer=normalizer,
        lexicon=lexicon,
    )
    by_text = {a.text: a.kind for a in aliases}
    assert by_text == {
        "Dr. Elara Voss": "true_name",
        "Elara Voss": "title",
        "Voss": "short",
        "Elara": "short",
    }
    assert all(a.known and not a.secret for a in aliases)
    norms = [normalizer.norm(a.text) for a in aliases]
    assert len(norms) == len(set(norms))
    assert (
        derive(
            "Dr. Elara Voss",
            kind="true_name",
            known=True,
            normalizer=normalizer,
            lexicon=lexicon,
        )
        == aliases
    )


def test_derive_aliases_for_a_descriptor():
    normalizer, lexicon = _tools()
    aliases = derive(
        "La Kethari âgée",
        kind="descriptor",
        known=False,
        normalizer=normalizer,
        lexicon=lexicon,
    )
    assert aliases and all(a.kind == "descriptor" and a.known for a in aliases)
    # With and without the determiner: both surfaces reach an alias by their norm.
    norms = {normalizer.norm(a.text) for a in aliases}
    assert normalizer.norm("Kethari âgée") in norms
    assert normalizer.norm("la Kethari âgée") in norms
    assert len(norms) == len(aliases)


def test_true_name_aliases_are_unknown_until_revealed():
    normalizer, lexicon = _tools()
    hidden = derive(
        "Nahle Irun-Sa",
        kind="true_name",
        known=False,
        secret=True,
        normalizer=normalizer,
        lexicon=lexicon,
    )
    assert {a.text for a in hidden} == {"Nahle Irun-Sa", "Irun-Sa", "Nahle"}
    assert all(not a.known and a.secret for a in hidden)
    assert hidden[0] == AliasSpec("Nahle Irun-Sa", "true_name", False, True)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Tesk Vahrun-Oo", True),
        ("Cheffe de serre", False),
        ("Un client en bleu de travail", False),
        ("Pervenche", True),
        ("Dr. Elara Voss", True),
        ("l'Ordre des Veilleurs", False),
    ],
)
def test_looks_like_proper_name(text, expected):
    normalizer, lexicon = _tools()
    assert normalizer.looks_like_proper_name(text, lexicon) is expected


def test_looks_like_proper_name_reads_the_language_pack():
    normalizer, lexicon = _tools("en")
    assert normalizer.looks_like_proper_name("The Old Mill", lexicon) is False
    assert normalizer.looks_like_proper_name("Rafe Collins", lexicon) is True


def test_genre_titles_extra_are_stripped():
    genre = GenrePack(slug="test_genre", identity=GenreIdentity(titles_extra=["pater"]))
    normalizer, lexicon = _tools(genre=genre)
    assert normalizer.strip_title("Pater Ondrev", lexicon) == "Ondrev"
    aliases = derive(
        "Pater Ondrev Kessel",
        kind="true_name",
        known=True,
        normalizer=normalizer,
        lexicon=lexicon,
    )
    assert "Ondrev Kessel" in {a.text for a in aliases if a.kind == "title"}
    assert "Pater" not in {a.text for a in aliases}
    _, neutral = _tools()
    assert normalizer.strip_title("Pater Ondrev", neutral) == "Pater Ondrev"


def test_tokens_leave_out_stop_words_titles_and_short_tokens():
    normalizer, lexicon = _tools()
    assert normalizer.tokens("Le docteur Ondrev de la Tour", lexicon) == [
        "ondrev",
        "tour",
    ]


def test_genre_prompt_examples_replace_the_language_ones():
    pack = load_lang("fr")
    assert (
        Lexicon(pack, load_genre(None)).prompt_examples == pack.prompt_examples.identity
    )
    genre = GenrePack(
        slug="g",
        identity=GenreIdentity(
            prompt_examples={"identity": [{"input": "x", "output": "y"}]}
        ),
    )
    assert [e.input for e in Lexicon(pack, genre).prompt_examples] == ["x"]


def test_for_game_falls_back_to_the_neutral_genre():
    lexicon = lexicon_mod.for_game("fr", "no_such_genre")
    assert lexicon.genre.slug == "_neutral"


def test_a_label_gives_a_label_alias():
    normalizer, lexicon = _tools()
    aliases = derive(
        "Bureau des Résidences",
        kind="label",
        known=True,
        normalizer=normalizer,
        lexicon=lexicon,
    )
    assert [(a.text, a.kind) for a in aliases] == [
        ("Bureau des Résidences", "label"),
        ("Résidences", "short"),
        ("Bureau", "short"),
    ]


def test_an_elided_word_is_split_off_a_short_alias():
    normalizer, lexicon = _tools()
    aliases = derive(
        "Maison d'Ombelle",
        kind="label",
        known=True,
        normalizer=normalizer,
        lexicon=lexicon,
    )
    assert {a.text for a in aliases if a.kind == "short"} == {"Ombelle", "Maison"}


def test_tokens_split_off_elided_words():
    normalizer, lexicon = _tools()
    assert normalizer.tokens("Le chef de l'Ordre d'Ombelle", lexicon) == [
        "chef",
        "ordre",
        "ombelle",
    ]
    # Stop words written with an apostrophe are split off too.
    assert normalizer.tokens("Jusqu'au quai qu'Ondrev garde", lexicon) == [
        "quai",
        "ondrev",
        "garde",
    ]


def test_strip_title_skips_a_leading_article():
    genre = GenrePack(slug="test_genre", identity=GenreIdentity(titles_extra=["pater"]))
    normalizer, lexicon = _tools(genre=genre)
    assert normalizer.strip_title("Le Pater Ondrev", lexicon) == "Ondrev"
    assert normalizer.strip_title("Le Byte Bar", lexicon) == "Le Byte Bar"
    aliases = derive(
        "Le Pater Ondrev",
        kind="true_name",
        known=True,
        normalizer=normalizer,
        lexicon=lexicon,
    )
    assert ("Ondrev", "title") in {(a.text, a.kind) for a in aliases}
