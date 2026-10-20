"""#168: the former repos <-> kg <-> services.identity cycle is gone.

Each module of the former cycle imports alone, in a fresh interpreter, and none of them
breaks a cycle with an import placed inside a function.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

FORMER_CYCLE_MODULES = (
    "repos.uow",
    "repos.turns",
    "kg.populator",
    "kg.specialized_populator",
    "kg.item_writes",
    "kg.refs",
    "services.identity.service",
)
# Modules a function-level import used to reach lazily to break the cycle.
CYCLE_TARGETS = {
    "repos.uow",
    "repos.turns",
    "kg.populator",
    "services.identity.service",
}


@pytest.mark.parametrize("module", FORMER_CYCLE_MODULES)
def test_each_module_of_the_former_cycle_imports_alone(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def _function_level_imports(tree):
    """Full dotted names imported inside a function (methods and nested ones included)."""
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                yield node.module
                # `from kg import populator` reaches kg.populator.
                yield from (f"{node.module}.{alias.name}" for alias in node.names)


def test_no_lazy_import_breaks_a_cycle_in_the_former_cycle_modules():
    lazy = {}
    for module in FORMER_CYCLE_MODULES:
        path = BACKEND / (module.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = set(_function_level_imports(tree)) & CYCLE_TARGETS
        if found:
            lazy[module] = sorted(found)
    assert not lazy, f"function-level imports of the former cycle: {lazy}"


def test_api_modules_import_without_main():
    code = "import sys, api.dependencies; sys.exit('main' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
