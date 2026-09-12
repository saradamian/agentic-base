"""Import the declared portable surface out of a BUILT wheel, not out of the source tree.

`tests/test_portable_surface.py` checks three properties of that surface, and all three read
`src/`. So they cannot see the class of defect where the tree is correct and the artifact is not:
a subpackage that never ships, a data file outside the package-data globs, a dependency that is
only present because the development environment installs the service extra. Editable installs
mask every one of them, which is why this runs against the wheel in a bare virtual environment
holding nothing but the base dependencies.

The module list is read from the test rather than restated here. Two lists drift; this one cannot.

    check_wheel_imports.py <python-in-a-venv-that-has-the-wheel-installed>

Reports how many modules it imported, so an empty surface reads as a failure rather than as a
silent pass.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

DECLARATION = (
    Path(__file__).resolve().parent.parent / "tests" / "test_portable_surface.py"
)
NAME = "PORTABLE_MODULES"


def portable_modules(source: Path = DECLARATION) -> tuple[str, ...]:
    """Read the declared surface out of the test that owns it."""
    tree = ast.parse(source.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == NAME
            for target in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise SystemExit(f"{NAME} is not a module-level assignment in {source}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(__doc__)
    interpreter = argv[1]
    modules = portable_modules()
    if not modules:
        print(
            f"{NAME} parsed empty: this check would have passed without importing anything"
        )
        return 1

    failed = []
    for module in modules:
        probe = subprocess.run(
            [interpreter, "-c", f"import {module}"],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            failed.append((module, probe.stderr.strip().splitlines()[-1:]))

    version = subprocess.run(
        [interpreter, "-c", "import sys; print(sys.version.split()[0])"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    # PEP 561: without this file a consumer's type checker treats every import as untyped,
    # whatever the classifier says. Found by the first consumer, not by the suite.
    typed = subprocess.run(
        [
            interpreter,
            "-c",
            "from importlib.resources import files; "
            "print(files('agentic_base').joinpath('py.typed').is_file())",
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if typed != "True":
        print("FAILED py.typed: the installed package carries no PEP 561 marker")
        failed.append(("py.typed", ["missing"]))

    unimported = [module for module, _ in failed if module in modules]
    for module, why in failed:
        print(f"FAILED {module}: {why[0] if why else 'no output'}")
    print(
        f"imported {len(modules) - len(unimported)} of {len(modules)} portable modules "
        f"on {version}; py.typed {'present' if typed == 'True' else 'MISSING'}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
