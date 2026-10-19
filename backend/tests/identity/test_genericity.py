"""No language, genre or universe rule in the identity code: words live in the packs,
thresholds in IdentityConfig (spec §4.12, D33-D36, #152)."""

import ast
import re
from pathlib import Path

import pytest
import yaml

from packs.loader import PACKS_DIR, available_langs

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
# Pack keys that hold words; the others are settings or prose examples.
NON_LEXICAL_KEYS = frozenset(
    {
        "lang",
        "version",
        "apostrophes",
        "proper_name_uses_capitals",
        "min_distinctive_token_len",
        "prompt_examples",
    }
)
EXCLUDED_DIRS = ("packs/", "tests/", "evals/identity/lexicon/")
# Identity code: any literal equal to a pack word is a hard-coded rule.
IDENTITY_CODE = ("services/identity/", "prompts/identity_prompt.py")
# Justified exceptions as (path relative to backend/, folded literal) -> reason.
ALLOWED: dict[tuple[str, str], str] = {}
# English SQL keywords: words of the query language, not of a game's language. Only
# unquoted SQL is filtered with them: quoted literals are text, scanned word by word.
SQL_KEYWORDS = frozenset(
    {
        "as",
        "at",
        "by",
        "for",
        "from",
        "if",
        "in",
        "into",
        "is",
        "not",
        "of",
        "on",
        "or",
        "and",
        "to",
        "with",
        "no",
        "all",
        "any",
    }
)


def _fold(text: str) -> str:
    return text.replace("’", "'").casefold().strip()


def _words(value) -> set[str]:
    if isinstance(value, str):
        return {_fold(value)}
    if isinstance(value, list):
        return set().union(*map(_words, value)) if value else set()
    if isinstance(value, dict):
        return set().union(*map(_words, value.values())) if value else set()
    return set()


def _words_by_pack() -> dict[str, set[str]]:
    by_pack = {}
    for lang in available_langs():
        raw = yaml.safe_load(
            (PACKS_DIR / "lang" / f"{lang}.yaml").read_text(encoding="utf-8")
        )
        words = set()
        for key, value in raw.items():
            if key not in NON_LEXICAL_KEYS:
                words |= _words(value)
        by_pack[lang] = words - {""}
    return by_pack


def _pack_words() -> set[str]:
    return set().union(*_words_by_pack().values())


def _skipped_nodes(tree: ast.AST) -> set[int]:
    """Constants that are not words of a text: docstrings and f-string fragments (prose)."""
    skipped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            skipped |= {id(v) for v in node.values}
        elif (
            isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
        ):
            skipped.add(id(node.body[0].value))
    return skipped


