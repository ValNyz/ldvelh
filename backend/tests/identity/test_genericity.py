"""No language, genre or universe rule in the identity code: words live in the packs,
thresholds in IdentityConfig (spec §4.12, D33-D36, #152)."""

import ast
import re
from pathlib import Path

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
_NARRATOR_OUTPUT = (
    "day_transition values of the narrator's French output: a narrator "
    "language rule, outside identity; narrator languages are P8 (#48)"
)
ALLOWED: dict[tuple[str, str], str] = {
    ("schema/narration.py", "non"): _NARRATOR_OUTPUT,
    ("schema/narration.py", "no"): _NARRATOR_OUTPUT,
}
# English SQL keywords: words of the query language, not of a game's language.
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


def _pack_words() -> set[str]:
    words = set()
    for lang in available_langs():
        raw = yaml.safe_load(
            (PACKS_DIR / "lang" / f"{lang}.yaml").read_text(encoding="utf-8")
        )
        for key, value in raw.items():
            if key not in NON_LEXICAL_KEYS:
                words |= _words(value)
    return words - {""}


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


def _is_word(node: ast.AST, words: set[str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        folded = _fold(node.value)
        return folded if folded in words else None
    return None


# A word between regex alternation delimiters: (?:le|la|les).
_ALTERNATIVE = re.compile(r"(?<=[|(:])([\w'’-]+)(?=[|)])")


def _python_hits(path: Path, rel: str, words: set[str]) -> set[str]:
    """Hits of a module: in identity code every literal equal to a pack word (docstrings
    and f-string fragments aside); everywhere a collection whose items (dict values, not
    keys: those are field names) hold two distinct pack words, i.e. a word list, or a
    regex alternation of two pack words."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    strict = rel.startswith(IDENTITY_CODE)
    skipped = _skipped_nodes(tree)
    hits = set()
    for node in ast.walk(tree):
        if strict and id(node) not in skipped and (word := _is_word(node, words)):
            hits.add(word)
        elif isinstance(node, ast.List | ast.Tuple | ast.Set | ast.Dict):
            items = (
                node.values if isinstance(node, ast.Dict) else node.elts
            )  # keys: field names
            found = {w for item in items if (w := _is_word(item, words))}
            if len(found) >= 2:
                hits |= found
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            alternatives = {_fold(a) for a in _ALTERNATIVE.findall(node.value)} & words
            if len(alternatives) >= 2:
                hits |= alternatives
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


def test_no_language_lexicon_in_code():
    words = _pack_words()
    found = {
        f"{rel}: {sorted(hits)}"
        for path, rel in _python_files()
        if (hits := _python_hits(path, rel, words))
    }
    for path in _identity_sql_files():
        literals = _SQL_QUOTED.findall(
            _sql_without_comments(path.read_text(encoding="utf-8"))
        )
        hits = {_fold(q.replace("''", "'")) for q in literals} & words
        if hits:
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
        tokens = set(re.findall(r"\w+(?:['-]\w+)*'?", body.casefold())) - SQL_KEYWORDS
        if hits := tokens & words:
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
