"""Architecture guards: layer dependency rule and no SQL in API routes."""

import ast
import re

import pytest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {"tests", "scripts"}

LAYER_RULES = {  # layer -> top-level packages it must not import
    "domain": {"api", "pipeline", "services", "repos", "kg", "llm", "fastapi", "starlette",
               "asyncpg", "anthropic", "mistralai", "openai"},
    # pipeline may import workers (pipeline/director_runs.py, pipeline/steps/schedule.py): not forbidden.
    "pipeline": {"api", "fastapi", "starlette"},
    "services": {"api", "pipeline", "fastapi", "starlette"},
    "repos": {"api", "pipeline", "services", "kg", "fastapi", "starlette"},
    "llm": {"api", "pipeline", "services", "fastapi", "starlette"},
    "kg": {"api", "pipeline", "services", "fastapi", "starlette"},
    "schema": {"api", "pipeline", "packs", "fastapi", "starlette"},
    "prompts": {"api", "pipeline", "services", "fastapi", "starlette"},
    "packs": {"api", "pipeline", "services", "repos", "kg", "llm", "prompts", "fastapi", "starlette"},
    "api": {"main"},   # api/ gets the pool through dependencies, never from the app module
    "utils": {"fastapi", "starlette"},
    "workers": {"api", "pipeline", "services", "repos", "kg", "llm", "schema", "prompts",
                "asyncpg", "fastapi", "starlette"},
    "evals": {"api", "pipeline", "fastapi", "starlette"},  # offline evaluation code (P6 identity corpus)
}
# HTTP adapters that live outside api/ by design: exempt from LAYER_RULES.
LAYER_EXEMPT_FILES = {"utils/rate_limit.py"}  # request rate limiter (auth, enhance, chat)
KNOWN_VIOLATIONS: set[tuple[str, str]] = {   # (path relative to backend/, imported package): frozen debt, may only shrink
    ("api/dependencies.py", "main"),                   # lot H task 3
    ("kg/item_writes.py", "services"),                 # lot H task 3: services.identity.types moves to domain
    ("kg/populator.py", "services"),                   # #108: services.identity.service
    ("kg/refs.py", "services"),                        # lot H task 3 (identity.types) and #108 (identity.service)
    ("kg/specialized_populator.py", "services"),       # lot H task 3 (identity.types, aliases) and #108 (identity.classify)
    ("llm/session.py", "services"),                    # #172
    ("llm/usage.py", "services"),                      # #172
    ("packs/loader.py", "services"),                   # #169: normalisation moves with the packs work
    ("prompts/mechanical_prompt.py", "services"),      # P7 (#101): services.engine
    ("prompts/narrator_prompt.py", "services"),        # P7 (#101): services.engine
    ("prompts/world_enhance_prompt.py", "services"),   # P7 (#101): services.engine
    ("prompts/world_generation_prompt.py", "services"),  # P7 (#101): services.engine
    ("repos/games.py", "kg"),                          # #108
    ("repos/llm_models.py", "services"),               # #172: services.pricing
    ("repos/turns.py", "kg"),                          # lot H task 2
    ("repos/turns.py", "services"),                    # lot H task 2
    ("schema/narration.py", "packs"),                  # #169
}
SQL_IN_API_ALLOWED: set[str] = {   # api/ files still holding SQL: frozen debt, may only shrink
    "api/auth.py",          # #108
    "api/dependencies.py",  # #108
    "api/genres.py",        # #108
    "api/tooltips.py",      # #108
    "api/world.py",         # #108
}

_SQL_LEADING_COMMENTS = r"(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*"   # `-- ...` and `/* ... */` before the statement
_SQL_RE = re.compile(
    r"^\s*" + _SQL_LEADING_COMMENTS
    + r"(?:SELECT|INSERT|UPDATE|DELETE|WITH\s+(?:RECURSIVE\s+)?\w+\s*(?:\([^)]*\)\s*)?AS)\b",
    re.IGNORECASE | re.DOTALL,
)


def _source_files():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if rel.parts[0] in EXCLUDED_DIRS:
            continue
        yield path, rel


