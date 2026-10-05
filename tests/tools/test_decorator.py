"""Declaring a tool from a function."""

from __future__ import annotations

from agentic_base.limits import get_limits
from agentic_base.tools.decorator import tool
from agentic_base.tools.types import ToolResult


def test_name_and_description_come_from_the_function_when_not_given() -> None:
    @tool()
    def fetch_page(url: str) -> ToolResult:
        """Fetch a page by URL.

        The second line is for the reader of the code.
        """
        return ToolResult.ok(url)

    assert fetch_page.name == "fetch_page"
    assert fetch_page.description == "Fetch a page by URL."


def test_a_parameter_without_a_default_is_required_and_one_with_a_default_is_not() -> (
    None
):
    @tool()
    def search(query: str, limit: int = 10) -> ToolResult:
        return ToolResult.ok(query)

    by_name = {p.name: p for p in search.parameters}

    assert by_name["query"].required is True
    assert by_name["limit"].required is False
    assert by_name["limit"].default == 10


def test_type_hints_become_json_types_and_an_unhinted_parameter_is_a_string() -> None:
    @tool()
    def configure(
        count: int, ratio: float, dry_run: bool, tags: list, raw
    ) -> ToolResult:  # type: ignore[no-untyped-def,type-arg]
        return ToolResult.ok("")

    types = {p.name: p.type for p in configure.parameters}

    assert types == {
        "count": "integer",
        "ratio": "number",
        "dry_run": "boolean",
        "tags": "array",
        "raw": "string",
    }


def test_an_explicit_parameter_replaces_what_the_signature_would_give() -> None:
    @tool(
        parameters={
            "mode": {
                "type": "string",
                "description": "How to validate",
                "enum": ["dry-run", "fetch"],
            }
        }
    )
    def validate(path: str, mode: str = "dry-run") -> ToolResult:
        return ToolResult.ok(path)

    mode = next(p for p in validate.parameters if p.name == "mode")

    assert mode.description == "How to validate"
    assert mode.enum == ["dry-run", "fetch"]
    assert mode.required is False


def test_the_tool_calls_the_function_it_was_made_from() -> None:
    @tool(name="shout")
    def upper(text: str) -> ToolResult:
        return ToolResult.ok(text.upper())

    assert upper.handler is not None
    assert str(upper.handler(text="eb")) == "EB"


def test_output_limit_is_the_configured_one_unless_the_declaration_sets_it() -> None:
    @tool()
    def default_limit() -> ToolResult:
        return ToolResult.ok("")

    @tool(max_output_chars=500_000)
    def large_diff() -> ToolResult:
        return ToolResult.ok("")

    assert default_limit.output_limit == get_limits().tool_output_max_chars
    assert large_diff.output_limit == 500_000
