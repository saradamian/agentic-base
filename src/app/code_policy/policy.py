"""A cheap structural pre-filter for model-generated Python.

Read this before relying on it.

This is not an isolation boundary and must never be described as one. It bounds accidental
damage and rejects the known reflection-escape class before code reaches an executor. Real
isolation is the executor's job: a container with a read-only root filesystem and no bind
mounts, or a sandboxed runtime such as gVisor, or a microVM. On Kubernetes those exist and
should be used. This file is what runs in front of them, for free, to catch the obvious cases
without paying for a process.

The check is on the parsed syntax tree rather than on the text. A blocklist of patterns over
source text was verifiably escaped in the predecessor project by writing the attribute name as
two concatenated string literals, then walking the object graph to reach the file builtin. A
structural walk sees the same code as the interpreter does, so that trick has nothing to hide
behind.

One route the tree does not show, and which is handled separately: format-string fields resolve
attributes at runtime, so a dunder inside a field of a literal string is attribute access that
never appears as an attribute node.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

FORBIDDEN_NAMES = frozenset(
    {
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "globals",
        "locals",
        "eval",
        "exec",
        "compile",
        "open",
        "__import__",
        "breakpoint",
        "input",
        "object",
        "super",
        "memoryview",
        "exit",
        "quit",
    }
)
"""Builtins that hand back the object graph or the import system."""


def is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def format_field_reaches_dunder(text: str) -> bool:
    """Whether a format field inside a literal string resolves a dunder attribute.

    `"{0.__class__}".format(1)` performs attribute access that no attribute node describes.
    Only the fields are inspected, so prose mentioning a dunder is untouched.
    """
    i = 0
    while True:
        i = text.find("{", i)
        if i == -1:
            return False
        j = text.find("}", i + 1)
        if j == -1:
            return False
        field = text[i + 1 : j]
        for sep in ("[", "]", "!", ":"):
            field = field.replace(sep, ".")
        if any(is_dunder(part.strip()) for part in field.split(".")):
            return True
        i = j + 1


@dataclass(frozen=True)
class Violation:
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


def inspect(code: str) -> list[Violation]:
    """Structural violations in the given source.

    Code that does not parse is a violation rather than a pass. Unparseable input must not reach
    an executor, and reporting it as clean would be the same defect as a probe whose failure
    returns zero.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [Violation("syntax", f"code does not parse ({exc.msg})")]

    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            found.append(Violation("import", "import statement"))
        elif isinstance(node, ast.Attribute) and is_dunder(node.attr):
            found.append(Violation("reflection", f"dunder attribute access ({node.attr})"))
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(Violation("builtin", f"forbidden name ({node.id})"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if is_dunder(node.value):
                found.append(Violation("reflection", f"dunder string literal ({node.value})"))
            elif format_field_reaches_dunder(node.value):
                found.append(Violation("reflection", "dunder inside a format field"))
    return found


def is_acceptable(code: str) -> bool:
    """Whether the code passes the pre-filter. Passing is not a guarantee of safety."""
    return not inspect(code)
