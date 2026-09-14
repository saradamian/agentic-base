"""The documentation builds, and the README reads the same wherever it is rendered.

The README is rendered in three places: GitHub, the package page on PyPI, and the documentation
site, which includes it. A relative link works in the first and breaks in the other two, and
nothing fails when one is added. The site build in strict mode refuses a link to a page that does
not exist, which is the other half of the same failure.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def relative_links(markdown: str) -> list[str]:
    return re.findall(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)", markdown)


def test_the_readme_has_no_link_that_breaks_off_github() -> None:
    assert relative_links((ROOT / "README.md").read_text()) == []


def test_a_planted_relative_link_is_found() -> None:
    assert relative_links(
        "see [the ledger](docs/ledger.md) and [x](https://github.com)"
    ) == ["docs/ledger.md"]


def test_the_documentation_site_builds_in_strict_mode(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--site-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    warnings = [
        line for line in result.stderr.splitlines() if line.startswith("WARNING")
    ]
    assert result.returncode == 0, "\n".join(warnings) or result.stderr[-2000:]