def _imported_packages(tree):
    """Top-level package of every import in the module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def forbidden_imports(source, forbidden):
    """Forbidden top-level packages imported anywhere in the source, lazy and TYPE_CHECKING imports included."""
    return set(_imported_packages(ast.parse(source))) & forbidden


def collect_violations():
    violations = set()
    for path, rel in _source_files():
        forbidden = LAYER_RULES.get(rel.parts[0])
        if not forbidden or len(rel.parts) < 2 or rel.as_posix() in LAYER_EXEMPT_FILES:
            continue
        for package in forbidden_imports(path.read_text(encoding="utf-8"), forbidden):
            violations.add((rel.as_posix(), package))
    return violations


def _docstring_nodes(func):
    first = func.body[0] if func.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        yield first.value


def _outermost_functions(tree):
    """Functions not nested in another function (module level and methods)."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef):
            yield from _outermost_functions(node)


def functions_with_sql(relative_path):
    """Names of outermost functions holding a SQL string.

    SQL in a nested function counts for the enclosing function; docstrings are ignored.
    """
    tree = ast.parse((BACKEND / relative_path).read_text(encoding="utf-8"))
    names = set()
    for func in _outermost_functions(tree):
        skipped = {id(doc) for scope in ast.walk(func)
                   if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
                   for doc in _docstring_nodes(scope)}
        for child in ast.walk(func):
            if (isinstance(child, ast.Constant) and isinstance(child.value, str)
                    and id(child) not in skipped and _SQL_RE.match(child.value)):
                names.add(func.name)
                break
    return names


def test_layer_rules_name_existing_packages():
    missing = {layer for layer in LAYER_RULES if not (BACKEND / layer).is_dir()}
    assert not missing, f"LAYER_RULES keys that are not backend directories (typo?): {sorted(missing)}"


def test_evals_layer_is_guarded():
    scanned = {rel.as_posix() for _, rel in _source_files()}
    assert "evals/identity/corpus.py" in scanned   # evals/ is not excluded from the scan
    assert {"api", "pipeline"} <= LAYER_RULES["evals"]


def test_lazy_and_type_checking_imports_are_detected():
    source = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    import services.x\n"
        "def f():\n    from main import pool\n    return pool\n"
    )
    assert forbidden_imports(source, {"main", "services", "api"}) == {"main", "services"}


def test_layers_respect_the_dependency_rule():
    new = collect_violations() - KNOWN_VIOLATIONS
    assert not new, f"new layer violations (do not add to KNOWN_VIOLATIONS): {sorted(new)}"


def test_known_violations_are_still_real():
    fixed = KNOWN_VIOLATIONS - collect_violations()
    assert not fixed, f"remove the fixed entry from KNOWN_VIOLATIONS: {sorted(fixed)}"


def _api_files_with_sql():
    return {rel.as_posix() for _, rel in _source_files()
            if rel.parts[0] == "api" and len(rel.parts) == 2 and functions_with_sql(rel)}


def test_no_sql_in_api():
    new = _api_files_with_sql() - SQL_IN_API_ALLOWED
    assert not new, f"SQL in api/ files (move it to repos/): {sorted(new)}"


def test_sql_in_api_allowed_is_still_real():
    fixed = SQL_IN_API_ALLOWED - _api_files_with_sql()
    assert not fixed, f"remove the fixed entry from SQL_IN_API_ALLOWED: {sorted(fixed)}"


def test_handle_chat_is_thin():
    tree = ast.parse((BACKEND / "api/routes.py").read_text(encoding="utf-8"))
    func = next(f for f in _outermost_functions(tree) if f.name == "_handle_chat")
    assert func.end_lineno is not None
    assert func.end_lineno - func.lineno + 1 < 80


@pytest.mark.parametrize("text, is_sql", [
    ("SELECT 1", True),
    ("  select * from t", True),
    ("WITH x AS (SELECT 1) SELECT * FROM x", True),
    ("WITH RECURSIVE r(n) AS (SELECT 1) SELECT n FROM r", True),
    ("-- c\nSELECT 1", True),
    ("/* c */ DELETE FROM t", True),
    ("hello world", False),
    ("with great power", False),
])
def test_sql_regex(text, is_sql):
    assert bool(_SQL_RE.match(text)) == is_sql


def test_layer_exempt_files_exist():
    missing = {f for f in LAYER_EXEMPT_FILES if not (BACKEND / f).is_file()}
    assert not missing, f"LAYER_EXEMPT_FILES entries that do not exist: {sorted(missing)}"
