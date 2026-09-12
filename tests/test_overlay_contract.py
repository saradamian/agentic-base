"""The deployment-overlay contract, and the tool that enforces and uses it.

The end-to-end tests build a throwaway upstream repository and an overlay in a temporary
directory, compose them, change upstream, and sync. They exercise git itself rather than a
mock of it, because the contract is a property of how git merges disjoint trees.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import overlay

ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True, check=True
    ).stdout


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.org",
        "commit",
        "-q",
        "-m",
        message,
    )


def _upstream(tmp: Path) -> Path:
    """A minimal upstream: a contract, one owned-by-upstream file, one commit on main."""
    up = tmp / "upstream"
    up.mkdir()
    _git(up, "init", "-q", "-b", "main")
    (up / "overlay.cfg").write_text(
        "[overlay]\nupstream = file://"
        + str(up)
        + "\npaths =\n    .overlay/\n    deploy/\n    OVERLAY.md\n"
    )
    (up / "code.py").write_text("VALUE = 1\n")
    _commit_all(up, "initial")
    return up


def _overlay(tmp: Path) -> Path:
    ov = tmp / "overlay"
    (ov / "deploy").mkdir(parents=True)
    (ov / ".overlay").mkdir()
    _git(ov, "init", "-q", "-b", "main")
    (ov / "deploy" / "values.yaml").write_text("host: internal.example\n")
    (ov / "OVERLAY.md").write_text("composed\n")
    (ov / ".overlay" / "forbidden.txt").write_text("internal\\.example\n")
    _commit_all(ov, "overlay")
    return ov


def test_no_declared_overlay_path_exists_in_this_repository() -> None:
    assert overlay.check(ROOT) == 0


def test_check_refuses_an_overlay_owned_path_that_appears_upstream(
    tmp_path: Path,
) -> None:
    up = _upstream(tmp_path)
    (up / "deploy").mkdir()
    (up / "deploy" / "leak.yaml").write_text("x: 1\n")
    _commit_all(up, "a deployment file lands upstream")

    assert overlay.check(up) == 1


def test_compose_then_sync_merges_an_upstream_change_without_touching_the_overlay(
    tmp_path: Path,
) -> None:
    up, ov = _upstream(tmp_path), _overlay(tmp_path)
    out = tmp_path / "composed"

    assert overlay.compose(ov, out, "main", "file://" + str(up)) == 0
    (up / "code.py").write_text("VALUE = 2\n")
    _commit_all(up, "upstream changes code")

    assert overlay.sync(out, "main") == 0
    assert (out / "code.py").read_text() == "VALUE = 2\n"
    assert (out / "deploy" / "values.yaml").read_text() == "host: internal.example\n"


def test_sync_refuses_when_upstream_grows_a_file_at_an_overlay_owned_path(
    tmp_path: Path,
) -> None:
    """The one way the merge can conflict, and it is a contract violation, not a merge problem."""
    up, ov = _upstream(tmp_path), _overlay(tmp_path)
    out = tmp_path / "composed"
    assert overlay.compose(ov, out, "main", "file://" + str(up)) == 0
    (up / "deploy").mkdir()
    (up / "deploy" / "values.yaml").write_text("host: upstream-thinks-it-owns-this\n")
    _commit_all(up, "upstream adds an overlay-owned file")

    assert overlay.sync(out, "main") == 1
    assert (out / "deploy" / "values.yaml").read_text() == "host: internal.example\n"


def test_check_refuses_a_site_identifier_in_an_upstream_owned_file_downstream(
    tmp_path: Path,
) -> None:
    up, ov = _upstream(tmp_path), _overlay(tmp_path)
    out = tmp_path / "composed"
    assert overlay.compose(ov, out, "main", "file://" + str(up)) == 0
    (out / "code.py").write_text("URL = 'https://internal.example/api'\n")
    _commit_all(out, "someone hardcodes the site on the deployment side")

    assert overlay.check(out) == 1


@pytest.mark.skipif(
    shutil.which("git") is None, reason="git is required for the contract tests"
)
def test_git_is_available() -> None:
    assert shutil.which("git")
