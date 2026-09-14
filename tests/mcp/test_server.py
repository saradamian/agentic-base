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

    # the observer's argument rewrite applied, and its result rewrite reached both copies
    assert result.structured_content["returned_after_boundary"] == 1
    assert "returned_after_boundary" in result.content[0].text
    assert "returned" not in result.structured_content
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


@pytest.mark.asyncio
async def test_an_unknown_run_is_a_tool_error_to_the_client_and_the_observer(
    engine,
) -> None:
    recorder = _Recorder()
    server = build_server(lambda: Session(engine), observer=recorder)

    async with Client(server) as client:
        result = await client.call_tool("get_run", {"run_id": "nope"})

    assert result.is_error is True
    assert "run not found" in result.content[0].text
    assert [c["success"] for c in recorder.calls] == [False]


class _Redacting(_Recorder):
    def inspect_result(self, tool, result, success):
        return result.replace("baseline", "[arm]")


class _Wrapping(_Recorder):
    def inspect_result(self, tool, result, success):
        return f"<data>{result}</data>"


@pytest.mark.asyncio
async def test_a_result_rewrite_reaches_the_structured_copy_too(engine) -> None:
    server = build_server(lambda: Session(engine), observer=_Redacting())

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("corpus_stats", {"tenant": "hpml"})

    assert "baseline" not in result.content[0].text
    assert "baseline" not in json.dumps(result.structured_content)
    assert "[arm]" in result.structured_content["by_arm"]


@pytest.mark.asyncio
async def test_a_rewrite_that_is_no_longer_json_still_leaves_no_original_behind(
    engine,
) -> None:
    server = build_server(lambda: Session(engine), observer=_Wrapping())

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("corpus_stats", {"tenant": "hpml"})

    assert result.structured_content == {"result": result.content[0].text}
    assert result.content[0].text.startswith("<data>")


def test_the_validity_tool_serves_the_same_report_as_the_http_endpoint(
    session, test_client
) -> None:
    for item in ("t1", "t2"):
        test_client.post(
            "/runs",
            json={"tenant": "same", "code_revision": "a", "item": item, "arm": "a"},
        )
        test_client.post(
            "/runs",
            json={
                "tenant": "same",
                "code_revision": "a",
                "item": item,
                "arm": "b",
                "status": "timeout",
            },
        )
    over_http = test_client.get(
        "/runs/validity/report", params={"tenant": "same"}
    ).json()

    from agentic_base.db import get_session

    app_session = next(test_client.app.dependency_overrides[get_session]())
    over_mcp = call_tool("validity_report", {"tenant": "same"}, app_session)

    assert over_mcp == over_http
    assert [f["arm"] for f in over_mcp["flow"]] == ["a", "b"]
    assert over_mcp["flagged"][0]["ratio"] is None  # 100 % against 0 %: no finite ratio
    json.dumps(over_mcp, allow_nan=False)


def test_the_validity_thresholds_come_from_the_limits(session, monkeypatch) -> None:
    from agentic_base.limits import get_limits

    flagged_by_default = call_tool("validity_report", {"tenant": "hpml"}, session)
    monkeypatch.setenv("AP_VALIDITY_MIN_ABSOLUTE_DIFFERENCE", "1.01")
    get_limits.cache_clear()
    try:
        relaxed = call_tool("validity_report", {"tenant": "hpml"}, session)
    finally:
        monkeypatch.undo()
        get_limits.cache_clear()

    assert flagged_by_default["flagged"]
    assert relaxed["flagged"] == []


def _long_run(engine, count: int = 50, size: int = 100) -> str:
    with Session(engine) as s:
        record = RunRecord(
            tenant="hpml",
            item="long",
            arm="baseline",
            system_prompt="be careful",
            messages=[
                {"role": "user", "content": f"{n}:" + "x" * size} for n in range(count)
            ],
        )
        s.add(record)
        s.commit()
        return record.run_id


def _page(engine, run_id: str, **arguments) -> dict:
    with Session(engine) as s:
        return call_tool("get_run", {"run_id": run_id, **arguments}, s)


@pytest.fixture()
def transcript_cap(monkeypatch):
    from agentic_base.limits import get_limits

    def set_cap(value: int) -> None:
        monkeypatch.setenv("AP_MCP_MAX_TRANSCRIPT_CHARS", str(value))
        get_limits.cache_clear()

    yield set_cap
    monkeypatch.delenv("AP_MCP_MAX_TRANSCRIPT_CHARS", raising=False)
    get_limits.cache_clear()


def test_paging_by_next_message_returns_every_message_exactly_once(
    engine, transcript_cap
) -> None:
    run_id = _long_run(engine)
    transcript_cap(1000)

    collected, cursor, pages = [], 0, 0
    while cursor is not None:
        page = _page(engine, run_id, from_message=cursor)
        collected += page["messages"]
        cursor = page["transcript"]["next_message"]
        pages += 1

    with Session(engine) as s:
        original = s.get(RunRecord, run_id).messages
    assert collected == original
    assert pages > 1


def test_the_system_prompt_comes_whole_on_the_first_page_only(
    engine, transcript_cap
) -> None:
    run_id = _long_run(engine)
    transcript_cap(1000)

    first = _page(engine, run_id)
    later = _page(engine, run_id, from_message=first["transcript"]["next_message"])

    assert first["system_prompt"] == "be careful"
    assert "system_prompt" not in later


def test_a_deployment_can_turn_the_cap_off(engine, transcript_cap) -> None:
    run_id = _long_run(engine)
    transcript_cap(0)

    page = _page(engine, run_id)

    assert len(page["messages"]) == 50
    assert page["transcript"]["next_message"] is None
    assert page["transcript"]["limit_chars"] is None


def test_a_caller_can_ask_for_smaller_pages_than_the_server_allows(
    engine, transcript_cap
) -> None:
    run_id = _long_run(engine)
    transcript_cap(0)

    page = _page(engine, run_id, max_chars=500)

    assert page["transcript"]["limit_chars"] == 500
    assert 0 < page["transcript"]["messages_returned"] < 50


def test_a_caller_cannot_raise_the_page_past_the_deployment_cap(
    engine, transcript_cap
) -> None:
    run_id = _long_run(engine)
    transcript_cap(1000)

    page = _page(engine, run_id, max_chars=10**9)

    assert page["transcript"]["limit_chars"] == 1000


def test_a_message_larger_than_the_limit_is_returned_whole_and_paging_moves_on(
    engine, transcript_cap
) -> None:
    run_id = _long_run(engine, count=3, size=5000)
    transcript_cap(1000)

    first = _page(engine, run_id)

    assert len(first["messages"][0]["content"]) == 5002
    assert first["transcript"]["one_message_exceeds_limit"] is True
    assert first["transcript"]["next_message"] == 1


def test_a_negative_page_is_an_error(engine) -> None:
    run_id = _long_run(engine, count=2)

    assert "error" in _page(engine, run_id, from_message=-1)


@pytest.mark.asyncio
async def test_a_client_pages_a_transcript_through_the_tool(
    engine, transcript_cap
) -> None:
    run_id = _long_run(engine, count=20)
    transcript_cap(600)
    server = build_server(lambda: Session(engine))

    collected, cursor = [], 0
    async with Client(server, raise_exceptions=True) as client:
        while cursor is not None:
            result = await client.call_tool(
                "get_run", {"run_id": run_id, "from_message": cursor}
            )
            collected += result.structured_content["messages"]
            cursor = result.structured_content["transcript"]["next_message"]

    assert len(collected) == 20
