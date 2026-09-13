"""The names a page gives for code, tests, settings and endpoints exist in the tree.

A model-based drift check was measured against three planted changes to this repository and
caught one. What drifts most often is simpler than a false sentence: a module moved, a test was
renamed, a setting lost its prefix, a route changed shape. Those are checkable without a model,
so they are checked here, by reading the source rather than importing it, so the service extra is
not needed and nothing starts.

Each checker reports how many references it examined, and the test requires a floor, so a page
format change that makes the extractor find nothing fails instead of passing on an empty set.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGES = [
    ROOT / name
    for name in ("README.md", "START_HERE.md", "CONTRIBUTING.md", "SECURITY.md")
]
PAGES += sorted((ROOT / "docs").rglob("*.md"))

#: Upper-case names from other people's vocabularies that a page quotes on purpose.
EXTERNAL_NAMES = {
    "OTEL_*": "the OpenTelemetry SDK's own variables",
    "CONFLUENCE_*": "the configuration vocabulary of the reference Confluence server",
}
PATH_PREFIXES = ("tests/", "src/", "scripts/", "docs/", ".github/")
METHODS = ("get", "post", "put", "patch", "delete")


def _top_level_names(module: Path) -> dict[str, ast.AST]:
    names: dict[str, ast.AST] = {}
    for node in ast.parse(module.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = node
        elif isinstance(node, ast.Assign):
            names.update({t.id: node for t in node.targets if isinstance(t, ast.Name)})
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names[node.target.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update({(a.asname or a.name).split(".")[0]: node for a in node.names})
    return names


def _module_file(dotted: list[str]) -> Path | None:
    base = SRC.joinpath(*dotted)
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def missing_module_reference(reference: str) -> str | None:
    parts = reference.split(".")
    for cut in range(len(parts), 0, -1):
        module = _module_file(parts[:cut])
        if module is None:
            continue
        rest = parts[cut:]
        if not rest:
            return None
        node = _top_level_names(module).get(rest[0])
        if node is None:
            return f"`{reference}`: {module.relative_to(ROOT)} defines no `{rest[0]}`"
        if len(rest) > 1 and isinstance(node, ast.ClassDef):
            members = {
                getattr(item, "name", None)
                or getattr(getattr(item, "target", None), "id", None)
                for item in node.body
            }
            if rest[1] not in members:
                return f"`{reference}`: class `{rest[0]}` has no `{rest[1]}`"
        return None
    return f"`{reference}`: no such module under src/"


def missing_path_reference(reference: str) -> str | None:
    path = reference.split("::")[0].split()[0]
    return None if (ROOT / path).exists() else f"`{reference}`: no such path"


def _settings_fields() -> set[str]:
    tree = ast.parse((SRC / "agentic_base" / "config.py").read_text())
    return {
        node.target.id.upper()
        for cls in tree.body
        if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def _source_constants() -> set[str]:
    return {
        name
        for module in SRC.rglob("*.py")
        for name in _top_level_names(module)
        if name.isupper()
    }


def missing_name_reference(
    reference: str, fields: set[str], constants: set[str]
) -> str | None:
    if reference in EXTERNAL_NAMES or reference in fields or reference in constants:
        return None
    if reference.endswith("_*") and any(f.startswith(reference[:-1]) for f in fields):
        return None
    return (
        f"`{reference}`: not a setting, a constant in src/, or a listed external name"
    )


def _routes() -> set[str]:
    routes: set[str] = set()
    for module in (SRC / "agentic_base" / "routers").glob("*.py"):
        tree = ast.parse(module.read_text())
        prefix = ""
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "APIRouter"
            ):
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = str(kw.value.value)
        for node in ast.walk(tree):
            for deco in getattr(node, "decorator_list", []):
                if not (
                    isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                ):
                    continue
                arg = deco.args[0] if deco.args else None
                if deco.func.attr in METHODS and isinstance(arg, ast.Constant):
                    routes.add(f"{deco.func.attr.upper()} {prefix}{arg.value!s}")
    return routes


def missing_endpoint_reference(reference: str, routes: set[str]) -> str | None:
    return (
        None if reference.split("?")[0] in routes else f"`{reference}`: no such route"
    )


def check(text: str) -> tuple[list[str], dict[str, int]]:
    """Problems found in one page's backticked references, and how many of each kind it read."""
    fields, constants, routes = _settings_fields(), _source_constants(), _routes()
    problems: list[str] = []
    examined = {"modules": 0, "paths": 0, "names": 0, "endpoints": 0}
    for token in re.findall(r"`([^`\n]+)`", text):
        if re.fullmatch(r"agentic_base(\.\w+)+", token):
            examined["modules"] += 1
            problem = missing_module_reference(token)
        elif token.startswith(PATH_PREFIXES):
            examined["paths"] += 1
            problem = missing_path_reference(token)
        elif re.fullmatch(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)*(_\*)?", token) and (
            "_" in token or token in fields
        ):
            examined["names"] += 1
            problem = missing_name_reference(token, fields, constants)
        elif re.match(r"(GET|POST|PUT|PATCH|DELETE) /", token):
            examined["endpoints"] += 1
            problem = missing_endpoint_reference(token, routes)
        else:
            continue
        if problem:
            problems.append(problem)
    return problems, examined


def test_every_reference_on_a_page_names_something_that_exists() -> None:
    problems: list[str] = []
    totals = {"modules": 0, "paths": 0, "names": 0, "endpoints": 0}
    for page in PAGES:
        found, examined = check(page.read_text())
        problems += [f"{page.relative_to(ROOT)}: {p}" for p in found]
        totals = {k: totals[k] + examined[k] for k in totals}
    floors = {"modules": 15, "paths": 25, "names": 8, "endpoints": 2}
    assert all(totals[k] >= floors[k] for k in floors), (
        f"read too little to mean anything: {totals}"
    )
    assert problems == [], "\n".join(problems)


def test_a_planted_reference_of_each_kind_is_reported() -> None:
    page = (
        "`agentic_base.domain.integrity.no_such_function` `agentic_base.nowhere` "
        "`tests/test_nothing_here.py` `REDACTION_NO_SUCH_SETTING` `GET /runs/nowhere` "
        "`agentic_base.domain.integrity.verify_chain` `REDACTION_LLM_*` `GET /runs/export?tenant=x`"
    )
    problems, examined = check(page)
    assert examined == {"modules": 3, "paths": 1, "names": 2, "endpoints": 2}
    assert len(problems) == 5, problems
