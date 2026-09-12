"""The read-only MCP surface."""

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine

from agentic_base.domain.run_record import LabelSource, RunRecord, RunStatus
from agentic_base.mcp.server import call_tool, handle_request


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
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
        yield s
    engine.dispose()


def test_initialize_announces_the_tool_capability(session) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, session
    )

    assert response is not None
    assert "tools" in response["result"]["capabilities"]


def test_a_notification_receives_no_reply(session) -> None:
    """A reply to a notification makes some clients drop the session."""
    assert (
        handle_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, session
        )
        is None
    )


def test_the_published_surface_stays_small(session) -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, session
    )

    assert response is not None
    assert len(response["result"]["tools"]) == 4


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


def test_a_missing_argument_becomes_a_protocol_error(session) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "list_runs"},
    }

    response = handle_request(request, session)

    assert response is not None
    assert response["error"]["code"] == -32602


def test_a_tool_call_returns_json_text_content(session) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {"name": "corpus_stats", "arguments": {"tenant": "hpml"}},
    }

    response = handle_request(request, session)

    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["tenant"] == "hpml"
