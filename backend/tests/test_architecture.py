"""Architecture guards: layer dependency rule and no SQL in API routes."""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {"tests", "scripts"}

LAYER_RULES = {  # layer -> top-level packages it must not import
    "domain": {"api", "pipeline", "services", "repos", "kg", "llm", "fastapi", "starlette",
               "asyncpg", "anthropic", "mistralai", "openai"},
    "pipeline": {"api", "fastapi", "starlette"},
    "services": {"api", "pipeline"},
    "repos": {"api", "pipeline"},
    "llm": {"api", "pipeline"},
    "kg": {"api", "pipeline"},
    "schema": {"api", "pipeline"},
    "prompts": {"api", "pipeline"},
}
KNOWN_VIOLATIONS = {("services/llm_service.py", "api")}        # removed in Task 3
SQL_IN_ROUTES_ALLOWED = {"_resolve_user_api_key", "_handle_chat"}  # emptied in Task 2

_SQL_RE = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


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


def collect_violations():
    violations = set()
    for path, rel in _source_files():
        forbidden = LAYER_RULES.get(rel.parts[0])
        if not forbidden or len(rel.parts) < 2:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for package in set(_imported_packages(tree)) & forbidden:
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
        skipped = {id(n) for n in ast.walk(func) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   for n in _docstring_nodes(n)}
        for child in ast.walk(func):
            if (isinstance(child, ast.Constant) and isinstance(child.value, str)
                    and id(child) not in skipped and _SQL_RE.match(child.value)):
                names.add(func.name)
                break
    return names


def test_layers_respect_the_dependency_rule():
    assert collect_violations() == KNOWN_VIOLATIONS   # a new one fails; a fixed one must be removed here


def test_no_sql_in_api_routes():
    assert functions_with_sql("api/routes.py") == SQL_IN_ROUTES_ALLOWED
