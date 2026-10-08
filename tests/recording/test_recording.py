"""The seam between a served call and whatever records it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentic_base.recording import (
    CALL_LOG_VARIABLE,
    CallObserver,
    JsonLinesObserver,
    NullObserver,
    ObservingMiddleware,
    SafeObserver,
    observer_from_environment,
)


class _Recording:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {**arguments, "seen": True}

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        return f"[wrapped]{result}"

    def record(self, tool, arguments, result, success, elapsed_ms, **extra) -> None:
        self.calls.append((tool, success))


class _Broken:
    def inspect_arguments(self, tool, arguments):
        raise RuntimeError("database is gone")

    def inspect_result(self, tool, result, success):
        raise RuntimeError("exporter is gone")

    def record(self, tool, arguments, result, success, elapsed_ms, **extra):
        raise RuntimeError("journal is gone")


def test_the_default_observer_changes_nothing() -> None:
    observer = NullObserver()

    assert observer.inspect_arguments("t", {"a": 1}) == {"a": 1}
    assert observer.inspect_result("t", "out", True) == "out"
    observer.record("t", {}, "out", True, 1.0)  # returns nothing; it must not raise


def test_the_default_observer_satisfies_the_protocol() -> None:
    """A host that implements nothing still type-checks as an observer."""
    assert isinstance(NullObserver(), CallObserver)


def test_a_host_observer_can_alter_arguments_and_results() -> None:
    observer = _Recording()

    assert observer.inspect_arguments("t", {"a": 1})["seen"] is True
    assert observer.inspect_result("t", "out", True).startswith("[wrapped]")


def test_a_failed_call_is_recorded_like_any_other() -> None:
    """A wrapper that records only successes produces a corpus with a zero failure rate, which is
    the most confidently wrong number a corpus can hold."""
    observer = _Recording()

    observer.record("t", {}, "boom", False, 30_000.0)

    assert observer.calls == [("t", False)]


def test_a_broken_host_observer_cannot_break_a_tool_call() -> None:
    """The call is the work; the record is the account of it. Inverting that is the wrong trade."""
    safe = SafeObserver(_Broken())

    assert safe.inspect_arguments("t", {"a": 1}) == {"a": 1}
    assert safe.inspect_result("t", "out", True) == "out"
    safe.record("t", {}, "out", True, 1.0)

    assert safe.failures == 3


def test_a_quietly_broken_recorder_is_visible_as_a_count(caplog) -> None:
    """Degrading silently is how a corpus ends up empty and nobody notices."""
    safe = SafeObserver(_Broken())

    for _ in range(4):
        safe.record("t", {}, "out", True, 1.0)

    assert safe.failures == 4


def test_a_working_observer_never_increments_the_failure_count() -> None:
    safe = SafeObserver(_Recording())

    safe.record("t", {}, "out", True, 1.0)

    assert safe.failures == 0


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_call_log_gets_one_line_per_call_and_a_failed_call_is_one_of_them(
    tmp_path: Path,
) -> None:
    log = tmp_path / "calls.jsonl"
    observer = JsonLinesObserver(log, server="easybuild")

    observer.record("search", {"name": "zlib"}, "nine hits", True, 12.34)
    observer.record("fetch", {"path": "missing.eb"}, "not found", False, 3.0)

    first, second = _lines(log)
    assert (first["server"], first["tool"], first["arguments"], first["success"]) == (
        "easybuild",
        "search",
        {"name": "zlib"},
        True,
    )
    assert first["elapsed_ms"] == 12.3 and first["result_chars"] == len("nine hits")
    assert (second["tool"], second["success"]) == ("fetch", False)


def test_the_call_log_leaves_the_result_text_out(tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"

    JsonLinesObserver(log).record("fetch", {}, "the whole document", True, 1.0)

    assert "the whole document" not in log.read_text()


def test_two_servers_can_write_to_the_same_call_log(tmp_path: Path) -> None:
    log = tmp_path / "shared" / "calls.jsonl"

    JsonLinesObserver(log, server="easybuild").record("a", {}, "", True, 1.0)
    JsonLinesObserver(log, server="slurm").record("b", {}, "", True, 1.0)

    assert [entry["server"] for entry in _lines(log)] == ["easybuild", "slurm"]


def test_without_the_variable_nothing_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CALL_LOG_VARIABLE, raising=False)

    assert isinstance(observer_from_environment("easybuild"), NullObserver)


def test_the_variable_names_the_file_calls_are_written_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv(CALL_LOG_VARIABLE, str(log))

    observer_from_environment("easybuild").record("search", {}, "", True, 1.0)

    assert _lines(log)[0]["server"] == "easybuild"


def test_a_call_log_that_cannot_be_written_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    monkeypatch.setenv(CALL_LOG_VARIABLE, str(blocker / "calls.jsonl"))
    observer = observer_from_environment("easybuild")

    observer.record("search", {}, "", True, 1.0)

    assert isinstance(observer, SafeObserver) and observer.failures == 1


@pytest.mark.asyncio
async def test_a_server_built_on_the_sdk_records_every_call_through_the_middleware(
    tmp_path: Path,
) -> None:
    """A tool server outside this repository gets the seam with one argument and no database."""
    from mcp import Client
    from mcp.server import MCPServer

    log = tmp_path / "calls.jsonl"
    server = MCPServer(
        "demo", middleware=[ObservingMiddleware(JsonLinesObserver(log, server="demo"))]
    )

    @server.tool()
    def double(n: int) -> int:
        return 2 * n

    @server.tool()
    def broken() -> str:
        raise ValueError("no page")

    async with Client(server) as client:
        await client.call_tool("double", {"n": 21})
        await client.call_tool("broken", {})

    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(e["server"], e["tool"], e["success"]) for e in lines] == [
        ("demo", "double", True),
        ("demo", "broken", False),
    ]
    assert lines[0]["arguments"] == {"n": 21}


def test_the_middleware_is_still_importable_where_it_used_to_live() -> None:
    from agentic_base.mcp import server

    assert server.ObservingMiddleware is ObservingMiddleware
