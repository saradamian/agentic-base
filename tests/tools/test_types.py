"""The tool contract."""

from __future__ import annotations

from agentic_base.limits import get_limits
from agentic_base.tools.types import (
    FatalToolError,
    ScopedBackend,
    Tool,
    ToolParameter,
    ToolResult,
)


def test_a_successful_result_reads_as_its_output() -> None:
    assert str(ToolResult.ok("done")) == "done"


def test_a_failed_result_reads_as_its_error() -> None:
    """The model sees this text, so it has to say what went wrong."""
    assert str(ToolResult.fail("no such file")) == "Error: no such file"


def test_metadata_travels_with_a_result() -> None:
    assert ToolResult.ok("x", rows=3).metadata == {"rows": 3}


def test_a_fatal_error_is_distinct_from_a_failed_result() -> None:
    """An ordinary failure is retried. This one says retrying is pointless."""
    assert issubclass(FatalToolError, Exception)
    assert not isinstance(ToolResult.fail("x"), Exception)


def test_required_parameters_appear_in_the_schema() -> None:
    tool = Tool(
        name="read_file",
        description="Read a file",
        parameters=[
            ToolParameter("path", description="Where"),
            ToolParameter("encoding", required=False),
        ],
    )

    schema = tool.to_openai_schema()["function"]["parameters"]

    assert set(schema["properties"]) == {"path", "encoding"}
    assert schema["required"] == ["path"]


def test_a_tool_with_no_required_parameters_omits_the_key() -> None:
    """An empty required list is not the same as no required key, and some endpoints care."""
    tool = Tool(
        name="now", description="Time", parameters=[ToolParameter("tz", required=False)]
    )

    assert "required" not in tool.to_openai_schema()["function"]["parameters"]


def test_an_enum_parameter_carries_its_options() -> None:
    tool = Tool(
        name="t",
        description="d",
        parameters=[ToolParameter("mode", enum=["read", "write"])],
    )

    assert tool.to_openai_schema()["function"]["parameters"]["properties"]["mode"][
        "enum"
    ] == [
        "read",
        "write",
    ]


def test_the_output_limit_comes_from_configuration_not_a_literal() -> None:
    """A capability limit, so two runs at different values are not comparable and a record has to
    be able to say what it was."""
    get_limits.cache_clear()

    assert (
        Tool(name="t", description="d").output_limit
        == get_limits().tool_output_max_chars
    )


def test_a_tool_may_override_its_own_output_limit() -> None:
    assert Tool(name="t", description="d", max_output_chars=50).output_limit == 50


class _Widenable:
    def __init__(self) -> None:
        self.roots: list[str] = []

    def add_allowed_root(self, path: str) -> None:
        self.roots.append(path)


class _NotWidenable:
    pass


def test_a_backend_is_recognised_by_capability_not_by_class() -> None:
    """The reason this is a protocol.

    Upstream, the equivalent check tested for a concrete class, silently skipped a second
    implementation with identical behaviour, and every cross-product read failed for months.
    """
    assert isinstance(_Widenable(), ScopedBackend)
    assert not isinstance(_NotWidenable(), ScopedBackend)


def test_the_backend_is_wiring_and_not_identity() -> None:
    """Two tools naming the same capability are the same tool, whatever is behind them."""
    a = Tool(name="read_file", description="d", backend=_Widenable())
    b = Tool(name="read_file", description="d", backend=_Widenable())

    assert a == b


def test_two_backends_of_one_capability_register_the_same_name() -> None:
    """Decision D1. Telemetry aggregates by name, and divergent names cannot be reconciled later."""
    host = Tool(name="read_file", description="Read a file", backend=_Widenable())
    container = Tool(name="read_file", description="Read a file", backend=_Widenable())

    assert host.name == container.name
