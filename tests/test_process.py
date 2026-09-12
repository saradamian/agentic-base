"""Guards on the repository's own process.

These exist because agent-assisted development multiplies whatever process is already in place.
In the project this came from, one person plus agents produced 1,823 commits in five months, and
87% of them reached the trunk without review. That is not a style preference for a component other
tenants depend on.

Most of the process lives in settings that are not in this repository: protected branches, squash
on merge, a pipeline that must pass, discussions that must be resolved. Those are managed as
Terraform elsewhere and are listed in `docs/architecture/process.md`. What is asserted here is
only the part a commit can change.
"""

from __future__ import annotations

from pathlib import Path

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]


class _CILoader(yaml.SafeLoader):
    """Tolerates GitLab's own YAML tags, such as `!reference`.

    The safe loader rejects them, and a parse failure here would otherwise be indistinguishable
    from a policy failure, which is the confusion these tests exist to prevent.
    """


_CILoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _load_ci() -> dict:
    return yaml.load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"), Loader=_CILoader)

MINIMUM_COVERAGE = 88
"""The floor. Raise it when coverage rises; never lower it.

Asserted here as well as configured, because a flag in a configuration file can be lowered in the
same change that breaks the tests it was protecting.
"""


def test_the_coverage_gate_is_at_least_the_ratcheted_floor() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    configured = config["tool"]["coverage"]["report"]["fail_under"]

    assert configured >= MINIMUM_COVERAGE


def test_no_pipeline_job_is_permitted_to_fail() -> None:
    """A permitted failure is silence, not a warning.

    The pipeline verdict is what people read, so a job that is allowed to fail and does fail is
    indistinguishable from one that passed. Two gates in the predecessor project were dead behind a
    green pipeline through a 165-commit consolidation. If a check cannot block, delete it.

    Parsed rather than grepped. The first version searched the file as text and would have failed
    on a comment explaining the rule, which is a check whose answer depends on something other
    than the property it names.
    """
    ci = _load_ci()

    offenders = [
        name
        for name, body in ci.items()
        if isinstance(body, dict) and body.get("allow_failure")
    ]

    assert not offenders, f"jobs permitted to fail: {offenders}"


def test_the_pipeline_asserts_its_own_job_list_at_runtime() -> None:
    """The static check above covers only jobs written here.

    Most jobs arrive from a shared component pinned at a version that is bumped automatically, so
    a permitted failure can appear in this pipeline without this file changing.
    """
    ci = _load_ci()

    assert "assert:no-permitted-failures" in ci


def test_commit_messages_are_checked_at_commit_time() -> None:
    """Conventional commits are what make a changelog and a bisect survive frequent agent commits.

    Between two comparable repositories the compliance rate was 95% with this hook and 4.5%
    without. The difference is entirely the hook.
    """
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [hook["id"] for repo in config["repos"] for hook in repo["hooks"]]

    assert "commitizen" in hooks


def test_every_source_module_has_a_test_module() -> None:
    """A module with no test is a module with no caller until proven otherwise.

    The first test written for a ported module found that it imported a constant which no longer
    existed. Nothing had imported it, so nothing had failed.
    """
    wired_only = {"__init__", "main", "config", "db"}
    modules = {
        path.stem for path in (ROOT / "src" / "app").rglob("*.py")
    } - wired_only
    tested = {path.stem.removeprefix("test_") for path in (ROOT / "tests").rglob("test_*.py")}

    assert modules <= tested, f"no test module for: {sorted(modules - tested)}"
