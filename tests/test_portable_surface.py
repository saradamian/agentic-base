"""The half of this repository that `agentic-env` has to be able to import.

The point of this layer is that code leaves its consumers and lands here. That only works if a
consumer can actually import it, and on the day this was written it could not: the package
declared Python 3.14 against `agentic-env`'s 3.10 floor, and its core dependencies included a web
framework, a migration tool and a Postgres driver. Importing a URL-safety helper would have
pulled all three into a benchmark cell running inside a task container.

So the portable surface is declared here rather than described in a document, and three
properties of it are checked. Each was verified to fail when broken:

* every portable module parses under the 3.10 grammar;
* importing one loads no service dependency, checked in a fresh interpreter so that another
  test having already imported SQLModel cannot make this pass vacuously;
* none of them reaches for the runtime attributes that exist only above the floor.

The third is a name check and is weaker than the other two. It is here because `datetime.UTC` and
`enum.StrEnum` are the two that actually shipped, and neither is visible to a parser.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

PORTABLE_MODULES = (
    "agentic_base.client",
    "agentic_base.code_policy.policy",
    "agentic_base.domain.epochs",
    "agentic_base.domain.integrity",
    "agentic_base.domain.outcomes",
    "agentic_base.domain.validity",
    "agentic_base.hpc.clusters",
    "agentic_base.hpc.job_result",
    "agentic_base.limits",
    "agentic_base.llm.health",
    "agentic_base.llm.resilience",
    "agentic_base.observability.conventions",
    "agentic_base.recording",
    "agentic_base.redaction.redact",
    "agentic_base.security.netsec",
    "agentic_base.tools.types",
)
"""What a consumer may import. Anything outside this list is the service's own business."""

SERVICE_ONLY = (
    "sqlalchemy",
    "sqlmodel",
    "fastapi",
    "starlette",
    "psycopg",
    "alembic",
    "uvicorn",
)

CONSUMER_PYTHON_FLOOR = (3, 10)
"""`agentic-env` declares `requires-python = ">=3.10"`. This layer cannot ask for more."""

ABOVE_THE_FLOOR = (
    ("datetime.UTC", "datetime.UTC is 3.11+; use datetime.timezone.utc"),
    ("import UTC", "datetime.UTC is 3.11+; use datetime.timezone.utc"),
    ("StrEnum", "enum.StrEnum is 3.11+; subclass (str, Enum)"),
    ("ExceptionGroup", "ExceptionGroup is 3.11+"),
    ("tomllib", "tomllib is 3.11+; use tomli or pyyaml"),
)


def _path_of(module: str) -> Path:
    return SRC / (module.replace(".", "/") + ".py")


@pytest.mark.parametrize("module", PORTABLE_MODULES)
def test_portable_module_parses_under_the_consumer_python_floor(module: str) -> None:
    source = _path_of(module).read_text()
    ast.parse(source, feature_version=CONSUMER_PYTHON_FLOOR)


@pytest.mark.parametrize("module", PORTABLE_MODULES)
def test_portable_module_avoids_runtime_names_newer_than_the_floor(module: str) -> None:
    source = _path_of(module).read_text()
    for needle, why in ABOVE_THE_FLOOR:
        assert needle not in source, f"{module}: {why}"


@pytest.mark.parametrize("module", PORTABLE_MODULES)
def test_importing_a_portable_module_loads_no_service_dependency(module: str) -> None:
    """Run in a fresh interpreter on purpose.

    In-process this would pass whenever some earlier test had already imported SQLModel, which is
    an absence the check could not have contradicted.
    """
    probe = (
        "import importlib, sys, json;"
        f"importlib.import_module({module!r});"
        f"print(json.dumps(sorted({{m.split('.')[0] for m in sys.modules}} & set({list(SERVICE_ONLY)!r}))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=SRC.parent,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC), "HOME": "/tmp"},
        timeout=120,
    )
    assert result.returncode == 0, f"{module} failed to import:\n{result.stderr}"
    leaked = result.stdout.strip().splitlines()[-1]
    assert leaked == "[]", f"{module} pulled service dependencies: {leaked}"


def test_the_linter_targets_the_consumer_floor_rather_than_ours() -> None:
    """Otherwise the linter demands the constructs the consumer cannot run.

    This is not hypothetical. With `target-version = "py314"`, ruff's own pyupgrade rules asked
    for `datetime.UTC` and `enum.StrEnum` in these modules, both 3.11+. A contributor clearing
    the lint would have broken the consumer, and the lint would have been the reason.
    """
    text = (SRC.parent / "pyproject.toml").read_text()
    line = next(ln for ln in text.splitlines() if ln.startswith("target-version"))
    target = line.split('"')[1]
    want = f"py{CONSUMER_PYTHON_FLOOR[0]}{CONSUMER_PYTHON_FLOOR[1]}"
    assert target == want, (
        f"ruff targets {target} but the consumer floor is {want}; its upgrade rules will ask "
        "for syntax this layer's consumers cannot run"
    )


def test_the_declared_python_floor_admits_the_consumer() -> None:
    text = (SRC.parent / "pyproject.toml").read_text()
    line = next(ln for ln in text.splitlines() if ln.startswith("requires-python"))
    floor = tuple(int(p) for p in line.split('">=')[1].rstrip('"').split("."))
    assert floor <= CONSUMER_PYTHON_FLOOR, (
        f"requires-python is {floor}, above the consumer floor {CONSUMER_PYTHON_FLOOR}; "
        "agentic-env could not import this at all"
    )
