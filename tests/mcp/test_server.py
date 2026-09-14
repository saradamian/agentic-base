"""The read-only MCP surface."""

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from agentic_base.domain.run_record import LabelSource, RunRecord, RunStatus
from agentic_base.mcp.server import build_server, call_tool


@pytest.fixture()
def engine():
    # The SDK runs a sync tool on a worker thread; an in-memory SQLite must be one connection.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(
            RunRecord(
                tenant="hpml",
                item="task-1",
                arm="baseline",
                resolved=True,
                label_source=LabelSource.OFFICIAL_HARNESS,
            )
        )
        s.add(
            RunRecord(
                tenant="hpml",
                item="task-2",
                arm="baseline",
                resolved=True,
                label_source=LabelSource.CONVENIENCE_VERIFIER,
            )
        )
        s.add(
            RunRecord(
                tenant="hpml",
                item="task-3",
                arm="treatment",
                status=RunStatus.INFRASTRUCTURE_ERROR,
                failure_kind="container_removed",
            )
        )
        s.commit()
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture()
def server(engine):
    return build_server(lambda: Session(engine))


def test_listing_runs_reports_whether_each_outcome_is_citable(session) -> None:
    payload = call_tool("list_runs", {"tenant": "hpml"}, session)

    citable = {r["item"]: r["citable"] for r in payload["runs"]}
    assert citable["task-1"] is True
    assert citable["task-2"] is False


def test_corpus_stats_separate_the_arms(session) -> None:
    payload = call_tool("corpus_stats", {"tenant": "hpml"}, session)

    assert payload["by_arm"]["baseline"]["runs"] == 2
    assert payload["by_arm"]["treatment"]["excluded"] == 1


def test_the_validity_tool_reports_what_it_examined(session) -> None:
    payload = call_tool("validity_report", {"tenant": "hpml"}, session)

    assert payload["arms_examined"] == 2
    assert "could_have_flagged" in payload


def test_an_unknown_run_reports_an_error_rather_than_raising(session) -> None:
    assert "error" in call_tool("get_run", {"run_id": "nope"}, session)


@pytest.mark.asyncio
async def test_the_published_surface_stays_small(server) -> None:
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()

    assert sorted(t.name for t in listed.tools) == [
        "corpus_stats",
        "get_run",
        "list_runs",
        "validity_report",
    ]


@pytest.mark.asyncio
async def test_a_tool_call_returns_structured_content_and_json_text(server) -> None:
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("corpus_stats", {"tenant": "hpml"})

    assert result.is_error is False
    assert result.structured_content["tenant"] == "hpml"
    assert json.loads(result.content[0].text)["by_arm"]["baseline"]["runs"] == 2


@pytest.mark.asyncio
async def test_a_missing_argument_is_a_tool_error_not_a_crash(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("list_runs", {})

    assert result.is_error is True


@pytest.mark.asyncio
async def test_the_row_cap_is_reported_rather_than_silent(server, monkeypatch) -> None:
    monkeypatch.setenv("AP_MCP_MAX_ROWS", "1")
    from agentic_base.limits import get_limits

    get_limits.cache_clear()
    try:
        async with Client(server, raise_exceptions=True) as client:
            result = await client.call_tool("list_runs", {"tenant": "hpml"})
    finally:
        get_limits.cache_clear()

    payload = result.structured_content
    assert payload["total"] == 3
    assert payload["returned"] == 1


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def inspect_arguments(self, tool, arguments):
        return {**arguments, "limit": 1} if tool == "list_runs" else arguments

    def inspect_result(self, tool, result, success):
        return (
            result.replace('"returned"', '"returned_after_boundary"')
            if success
            else result
        )

    def record(self, tool, arguments, result, success, elapsed_ms, **extra):
        self.calls.append(
            {
                "tool": tool,
                "arguments": arguments,
                "success": success,
                "elapsed_ms": elapsed_ms,
                **extra,
            }
        )


@pytest.mark.asyncio
async def test_every_served_call_reaches_the_observer_and_its_argument_rewrite_is_honoured(
    engine,
) -> None:
    recorder = _Recorder()
    server = build_server(lambda: Session(engine), observer=recorder)

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("list_runs", {"tenant": "hpml"})

    assert (
        result.structured_content["returned"] == 1
    )  # the observer's argument rewrite applied
    assert (
        "returned_after_boundary" in result.content[0].text
    )  # and its result rewrite reached the client
    (call,) = recorder.calls
    assert call["tool"] == "list_runs"
    assert call["arguments"]["limit"] == 1
    assert call["success"] is True
    assert call["elapsed_ms"] > 0
    assert call["method"] == "tools/call"


@pytest.mark.asyncio
async def test_a_failed_call_is_recorded_as_a_failure_not_dropped(engine) -> None:
    recorder = _Recorder()
    server = build_server(lambda: Session(engine), observer=recorder)

    async with Client(server) as client:
        result = await client.call_tool("list_runs", {})

    assert result.is_error is True
    assert [c["success"] for c in recorder.calls] == [False]


@pytest.mark.asyncio
async def test_a_broken_observer_cannot_break_a_call(engine) -> None:
    class Broken(_Recorder):
        def record(self, *a, **k):
            raise RuntimeError("recorder down")

    server = build_server(lambda: Session(engine), observer=Broken())

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("corpus_stats", {"tenant": "hpml"})

    assert result.is_error is False


@pytest.mark.asyncio
async def test_the_sdk_traces_a_served_call_into_the_configured_provider(
    engine, monkeypatch
) -> None:
    """The MCP SDK traces through the global provider. If configure_tracing did not set it,
    every span the SDK emits would be dropped by the API's no-op default."""
    from fastapi import FastAPI
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from agentic_base.observability.tracing import configure_tracing

    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    exporter = InMemorySpanExporter()
    assert configure_tracing(FastAPI(), exporter=exporter) is not None
    server = build_server(lambda: Session(engine))

    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("corpus_stats", {"tenant": "hpml"})

    scopes = {s.instrumentation_scope.name for s in exporter.get_finished_spans()}
    assert "mcp-python-sdk" in scopes, scopes


@pytest.mark.asyncio
async def test_the_installed_command_serves_the_database_it_is_pointed_at(
    tmp_path,
) -> None:
    """The server is reachable the way a chat client reaches it: a process over stdio."""
    url = f"sqlite:///{tmp_path / 'runs.db'}"
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(RunRecord(tenant="from-disk", item="task-1", arm="baseline"))
        s.commit()
    engine.dispose()

    command = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentic_base.mcp.server"],
        env={
            **os.environ,
            "DATABASE_URL": url,
            "OTEL_SDK_DISABLED": "true",
            # this tree's code, whatever copy the interpreter has installed
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
        },
    )
    async with Client(command, raise_exceptions=True) as client:
        tools = sorted(t.name for t in (await client.list_tools()).tools)
        stats = await client.call_tool("corpus_stats", {"tenant": "from-disk"})

    assert tools == ["corpus_stats", "get_run", "list_runs", "validity_report"]
    assert stats.structured_content is not None
    assert json.dumps(stats.structured_content).count("baseline") >= 1
