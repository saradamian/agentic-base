"""The read-only MCP surface."""

import json

import pytest
from mcp import Client
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
