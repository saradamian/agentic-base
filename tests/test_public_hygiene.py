"""The repository is public. Site facts and internal sources stay out of it.

The overlay contract keeps deployment values out of the tree. This holds the prose to the same
rule: no internal hostnames, no internal repository paths, no references to internal documents
as sources. Content stays; attribution to something a reader cannot open does not.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = (
    r"confluence\.ia",
    r"gitlab\.surf",
    r"surf\.nl:5050",
    r"hpml-llms",
    r"sdp/(components|apps|templates|infrastructure)",
    r"internal (wiki|gitlab|registry|documentation)",
    r"design memo",
    r"user interviews?",
    r"CISO",
    r"procurement",
    r"/home/[a-z]+",
    r"\b(T2|T4)\.[0-9]+\b",
)

DOCS = [
    *ROOT.glob("*.md"),
    *(ROOT / "docs").rglob("*.md"),
    *(ROOT / "src").rglob("*.py"),
]


def test_public_prose_names_no_internal_source_or_site() -> None:
    hits = []
    for path in DOCS:
        text = path.read_text()
        for pattern in FORBIDDEN:
            for m in re.finditer(pattern, text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(ROOT)}:{line}: {m.group(0)}")
    assert len(DOCS) > 20, "the file list is too short to be the repository"
    assert not hits, f"{len(DOCS)} files read; internal references: {hits}"
