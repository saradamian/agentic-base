"""The demo demonstrates the trap, from the installed package, with nothing else at hand."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agentic_base.demo import main

ROOT = Path(__file__).resolve().parents[1]


def test_the_demo_prints_the_naive_number_beside_the_checked_verdict(capsys) -> None:
    code = main()

    out = capsys.readouterr().out
    assert code == 0, "the demonstration succeeded; the 1 it prints is the check's"
    assert "with-planner  12/14 = 85.7%" in out
    assert "baseline: assessed 20; excluded 1 (1 timeout); analysed 19" in out
    assert "with-planner: assessed 20; excluded 6 (6 timeout); analysed 14" in out
    assert "not sound: timeout: 30.0% (with-planner) vs 5.0% (baseline)" in out
    assert "outcomes: 33 name a citable scorer" in out
    assert "exit code 1" in out


def test_python_dash_m_runs_the_demo_as_the_readme_says() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agentic_base.demo"],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "not sound: timeout" in result.stdout


def test_the_demo_ships_inside_the_package_not_under_examples() -> None:
    """The reader it exists for has no checkout, so the module must travel in the wheel.

    Being under `src/agentic_base/` is what setuptools' src-layout discovery ships, and being
    in `PORTABLE_MODULES` is what makes the release gate import it out of the built wheel on
    the consumer floor (`scripts/check_wheel_imports.py`)."""
    from tests.test_portable_surface import PORTABLE_MODULES

    assert (ROOT / "src" / "agentic_base" / "demo.py").is_file()
    assert "agentic_base.demo" in PORTABLE_MODULES
