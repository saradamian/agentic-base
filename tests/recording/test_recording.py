"""The seam between a served call and whatever records it."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
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
    call_context,
    call_log_schema,
    call_outcome,
    capped_error,
    default_call_log_directory,
    observer_from_environment,
    prune_call_log,
    read_call_log,
    summarise_calls,
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


def test_without_the_variable_calls_go_to_this_months_file_in_the_state_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv(CALL_LOG_VARIABLE, raising=False)

    observer_from_environment("easybuild").record("search", {}, "", True, 1.0)

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    log = tmp_path / "agentic-base" / "calls" / f"{month}.jsonl"
    assert _lines(log)[0]["server"] == "easybuild"


def test_an_empty_variable_means_the_default_like_an_unset_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv(CALL_LOG_VARIABLE, " ")

    observer_from_environment("easybuild").record("search", {}, "", True, 1.0)

    assert read_call_log([default_call_log_directory()]).calls


@pytest.mark.parametrize("value", ["off", "OFF", " off "])
def test_off_records_nothing(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CALL_LOG_VARIABLE, value)

    assert isinstance(observer_from_environment("easybuild"), NullObserver)


def test_the_default_directory_is_under_the_home_when_xdg_state_home_is_unset_or_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    expected = tmp_path / ".local" / "state" / "agentic-base" / "calls"

    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert default_call_log_directory() == expected
    monkeypatch.setenv("XDG_STATE_HOME", "relative/state")
    assert default_call_log_directory() == expected


def test_without_a_home_directory_nothing_is_recorded_and_nothing_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_home() -> Path:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", no_home)

    assert isinstance(observer_from_environment("easybuild"), NullObserver)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_a_new_call_log_is_readable_by_its_owner_only(tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"

    JsonLinesObserver(log).record("search", {"q": "internal"}, "", True, 1.0)

    assert os.stat(log).st_mode & 0o777 == 0o600


def test_a_monthly_log_names_each_file_by_the_month_of_its_calls(
    tmp_path: Path,
) -> None:
    JsonLinesObserver(tmp_path, server="easybuild", monthly=True).record(
        "search", {}, "", True, 1.0
    )

    [written] = list(tmp_path.iterdir())
    assert written.name == datetime.now(timezone.utc).strftime("%Y-%m") + ".jsonl"


def _write(path: Path, *entries: dict[str, Any], tail: str = "") -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries) + tail)
    return path


def _call(
    tool: str, success: bool = True, ms: float = 10.0, **extra: Any
) -> dict[str, Any]:
    return {
        "time": "2026-10-08T10:00:00.000+00:00",
        "server": "easybuild",
        "tool": tool,
        "arguments": {},
        "success": success,
        "elapsed_ms": ms,
        **extra,
    }


def test_reading_skips_a_half_written_line_and_counts_it(tmp_path: Path) -> None:
    log = _write(tmp_path / "2026-10.jsonl", _call("search"), tail='{"time": "2026-10-')

    read = read_call_log([log])

    assert [c["tool"] for c in read.calls] == ["search"] and read.unreadable_lines == 1


def test_reading_a_directory_reads_every_month_oldest_first(tmp_path: Path) -> None:
    _write(tmp_path / "2026-10.jsonl", _call("later", time="2026-10-01T00:00:00+00:00"))
    _write(
        tmp_path / "2026-09.jsonl", _call("earlier", time="2026-09-01T00:00:00+00:00")
    )

    assert [c["tool"] for c in read_call_log([tmp_path]).calls] == ["earlier", "later"]


def test_reading_keeps_only_the_server_and_the_period_asked_for(tmp_path: Path) -> None:
    log = _write(
        tmp_path / "calls.jsonl",
        _call("old", time="2026-09-01T00:00:00+00:00"),
        _call("new", time="2026-10-08T00:00:00+00:00"),
        {**_call("other"), "server": "confluence"},
    )

    read = read_call_log(
        [log], since=datetime(2026, 10, 1, tzinfo=timezone.utc), server="easybuild"
    )

    assert [c["tool"] for c in read.calls] == ["new"]


def test_reading_the_default_directory_before_anything_was_recorded_is_an_empty_log() -> (
    None
):
    read = read_call_log()

    assert read.calls == [] and read.files == []


def test_reading_a_named_path_that_does_not_exist_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_call_log([tmp_path / "missing.jsonl"])


def test_the_summary_puts_the_busiest_tool_first_with_its_failures_and_durations() -> (
    None
):
    calls = [_call("search", ms=float(ms)) for ms in range(1, 21)]
    calls += [
        _call("checksum", success=False, error="URL rejected: internal address"),
        _call("checksum", ms=30.0),
    ]

    summary = summarise_calls(calls)

    search, checksum = summary.tools
    assert (search.tool, search.calls, search.failed) == ("search", 20, 0)
    assert (search.median_ms, search.p95_ms) == (10.5, 19.0)
    assert (checksum.failed, checksum.last_error) == (
        1,
        "URL rejected: internal address",
    )
    assert (summary.calls, summary.failed) == (22, 1)


def test_the_summary_counts_clients_by_name_and_version() -> None:
    calls = [
        _call("a", client={"name": "claude-code", "version": "2.1"}),
        _call("b", client={"name": "claude-code", "version": "2.1"}),
        _call("c", client={"name": "opencode"}),
        _call("d"),
    ]

    assert summarise_calls(calls).clients == {"claude-code 2.1": 2, "opencode": 1}


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


async def _served(log: Path, **call: Any) -> list[dict[str, Any]]:
    from mcp import Client
    from mcp.server import MCPServer

    server = MCPServer(
        "demo",
        middleware=[
            ObservingMiddleware(JsonLinesObserver(log, server="demo", version="1.2.3"))
        ],
    )

    @server.tool()
    def double(n: int) -> int:
        return 2 * n

    @server.tool()
    def broken() -> str:
        # A tool error's text reaches the client; an unexpected exception's text does not.
        from mcp.server.mcpserver.exceptions import ToolError

        raise ToolError("no page " + "x" * 2000)

    async with Client(server) as client:
        await client.call_tool(
            "double", {"n": 21}, meta={"agentic_base.run_id": "run-123"}
        )
        await client.call_tool("broken", {})
    return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.asyncio
async def test_a_call_record_says_which_client_request_and_run_it_belongs_to(
    tmp_path: Path,
) -> None:
    ok, _ = await _served(tmp_path / "calls.jsonl")
    assert ok["server_version"] == "1.2.3"
    assert isinstance(ok["request_id"], int)
    assert ok["protocol_version"]
    assert ok["client"]["name"]
    # the caller's own keys are kept; the protocol's, which the session already gives, are not
    assert ok["meta"] == {"agentic_base.run_id": "run-123"}
    assert "error" not in ok


@pytest.mark.asyncio
async def test_a_failed_call_keeps_its_error_cut_at_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentic_base.limits import get_limits

    monkeypatch.setenv("AP_CALL_LOG_ERROR_CHARS", "40")
    get_limits.cache_clear()
    try:
        _, failed = await _served(tmp_path / "calls.jsonl")
    finally:
        monkeypatch.delenv("AP_CALL_LOG_ERROR_CHARS")
        get_limits.cache_clear()
    assert failed["success"] is False
    assert "no page" in failed["error"]
    assert failed["error"].endswith("characters]")
    assert len(failed["error"]) < 80


@pytest.mark.asyncio
async def test_a_call_record_carries_the_ids_of_the_span_it_ran_in(
    tmp_path: Path,
) -> None:
    from dataclasses import dataclass

    from opentelemetry.sdk.trace import TracerProvider

    @dataclass
    class _Ctx:
        method: str
        params: dict[str, Any]

    async def _call_next(ctx: Any) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": "42"}], "isError": False}

    extras: list[dict[str, Any]] = []

    class _Extras(NullObserver):
        def record(self, tool, arguments, result, success, elapsed_ms, **extra) -> None:
            extras.append(extra)

    middleware = ObservingMiddleware(_Extras())
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("tools/call double") as span:
        await middleware(
            _Ctx("tools/call", {"name": "double", "arguments": {}}), _call_next
        )
    (extra,) = extras
    assert extra["trace_id"] == format(span.get_span_context().trace_id, "032x")
    assert extra["span_id"] == format(span.get_span_context().span_id, "016x")


def test_call_context_reads_a_relays_mapping_and_its_own_span() -> None:
    class Span:
        is_valid = True
        trace_id = 0x120BB1DF40892F503418AAFD635553D2
        span_id = 0x1A2B3C4D5E6F7081

    context = call_context(
        {
            "_meta": {
                "agentic_base.run_id": "run-7",
                "io.modelcontextprotocol/progressToken": 1,
            }
        },
        request_id=4,
        protocol_version="2026-07-28",
        client={"name": "claude-code", "version": "2.1"},
        span_context=Span(),
    )

    assert context == {
        "request_id": 4,
        "protocol_version": "2026-07-28",
        "client": {"name": "claude-code", "version": "2.1"},
        "meta": {"agentic_base.run_id": "run-7"},
        "trace_id": "120bb1df40892f503418aafd635553d2",
        "span_id": "1a2b3c4d5e6f7081",
    }


def test_call_outcome_reads_a_result_and_a_protocol_error() -> None:
    failed = {"isError": True, "content": [{"type": "text", "text": "no such page"}]}
    assert call_outcome(failed) == ("no such page", False)
    assert call_outcome({"content": [{"type": "text", "text": "ok"}]}) == ("ok", True)
    assert call_outcome(error={"code": -32602, "message": "Unknown tool: t"}) == (
        "Unknown tool: t",
        False,
    )


def test_capped_error_keeps_a_short_text_and_says_how_long_a_cut_one_was() -> None:
    assert capped_error("short") == "short"
    assert capped_error("x" * 600).endswith("… [600 characters]")


@pytest.mark.asyncio
async def test_a_line_the_middleware_writes_satisfies_the_published_schema(
    tmp_path: Path,
) -> None:
    import jsonschema
    from mcp import Client
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    log = tmp_path / "calls.jsonl"
    server = MCPServer(
        "schema-check",
        middleware=[ObservingMiddleware(JsonLinesObserver(log, server="schema-check"))],
    )

    @server.tool()
    def refuse(reason: str) -> str:
        raise ToolError(reason)

    async with Client(server) as client:
        await client.call_tool(
            "refuse", {"reason": "no"}, meta={"agentic_base.run_id": "r"}
        )

    schema = call_log_schema()
    [line] = _lines(log)
    jsonschema.validate(line, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**line, "trace_id": "not-a-trace-id"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({k: v for k, v in line.items() if k != "success"}, schema)


NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def _months(directory: Path, *names: str) -> None:
    for name in names:
        (directory / name).write_text("{}\n")


def test_a_month_that_ended_more_than_the_retention_ago_is_deleted(
    tmp_path: Path,
) -> None:
    # March ended on 1 April, 191 days before NOW; April ended 161 days before it.
    _months(
        tmp_path,
        "2025-01.jsonl",
        "2026-03.jsonl",
        "2026-04.jsonl",
        "notes.jsonl",
        "2026-13.jsonl",
    )

    deleted = prune_call_log(tmp_path, NOW, keep_days=183)

    assert sorted(p.name for p in deleted) == ["2025-01.jsonl", "2026-03.jsonl"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "2026-04.jsonl",
        "2026-13.jsonl",
        "notes.jsonl",
    ]


def test_zero_keeps_every_month(tmp_path: Path) -> None:
    _months(tmp_path, "2020-01.jsonl")
    assert prune_call_log(tmp_path, NOW, keep_days=0) == []
    assert (tmp_path / "2020-01.jsonl").exists()


def test_a_period_shorter_than_six_months_is_honoured(tmp_path: Path) -> None:
    # August ended on 1 September, 38 days before NOW; September ended 8 days before it.
    _months(tmp_path, "2026-08.jsonl", "2026-09.jsonl")

    deleted = prune_call_log(tmp_path, NOW, keep_days=30)

    assert [p.name for p in deleted] == ["2026-08.jsonl"]
    assert (tmp_path / "2026-09.jsonl").exists()


def test_december_ends_on_the_first_of_january(tmp_path: Path) -> None:
    _months(tmp_path, "2025-12.jsonl")
    assert (
        prune_call_log(
            tmp_path, datetime(2026, 7, 3, tzinfo=timezone.utc), keep_days=183
        )
        == []
    )
    assert prune_call_log(
        tmp_path, datetime(2026, 7, 4, tzinfo=timezone.utc), keep_days=183
    )


def test_the_first_call_of_a_month_prunes_the_old_months(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AP_CALL_LOG_RETENTION_DAYS", "183")
    from agentic_base.limits import get_limits

    get_limits.cache_clear()
    try:
        _months(tmp_path, "2020-01.jsonl")
        JsonLinesObserver(tmp_path, server="easybuild", monthly=True).record(
            "t", {}, "", True, 1.0
        )
    finally:
        get_limits.cache_clear()

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    assert [p.name for p in tmp_path.iterdir()] == [f"{month}.jsonl"]
