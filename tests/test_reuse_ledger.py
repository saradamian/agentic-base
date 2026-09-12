"""The reuse ledger is a claim about the code, so it is checked against the code.

`docs/architecture/reuse-ledger.md` says which concerns are adopted, bridged or built. Its own
closing rule is that an ADOPT verdict implemented by hand is a defect. Until now nothing failed
when that happened, and it happened once (the MCP surface). These guards read the ledger's
tables and hold the source tree to them.

The ledger has four table shapes. A parser keyed on one layout would examine zero rows of the
others and report clean, so every check states how many rows it read.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "architecture" / "reuse-ledger.md"
SRC = ROOT / "src" / "agentic_base"

# An ADOPT verdict on one of these modules means the named strings must not appear in it,
# because each is the signature of doing the adopted thing by hand.
HAND_ROLLED = {
    "mcp/server.py": ('"jsonrpc"', '"tools/list"', "protocolVersion"),
    "llm/resilience.py": ("for attempt", "while True", "sleep("),
}

# A verdict that adopts a vocabulary means the module imports it rather than restating it.
IMPORTS_THE_STANDARD = {
    "observability/conventions.py": ("openinference.semconv", "opentelemetry.semconv"),
}


def _tables(text: str) -> list[tuple[tuple[str, ...], list[dict[str, str]]]]:
    """Every markdown table as (header, rows). Cells keep their markup."""
    tables: list[tuple[tuple[str, ...], list[dict[str, str]]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if (
            lines[i].startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1])
        ):
            header = tuple(c.strip() for c in lines[i].strip("|").split("|"))
            rows: list[dict[str, str]] = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                rows.append(dict(zip(header, cells, strict=False)))
                i += 1
            tables.append((header, rows))
        else:
            i += 1
    return tables


def _rows(header_starts: tuple[str, ...]) -> list[dict[str, str]]:
    found = [
        rows
        for header, rows in _tables(LEDGER.read_text())
        if header[: len(header_starts)] == header_starts
    ]
    assert found, f"no table in the ledger starts with columns {header_starts}"
    return [row for rows in found for row in rows]


def _modules() -> set[str]:
    return {
        str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if p.name != "__init__.py"
    }


def _audit_module(row: dict[str, str]) -> str:
    return row["module"].strip("`")


def test_the_ledger_parses_into_every_table_shape_it_uses() -> None:
    counts = {header: len(rows) for header, rows in _tables(LEDGER.read_text())}
    shapes = {h[:2] for h in counts}
    assert ("concern", "component") in shapes, counts
    assert ("concern", "why nothing else does it") in shapes, counts
    assert ("module", "finding") in shapes, counts
    assert all(n > 0 for n in counts.values()), counts


def test_every_module_in_src_has_a_verdict_in_the_source_audit() -> None:
    rows = _rows(("module", "finding", "verdict"))
    audited = {_audit_module(r) for r in rows}
    missing = _modules() - audited
    assert not missing, (
        f"{len(rows)} audit rows read; modules with no verdict: {sorted(missing)}"
    )


def test_every_audit_row_names_a_module_that_exists() -> None:
    rows = _rows(("module", "finding", "verdict"))
    stale = {_audit_module(r) for r in rows} - _modules()
    assert not stale, (
        f"{len(rows)} audit rows read; rows for modules that no longer exist: {sorted(stale)}"
    )


def test_every_build_verdict_says_when_to_revisit() -> None:
    build_rows = _rows(("concern", "why nothing else does it", "revisit when"))
    empty = [r["concern"] for r in build_rows if not r["revisit when"].strip()]
    assert not empty, (
        f"{len(build_rows)} BUILD rows read; no revisit condition: {empty}"
    )

    audit_builds = [
        r
        for r in _rows(("module", "finding", "verdict"))
        if r["verdict"].startswith("BUILD")
    ]
    without = [
        _audit_module(r)
        for r in audit_builds
        if "revisit when" not in r["verdict"].lower()
    ]
    assert not without, (
        f"{len(audit_builds)} BUILD audit rows read; no revisit condition: {without}"
    )


def test_an_adopt_verdict_is_not_implemented_by_hand() -> None:
    verdicts = {
        _audit_module(r): r["verdict"] for r in _rows(("module", "finding", "verdict"))
    }
    checked = 0
    for module, markers in HAND_ROLLED.items():
        assert verdicts[module].startswith("ADOPT"), (
            f"{module} is in HAND_ROLLED but the ledger says {verdicts[module][:40]!r}; "
            "update one of them"
        )
        source = (SRC / module).read_text()
        present = [m for m in markers if m in source]
        assert not present, (
            f"{module} is ADOPT in the ledger and still hand-rolls it: {present}"
        )
        checked += 1
    assert checked == len(HAND_ROLLED)


def test_an_adopted_vocabulary_is_imported_not_restated() -> None:
    verdicts = {
        _audit_module(r): r["verdict"] for r in _rows(("module", "finding", "verdict"))
    }
    for module, packages in IMPORTS_THE_STANDARD.items():
        assert verdicts[module].startswith("ADOPT"), module
        source = (SRC / module).read_text()
        absent = [p for p in packages if p not in source]
        assert not absent, f"{module} is ADOPT and does not import {absent}"
