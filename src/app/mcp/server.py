"""Read-only MCP surface over the run corpus.

Why this exists. The run records are the most useful thing the platform holds, and the people
who want them are usually sitting in a chat client rather than writing a query. MCP is how a
chat client reaches a tool, so publishing the corpus as an MCP server means a researcher can ask
what their runs did, and what their comparison is worth, without an account on anything new.

Two decisions worth stating.

The surface is read-only and small. A manifest that registers everything costs the caller a tool
schema on every turn and hands out capabilities written for a trusted in-process caller. Four
tools cover what people actually ask.

Rows come back capped. A chat client pays for every row in its context window, so a query that
would return thousands returns the cap and says how many it left.

Dispatch is a pure function of the request and a session, so it is tested without a transport.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from sqlmodel import Session, select

from app.domain.run_record import RunRecord
from app.domain.validity import check_comparison
from app.limits import get_limits

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "agentic-base", "version": "0.1.0"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_runs",
        "description": (
            "List run records for a tenant, newest first. Returns identifiers, arm, status, "
            "outcome and the provenance of the outcome label."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant": {"type": "string", "description": "Owning project or research group."},
                "arm": {"type": "string", "description": "Optional filter on the arm."},
                "limit": {"type": "integer", "description": "Rows to return."},
            },
            "required": ["tenant"],
        },
    },
    {
        "name": "get_run",
        "description": (
            "One run in full, including the transcript the model received and the resolved "
            "environment it ran in."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "validity_report",
        "description": (
            "Whether a comparison across a tenant's arms is sound enough to report. Detects "
            "exclusion channels whose rate differs by arm, which does not cancel in a contrast. "
            "Read could_have_flagged before believing sound."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"tenant": {"type": "string"}},
            "required": ["tenant"],
        },
    },
    {
        "name": "corpus_stats",
        "description": (
            "Counts per arm for a tenant: runs, how many carry a citable outcome label, and how "
            "many verdicts came from a degraded instrument."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"tenant": {"type": "string"}},
            "required": ["tenant"],
        },
    },
]


class _Observation:
    __slots__ = ("item", "arm", "channel")

    def __init__(self, item: str, arm: str, channel: str) -> None:
        self.item = item
        self.arm = arm
        self.channel = channel


def _runs_for(session: Session, tenant: str) -> list[RunRecord]:
    return list(session.exec(select(RunRecord).where(RunRecord.tenant == tenant)).all())


def call_tool(name: str, arguments: dict[str, Any], session: Session) -> dict[str, Any]:
    """Run one tool. Returns the structured payload, not the MCP envelope."""
    limits = get_limits()

    if name == "list_runs":
        rows = _runs_for(session, arguments["tenant"])
        if arm := arguments.get("arm"):
            rows = [r for r in rows if r.arm == arm]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        cap = min(int(arguments.get("limit") or limits.mcp_max_rows), limits.mcp_max_rows)
        return {
            "total": len(rows),
            "returned": min(len(rows), cap),
            "runs": [
                {
                    "run_id": r.run_id,
                    "item": r.item,
                    "arm": r.arm,
                    "status": r.status.value,
                    "resolved": r.resolved,
                    "label_source": r.label_source.value,
                    "degraded": r.degraded,
                    "citable": r.citable,
                }
                for r in rows[:cap]
            ],
        }

    if name == "get_run":
        record = session.get(RunRecord, arguments["run_id"])
        if record is None:
            return {"error": "run not found"}
        return json.loads(record.model_dump_json())

    if name == "validity_report":
        rows = _runs_for(session, arguments["tenant"])
        report = check_comparison(
            _Observation(r.item, r.arm, r.exclusion_channel) for r in rows
        )
        return {
            "sound": report.sound,
            "could_have_flagged": report.could_have_flagged,
            "summary": report.summary(),
            "arms_examined": report.arms_examined,
            "channels_examined": report.channels_examined,
            "observations_examined": report.observations_examined,
            "paired_items": report.paired_items,
            "total_items": report.total_items,
            "flagged": [c.describe() for c in report.flagged],
        }

    if name == "corpus_stats":
        rows = _runs_for(session, arguments["tenant"])
        stats: dict[str, dict[str, int]] = {}
        for record in rows:
            bucket = stats.setdefault(
                record.arm or "(unset)", {"runs": 0, "citable": 0, "degraded": 0, "excluded": 0}
            )
            bucket["runs"] += 1
            bucket["citable"] += int(record.citable)
            bucket["degraded"] += int(record.degraded)
            bucket["excluded"] += int(record.excluded)
        return {"tenant": arguments["tenant"], "by_arm": stats}

    return {"error": f"unknown tool: {name}"}


def handle_request(request: dict[str, Any], session: Session) -> dict[str, Any] | None:
    """Handle one JSON-RPC request. Returns None for a notification, which takes no reply."""
    method = request.get("method", "")
    request_id = request.get("id")

    if request_id is None:
        return None  # a notification

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            payload = call_tool(name, arguments, session)
        except KeyError as exc:
            return _error(request_id, -32602, f"missing argument: {exc}")
        return _result(
            request_id,
            {"content": [{"type": "text", "text": json.dumps(payload, default=str, indent=2)}]},
        )
    return _error(request_id, -32601, f"unknown method: {method}")


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve_stdio(session_factory: Callable[[], Session]) -> None:
    """Read requests from stdin and write replies to stdout.

    Nothing else may write to stdout while this runs. A stray print corrupts the protocol and
    presents as a client that connects and immediately disconnects, so logging goes to stderr.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        with session_factory() as session:
            response = handle_request(request, session)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
