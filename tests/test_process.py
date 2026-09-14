"""Guards on the repository's own process.

These exist because agent-assisted development multiplies whatever process is already in place.
In the project this came from, one person plus agents produced 1,823 commits in five months, and
87% of them reached the trunk without review. That is not a style preference for a component other
tenants depend on.

Most of the process lives in settings that are not in this repository: protected branches, squash
on merge, a pipeline that must pass, discussions that must be resolved. Those are managed as
Terraform elsewhere and are listed in `docs/architecture/process.md`. What is asserted here is
only the part a commit can change. The deployment pipeline belongs to the overlay, and its standing
check on permitted failures is `scripts/assert_no_permitted_failures.py`, tested in
`test_permitted_failures.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # the consumer floor; see tests/test_portable_surface.py
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]

MINIMUM_COVERAGE = 88
"""The floor. Raise it when coverage rises; never lower it.

Asserted here as well as configured, because a flag in a configuration file can be lowered in the
same change that breaks the tests it was protecting.
"""


def test_the_coverage_gate_is_at_least_the_ratcheted_floor() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    configured = config["tool"]["coverage"]["report"]["fail_under"]

    assert configured >= MINIMUM_COVERAGE


def test_commit_messages_are_checked_at_commit_time() -> None:
    """Conventional commits are what make a changelog and a bisect survive frequent agent commits.

    Between two comparable repositories the compliance rate was 95% with this hook and 4.5%
    without. The difference is entirely the hook.
    """
    config = yaml.safe_load(
        (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    hooks = [hook["id"] for repo in config["repos"] for hook in repo["hooks"]]

    assert "commitizen" in hooks


def test_every_source_module_has_a_test_module() -> None:
    """A module with no test is a module with no caller until proven otherwise.

    The first test written for a ported module found that it imported a constant which no longer
    existed. Nothing had imported it, so nothing had failed.
    """
    wired_only = {"__init__", "main", "config", "db"}
    # Alembic runs env.py and the revision files itself; the migration test exercises all of them.
    alembic_scripts = {"env"} | {
        path.stem
        for path in (ROOT / "src" / "agentic_base" / "migrations" / "versions").glob(
            "*.py"
        )
    }
    modules = (
        {path.stem for path in (ROOT / "src" / "agentic_base").rglob("*.py")}
        - wired_only
        - alembic_scripts
    )
    tested = {
        path.stem.removeprefix("test_") for path in (ROOT / "tests").rglob("test_*.py")
    }

    assert modules <= tested, f"no test module for: {sorted(modules - tested)}"


def test_the_package_ships_its_pep_561_marker() -> None:
    """The classifier says Typing :: Typed. Without py.typed in the wheel a consumer's mypy
    reports every import as untyped, which is how the first consumer found this."""
    assert (ROOT / "src" / "agentic_base" / "py.typed").exists()
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "py.typed" in data["tool"]["setuptools"]["package-data"]["agentic_base"]
    assert "Typing :: Typed" in data["project"]["classifiers"]


def test_pypi_receives_the_files_the_release_attested_not_a_rebuild() -> None:
    """Every consumer installs from PyPI. A second build in the publish job gives PyPI a wheel
    whose hash differs from the attested one, so nothing a consumer installs would verify."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    release, publish = (
        workflow["jobs"]["release"]["steps"],
        workflow["jobs"]["publish"]["steps"],
    )
    publish_runs = " ".join(step.get("run", "") for step in publish)

    assert any(
        step.get("uses", "").startswith("actions/upload-artifact@") for step in release
    )
    assert any(
        step.get("uses", "").startswith("actions/download-artifact@")
        for step in publish
    )
    assert "uv build" not in publish_runs
    assert "gh attestation verify" in publish_runs


def test_the_image_installs_the_service_and_not_the_development_tools() -> None:
    """Built without the service extra, the image started with no structlog and died; built with
    the default groups it carried pytest, ruff and mypy into production."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    syncs = [line for line in dockerfile.splitlines() if "uv sync" in line]

    assert len(syncs) == 2
    for line in syncs:
        assert "--no-dev" in line and "--extra service" in line and "--frozen" in line


def test_the_chart_deploys_the_released_version_by_default() -> None:
    """The image tag defaults to the chart's appVersion, which stayed 0.0.1 through five releases."""
    chart = yaml.safe_load((ROOT / "charts/app/Chart.yaml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert str(chart["appVersion"]) == str(citation["version"])


def test_the_image_can_read_its_own_version() -> None:
    """With .git out of the build context the image reported 0.0.0, the fallback, whatever it was."""
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert not any(line.strip() in {".git", "**/.git"} for line in ignored)
    assert "install -y -qq --no-install-recommends git" in dockerfile
