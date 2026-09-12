"""Guards on the repository's own process.

These exist because agent-assisted development multiplies whatever process is already in place.
In the project this came from, one person plus agents produced 1,823 commits in five months, and
87% of them reached the trunk without review. That is not a style preference for a component other
tenants depend on.

Most of the process lives in settings that are not in this repository: protected branches, squash
on merge, a pipeline that must pass, discussions that must be resolved. Those are managed as
Terraform elsewhere and are listed in `docs/architecture/process.md`. What is asserted here is
only the part a commit can change. The guards on the GitLab pipeline itself are in
`test_gitlab_pipeline.py`, kept apart because the public mirror has no such pipeline.
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
    modules = {path.stem for path in (ROOT / "src" / "app").rglob("*.py")} - wired_only
    tested = {
        path.stem.removeprefix("test_") for path in (ROOT / "tests").rglob("test_*.py")
    }

    assert modules <= tested, f"no test module for: {sorted(modules - tested)}"
