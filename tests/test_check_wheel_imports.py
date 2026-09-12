"""The release job's wheel check is itself a guard, so it gets the treatment every guard here gets.

`scripts/check_wheel_imports.py` reads the portable surface out of `tests/test_portable_surface.py`
by parsing the file. That coupling is deliberate, one list rather than two, and it is also the
thing most likely to break silently: a rename of `PORTABLE_MODULES` or a move to a different
shape would surface only when a release is being cut, which is the worst moment. Coverage is
measured on `src/` alone, so nothing else would notice first.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_wheel_imports.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_wheel_imports", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_checker_reads_the_same_surface_the_suite_declares() -> None:
    from tests import test_portable_surface

    module = _load()
    assert module.portable_modules() == test_portable_surface.PORTABLE_MODULES
    assert len(module.portable_modules()) > 0


def test_a_declaration_the_checker_cannot_find_is_an_error_not_an_empty_surface(
    tmp_path: Path,
) -> None:
    module = _load()
    decoy = tmp_path / "test_portable_surface.py"
    decoy.write_text("SOMETHING_ELSE = ('agentic_base.client',)\n")
    with pytest.raises(SystemExit, match="PORTABLE_MODULES"):
        module.portable_modules(decoy)


def test_every_declared_module_imports_from_source_so_a_red_release_means_the_wheel() -> (
    None
):
    """If a module fails to import from the source tree, the release check would fail for a
    reason that has nothing to do with packaging, and the message would point at the wheel."""
    module = _load()
    rc = module.main(["check_wheel_imports.py", sys.executable])
    assert rc == 0