def _field_names(tree: ast.AST) -> set[int]:
    """Single constants that name a field, not a text: dict keys, subscripts (`row["type"]`)
    and the arguments of `Literal[...]` (a subscript too). Their sets are still word lists
    to the collection check."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            names |= {id(k) for k in node.keys if k is not None}
        elif isinstance(node, ast.Subscript):
            index = node.slice
            elts = index.elts if isinstance(index, ast.Tuple) else [index]
            names |= {id(e) for e in elts}
    return names


def _is_word(node: ast.AST, words: set[str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        folded = _fold(node.value)
        return folded if folded in words else None
    return None


# A word between regex alternation delimiters: (?:le|la|les).
_ALTERNATIVE = re.compile(r"(?<=[|(:])([\w'’-]+)(?=[|)])")


def _word_list(items: list, packs: dict[str, set[str]], *, keyed: bool) -> set[str]:
    """Pack words of `items` when they form a word list: two distinct words of one pack. A
    dict's key or value set must also be at least half pack words: a record such as
    `{"type": …, "ms": …}` or a large vocabulary map with a few chance collisions is not a
    word list, `{"monsieur": 1, "madame": 2}` is."""
    texts = {
        _fold(i.value)
        for i in items
        if isinstance(i, ast.Constant) and isinstance(i.value, str)
    }
    hits = set()
    for words in packs.values():
        found = texts & words
        if len(found) >= 2 and (not keyed or 2 * len(found) >= len(texts)):
            hits |= found
    return hits


def _python_hits(
    path: Path, rel: str, words: set[str] | dict[str, set[str]]
) -> set[str]:
    """Hits of a module: in identity code every literal equal to a pack word (docstrings,
    f-string fragments and single field names aside); everywhere a word list (`_word_list`)
    in a list, tuple (`Literal[...]` arguments included), set, dict key set or dict value
    set, or a regex alternation of two pack words."""
    packs = words if isinstance(words, dict) else {"pack": words}
    every_word = set().union(*packs.values())
    tree = ast.parse(path.read_text(encoding="utf-8"))
    strict = rel.startswith(IDENTITY_CODE)
    skipped = _skipped_nodes(tree) | _field_names(tree)
    hits = set()
    for node in ast.walk(tree):
        if strict and id(node) not in skipped and (word := _is_word(node, every_word)):
            hits.add(word)
        elif isinstance(node, ast.Dict):
            hits |= _word_list([k for k in node.keys if k], packs, keyed=True)
            hits |= _word_list(node.values, packs, keyed=True)
        elif isinstance(node, ast.List | ast.Tuple | ast.Set):
            hits |= _word_list(node.elts, packs, keyed=False)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            alternatives = {_fold(a) for a in _ALTERNATIVE.findall(node.value)}
            for pack_words in packs.values():
                if len(alternatives & pack_words) >= 2:
                    hits |= alternatives & pack_words
    return {w for w in hits if (rel, w) not in ALLOWED}


def _python_files():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if not rel.startswith(EXCLUDED_DIRS):
            yield path, rel


def _identity_sql_files() -> list[Path]:
    migrations = REPO / "db" / "migrations"
    return sorted(
        {*migrations.glob("*entity_identity*.sql"), *migrations.glob("*identity*.sql")}
    )


def _sql_without_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


_SQL_QUOTED = re.compile(r"'((?:[^']|'')*)'")
_WORD = re.compile(r"\w+(?:['-]\w+)*'?")


def _sql_literal_words(sql: str) -> set[str]:
    """Every word inside the quoted literals of `sql` (a regex or a default text included)."""
    literals = _SQL_QUOTED.findall(_sql_without_comments(sql))
    return {w for q in literals for w in _WORD.findall(_fold(q.replace("''", "'")))}


def test_no_language_lexicon_in_code():
    words = _pack_words()
    by_pack = _words_by_pack()
    found = {
        f"{rel}: {sorted(hits)}"
        for path, rel in _python_files()
        if (hits := _python_hits(path, rel, by_pack))
    }
    for path in _identity_sql_files():
        if hits := _sql_literal_words(path.read_text(encoding="utf-8")) & words:
            found.add(f"{path.name}: {sorted(hits)}")
    assert found == set()


def test_the_literal_scan_catches_a_word_list_and_a_pattern(tmp_path):
    words = {"le", "la", "les"}
    module = tmp_path / "m.py"
    module.write_text(
        'ARTICLES = ("le", "la")\nPATTERN = r"^(?:le|la|les)\\s"\n'
        'KIND = {"le": 1, "la": 2}\nSINGLE = "la"\n',
        encoding="utf-8",
    )
    assert _python_hits(module, "pipeline/m.py", words) == {"le", "la", "les"}
    assert _python_hits(module, "services/identity/m.py", words) == {"le", "la", "les"}
    module.write_text('SINGLE = "la"\n', encoding="utf-8")
    assert _python_hits(module, "pipeline/m.py", words) == set()
    assert _python_hits(module, "services/identity/m.py", words) == {"la"}


def test_the_strict_scan_lets_field_names_through(tmp_path):
    words = {"type", "client", "le", "la", "les", "monsieur", "madame"}
    module = tmp_path / "m.py"
    module.write_text(
        'SCHEMA = {"type": "object"}\nKIND = row["type"]\nKind = Literal["type"]\n'
        'PAIR = table["type", "id"]\n',
        encoding="utf-8",
    )
    assert _python_hits(module, "services/identity/m.py", words) == set()
    module.write_text(
        'SINGLE = "type"\nSCHEMA = {"kind": "client"}\n', encoding="utf-8"
    )
    assert _python_hits(module, "services/identity/m.py", words) == {"type", "client"}


@pytest.mark.parametrize("rel", ["services/identity/m.py", "pipeline/m.py"])
def test_keyed_word_lists_are_caught(tmp_path, rel):
    words = {"le", "la", "les", "monsieur", "madame"}
    module = tmp_path / "m.py"
    module.write_text(
        'Article = Literal["le", "la", "les"]\nTITLES = {"monsieur": 1, "madame": 2}\n',
        encoding="utf-8",
    )
    assert _python_hits(module, rel, words) == words


def test_the_scan_catches_a_negative_answer_list(tmp_path):
    """The narrator parser's former word list is caught by construction: its words are
    `negative_answers` of the packs."""
    words = _pack_words()
    assert {"non", "aucune", "no"} <= words
    module = tmp_path / "m.py"
    module.write_text(
        'WORDS = frozenset({"", "null", "false", "none", "aucune", "non", "no"})\n',
        encoding="utf-8",
    )
    assert {"aucune", "non"} <= _python_hits(
        module, "schema/narration.py", _words_by_pack()
    )


def test_sql_literal_words_are_scanned_inside_the_literal():
    words = {"no", "inconnu"}
    sql = "SELECT regexp_replace(x, 'no|numero', ''), COALESCE(d, 'Inconnu(e)') -- no"
    assert _sql_literal_words(sql) & words == {"no", "inconnu"}


_SQL_FUNCTION = re.compile(
    r"CREATE (?:OR REPLACE )?FUNCTION\s+(?:\w+\.)?(\w+).*?AS\s+\$(\w*)\$(.*?)\$\2\$",
    re.DOTALL | re.IGNORECASE,
)


def test_sql_identity_functions_contain_no_pack_word():
    words = _pack_words()
    sql = _sql_without_comments(
        (REPO / "db" / "migrations" / "20261020000001_entity_identity.sql").read_text(
            encoding="utf-8"
        )
    )
    bodies = {m.group(1): m.group(3) for m in _SQL_FUNCTION.finditer(sql)}
    assert {"ldvelh_unaccent", "ldvelh_norm", "ldvelh_norm_for_game"} <= set(bodies)
    found = {}
    for name, body in bodies.items():
        unquoted = _SQL_QUOTED.sub(" ", body)
        tokens = set(_WORD.findall(unquoted.casefold())) - SQL_KEYWORDS
        if hits := (tokens | _sql_literal_words(body)) & words:
            found[name] = sorted(hits)
    assert found == {}


def _numbers(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.name}:{node.lineno}: {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) in (int, float)
        and node.value not in (0, 1)
    ]


def test_identity_config_has_no_duplicate_literal_in_candidates_or_decision():
    """Thresholds and bounds come from IdentityConfig: no number other than 0 and 1 in the
    identity service (candidates.py and decision.py included once they exist)."""
    code = sorted((BACKEND / "services" / "identity").glob("*.py"))
    assert code
    assert [n for path in code for n in _numbers(path)] == []
