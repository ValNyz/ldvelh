"""Language data of the identity corpus code lives in lexicon files, never in code (#151)."""

import ast
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.identity.corpus import Scene, load_scenes, load_sequences
from evals.identity.lexicon import LEXICON_DIR, load_lexicon
from tests.identity.test_corpus import ROOT, _custom_errors, _scene

BACKEND = Path(__file__).resolve().parents[2]
# report.py writes the evaluation report for the French-speaking maintainers: its labels
# are presentation text, not language rules of the corpus. Making them configurable is
# tracked apart (review M8); every other module must stay free of language words.
PRESENTATION = frozenset({"report.py"})
CODE = [
    *sorted(
        p
        for p in (BACKEND / "evals" / "identity").glob("*.py")
        if p.name not in PRESENTATION
    ),
    *sorted((BACKEND / "scripts").glob("identity_corpus_*.py")),
]


def _string_literals(path: Path) -> set[str]:
    """String constants of a module, docstrings left out."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


# Lexicon words that are also English words of the code (SQL `= on`, messages).
ENGLISH_COLLISIONS = frozenset({"on", "me", "se", "des"})


def _tokens(literal: str) -> set[str]:
    """Word tokens of a literal, the whole literal included (« l' », « les autres »)."""
    folded = literal.replace("’", "'").casefold()
    return {folded.strip()} | set(re.findall(r"\w+(?:['-]\w+)*'?", folded))


def _lexicon_words() -> set[str]:
    words = set()
    for path in LEXICON_DIR.glob("*.yaml"):
        lexicon = load_lexicon(path.stem)
        words |= lexicon.determiners | lexicon.elided_determiners
        words |= lexicon.personal_pronouns | lexicon.indefinite_pronouns
    return {w.casefold().strip() for w in words}


def test_the_french_lexicon_holds_the_closed_lists():
    fr = load_lexicon("fr")
    assert "quelqu'un" in fr.indefinite_pronouns
    assert "quelqu'un" in fr.unambiguous_pronouns
    assert {"la", "mon", "ces"} <= fr.determiners
    assert "elle" in fr.personal_pronouns
    assert fr.strip_determiner("l’Ordre") == "Ordre"
    assert fr.strip_determiner("la Coopérative") == "Coopérative"


def test_an_unknown_language_is_rejected_at_load():
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(language="xx"))
    assert Scene.model_validate(_scene()).language == "fr"


def test_the_pronoun_rule_reads_the_lexicon_of_the_scene(monkeypatch):
    fr = load_lexicon("fr")
    stripped = fr.model_copy(update={"unambiguous_pronouns": frozenset()})
    monkeypatch.setattr(
        "evals.identity.lexicon._LEXICONS", {"fr": stripped}, raising=False
    )
    assert _custom_errors("Il y a quelqu'un devant toi.", []) == []


def test_identity_code_has_no_language_or_genre_literals():
    words = {w for w in _lexicon_words() if len(w) >= 2} - ENGLISH_COLLISIONS
    genres = {s.genre for s in load_scenes(ROOT)}
    genres |= {t.genre for q in load_sequences(ROOT) for t in q.turns}
    assert len(genres) >= 2
    banned = words | {g.casefold() for g in genres}
    found = {
        f"{path.name}: {literal!r} ({sorted(_tokens(literal) & banned)})"
        for path in CODE
        for literal in _string_literals(path)
        if _tokens(literal) & banned
    }
    assert found == set()


def test_the_literal_scan_sees_words_inside_a_pattern():
    assert {"la", "les"} <= _tokens(r"^(?:le|la|les)\s")
    assert "quelqu'un" in _tokens("quelqu’un est là")
