"""Read-only MCP surface over the run corpus.

The run records are the most useful thing the platform holds, and the people who want them are
usually in a chat client. Publishing the corpus over MCP lets a researcher ask what their runs
did and what their comparison is worth without an account on anything new.

The protocol belongs to the official SDK. This module owns two things: the four tools, and the
pure dispatch in :func:`call_tool`, which takes a request and a session and is tested without a
transport. Everything else, the handshake, JSON-RPC, schemas derived from signatures, structured
output, the in-memory client tests run against, is the SDK's.

The surface is read-only and small. A manifest that registers everything costs the caller a tool
schema on every turn and hands out capabilities written for a trusted in-process caller. Rows
come back capped, because a chat client pays for every row in its context window.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from mcp.server import MCPServer
from mcp.server.context import ServerRequestContext
from mcp.types import CallToolResult, TextContent
from sqlmodel import Session, select

from agentic_base.domain.run_record import RunRecord
from agentic_base.domain.validity import check_comparison
from agentic_base.limits import get_limits
from agentic_base.recording import CallObserver, NullObserver, SafeObserver

SERVER_NAME = "surf-agentic-base"


def _distribution_version() -> str:
    try:
        return version("surf-agentic-base")
    except PackageNotFoundError:
        return "0"


class _Observation:
    __slots__ = ("item", "arm", "channel")

    def __init__(self, item: str, arm: str, channel: str) -> None:
        self.item = item
        self.arm = arm
        self.channel = channel


def _runs_for(session: Session, tenant: str) -> list[RunRecord]:
    return list(session.exec(select(RunRecord).where(RunRecord.tenant == tenant)).all())


def call_tool(name: str, arguments: dict[str, Any], session: Session) -> dict[str, Any]:
    """Run one tool. Returns the structured payload, not the protocol envelope."""
    limits = get_limits()

    if name == "list_runs":
        rows = _runs_for(session, arguments["tenant"])
        if arm := arguments.get("arm"):
            rows = [r for r in rows if r.arm == arm]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        cap = min(
            int(arguments.get("limit") or limits.mcp_max_rows), limits.mcp_max_rows
        )
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
                    "classification": r.classification.value,
                    "principal": r.principal,
                }
                for r in rows[:cap]
            ],
        }

    if name == "get_run":
        record = session.get(RunRecord, arguments["run_id"])
        if record is None:
            return {"error": "run not found"}
        return dict(json.loads(record.model_dump_json()))

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
                record.arm or "(unset)",
                {"runs": 0, "citable": 0, "degraded": 0, "excluded": 0},
            )
            bucket["runs"] += 1
            bucket["citable"] += int(record.citable)
            bucket["degraded"] += int(record.degraded)
            bucket["excluded"] += int(record.excluded)
        return {"tenant": arguments["tenant"], "by_arm": stats}

    return {"error": f"unknown tool: {name}"}


class ObservingMiddleware:
    """The recording seam, as the SDK's own middleware.

    Every ``tools/call`` passes the observer's three hooks: arguments before dispatch, the
    result after, and one record per call whether it succeeded or not. A failure that reaches
    the middleware as an exception is recorded and re-raised. Wrapped in ``SafeObserver`` so
    a host's recorder cannot break a call.
    """

    def __init__(self, observer: CallObserver) -> None:
        self.observer = SafeObserver(observer)

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: Callable[[ServerRequestContext[Any, Any]], Awaitable[Any]],
    ) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        params = dict(ctx.params or {})
        tool = str(params.get("name", ""))
        arguments = self.observer.inspect_arguments(
            tool, dict(params.get("arguments") or {})
        )
        started = time.perf_counter()
        try:
            result = await call_next(
                replace(ctx, params={**params, "arguments": arguments})
            )
        except Exception as exc:
            self.observer.record(
                tool, arguments, str(exc), False, (time.perf_counter() - started) * 1000
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        success = not _is_error(result)
        text = _first_text(result)
        seen = self.observer.inspect_result(tool, text, success)
        if seen != text:
            result = _with_first_text(result, seen)
        self.observer.record(
            tool, arguments, seen, success, elapsed_ms, method=ctx.method
        )
        return result


# At the middleware tier a result is the wire form, a dict with camelCase keys, not the model.
# Both shapes are handled so a future SDK that hands the model through changes nothing here.


def _is_error(result: Any) -> bool:
    if isinstance(result, CallToolResult):
        return bool(result.is_error)
    return bool(isinstance(result, dict) and result.get("isError"))


def _first_text(result: Any) -> str:
    if isinstance(result, CallToolResult):
        return next((b.text for b in result.content if isinstance(b, TextContent)), "")
    if isinstance(result, dict):
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                return str(block.get("text", ""))
    return ""


def _with_first_text(result: Any, text: str) -> Any:
    if isinstance(result, CallToolResult):
        content = list(result.content)
        for i, block in enumerate(content):
            if isinstance(block, TextContent):
                content[i] = TextContent(type="text", text=text)
                break
        return result.model_copy(update={"content": content})
    if isinstance(result, dict):
        content = [
            dict(b) if isinstance(b, dict) else b for b in result.get("content") or []
        ]
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                block["text"] = text
                break
        return {**result, "content": content}
    return result


def build_server(
    session_factory: Callable[[], Session], observer: CallObserver | None = None
) -> MCPServer:
    """The four tools over a session factory. Schemas come from the signatures.

    *observer* sees every served call through :class:`ObservingMiddleware`; the default keeps
    nothing.
    """
    server = MCPServer(
        SERVER_NAME,
        version=_distribution_version(),
        instructions=(
            "Read-only access to agent run records. Before quoting a number, read "
            "label_source and degraded on the run, and could_have_flagged on a validity report."
        ),
        middleware=[ObservingMiddleware(observer or NullObserver())],
    )

    def _call(name: str, **arguments: Any) -> dict[str, Any]:
        with session_factory() as session:
            return call_tool(name, arguments, session)

    @server.tool(name="list_runs")
    def list_runs(tenant: str, arm: str = "", limit: int = 0) -> dict[str, Any]:
        """List run records for a tenant, newest first, with the provenance of each outcome."""
        return _call("list_runs", tenant=tenant, arm=arm or None, limit=limit or None)

    @server.tool(name="get_run")
    def get_run(run_id: str) -> dict[str, Any]:
        """One run in full: the transcript the model received and the environment it ran in."""
        return _call("get_run", run_id=run_id)

    @server.tool(name="validity_report")
    def validity_report(tenant: str) -> dict[str, Any]:
        """Whether a comparison across a tenant's arms is sound enough to report.

        Detects exclusion channels whose rate differs by arm, which does not cancel in a
        contrast. Read could_have_flagged before believing sound.
        """
        return _call("validity_report", tenant=tenant)

    @server.tool(name="corpus_stats")
    def corpus_stats(tenant: str) -> dict[str, Any]:
        """Counts per arm: runs, citable outcomes, verdicts from a degraded instrument."""
        return _call("corpus_stats", tenant=tenant)

    return server


def serve_stdio(session_factory: Callable[[], Session]) -> None:
    """Serve over stdio. Nothing else may write to stdout while this runs."""
    build_server(session_factory).run("stdio")
