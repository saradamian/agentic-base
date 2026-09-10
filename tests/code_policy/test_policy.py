"""Behaviour of the structural pre-filter.

The concatenation test is a regression for a real escape: in the predecessor project a
text-pattern blocklist was defeated by writing the attribute name as two adjacent string
literals, then walking the object graph to reach the file builtin.
"""

from app.code_policy.policy import inspect, is_acceptable


def test_plain_arithmetic_passes() -> None:
    assert is_acceptable("total = sum(x * 2 for x in range(10))")


def test_an_import_statement_is_rejected() -> None:
    assert [v.kind for v in inspect("import os")] == ["import"]


def test_a_from_import_is_rejected() -> None:
    assert any(v.kind == "import" for v in inspect("from os import system"))


def test_reflection_through_a_dunder_attribute_is_rejected() -> None:
    assert any(v.kind == "reflection" for v in inspect("().__class__.__bases__"))


def test_a_forbidden_builtin_is_rejected_even_when_only_referenced() -> None:
    """Passing the name as a value is the same capability as calling it."""
    assert any(v.kind == "builtin" for v in inspect("f = open"))


def test_splitting_a_dunder_across_string_literals_is_still_rejected() -> None:
    """The escape that defeated a text-pattern blocklist. The tree sees what the interpreter sees."""
    assert not is_acceptable('getattr(object, "__subcla" "sses__")')


def test_a_dunder_inside_a_format_field_is_rejected() -> None:
    """Format fields resolve attributes at runtime, so no attribute node appears in the tree."""
    assert any(v.kind == "reflection" for v in inspect('"{0.__class__}".format(1)'))


def test_prose_mentioning_a_dunder_is_not_rejected() -> None:
    """Only format fields are inspected, so a docstring is untouched."""
    assert is_acceptable('x = "call __init__ when you construct it"')


def test_code_that_does_not_parse_is_a_violation_rather_than_a_pass() -> None:
    """Unparseable input must not reach an executor, and must not be reported clean."""
    violations = inspect("def (:")
    assert violations and violations[0].kind == "syntax"
