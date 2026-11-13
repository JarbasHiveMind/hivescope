"""The shipped templates are a tested contract, not documentation.

``templates/`` is the paved path: users copy those files into their own
repo and run them. Round 2 of the audit found two of them could never pass
(``c[1]`` on a dataclass, ``direction="inbound"`` against recorded ``"in"``),
which means nobody had ever executed them.

This module imports every template and runs each of its test functions
against the in-process harness. Functions carrying ``@pytest.mark.xfail``
are imported but not executed: they document upstream gaps on purpose.
"""
import importlib.util
import inspect
import pathlib

import pytest

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"

TEMPLATE_FILES = sorted(TEMPLATES_DIR.glob("test_template_*.py"))


def _load(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(f"_hivescope_tpl_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_xfail(func) -> bool:
    return any(mark.name == "xfail"
               for mark in getattr(func, "pytestmark", []))


def _skip_reason(func):
    """Return the reason a skipif marker would skip *func*, else None."""
    for mark in getattr(func, "pytestmark", []):
        if mark.name != "skipif":
            continue
        condition = mark.args[0] if mark.args else False
        if condition:
            return mark.kwargs.get("reason", "skipif condition is true")
    return None


def test_templates_directory_is_not_empty():
    """A refactor that moves or renames the templates must not silently
    turn this whole module into zero collected cases."""
    assert len(TEMPLATE_FILES) >= 10, (
        f"expected the shipped templates in {TEMPLATES_DIR}, found "
        f"{[p.name for p in TEMPLATE_FILES]}"
    )


@pytest.mark.parametrize("path", TEMPLATE_FILES, ids=lambda p: p.stem)
def test_template_imports(path):
    """Every template imports cleanly — no stale helper names or signatures."""
    module = _load(path)
    functions = [n for n in dir(module) if n.startswith("test_")]
    assert functions, f"{path.name} defines no test function"


def _cases():
    for path in TEMPLATE_FILES:
        module = _load(path)
        for name, func in sorted(vars(module).items()):
            if not name.startswith("test_") or not inspect.isfunction(func):
                continue
            yield pytest.param(func, id=f"{path.stem}::{name}")


@pytest.mark.parametrize("func", list(_cases()))
def test_template_runs(func):
    """Run each non-xfail template test body against the harness."""
    if _is_xfail(func):
        pytest.skip("template documents a pending upstream feature (xfail)")
    reason = _skip_reason(func)
    if reason:
        pytest.skip(reason)
    func()
