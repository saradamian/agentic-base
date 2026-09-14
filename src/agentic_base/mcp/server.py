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
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from sqlalchemy import func
from sqlmodel import Session, col, select

from agentic_base.domain.run_record import RunRecord
from agentic_base.domain.validity import check_comparison, report_as_dict
from agentic_base.limits import get_limits
from agentic_base.recording import CallObserver, NullObserver, SafeObserver

SERVER_NAME = "surf-agentic-base"


def _distribution_version() -> str:
    try:
        return version("surf-agentic-base")
    except PackageNotFoundError:
        return "0"


def _runs_for(session: Session, tenant: str) -> list[RunRecord]:
    return list(session.exec(select(RunRecord).where(RunRecord.tenant == tenant)).all())


def _transcript_page(
    record: RunRecord, from_message: int, max_chars: int, deployment_cap: int
) -> dict[str, Any]:
    """One page of a run's transcript, and where the next one starts.

    The budget is the smaller of the caller's ``max_chars`` and the deployment's cap, where ``0``
    means none. Messages are returned whole, never cut: a message larger than the budget is
    returned on its own and flagged, so paging always moves forward. The system prompt comes
    whole on the first page and does not count against the budget, so a page never repeats it.
    """
    data: dict[str, Any] = json.loads(record.model_dump_json())
    messages = data.pop("messages") or []
    if from_message:
        data.pop("system_prompt", None)
    caps = [c for c in (max_chars, deployment_cap) if c > 0]
    budget = min(caps) if caps else 0
    kept: list[Any] = []
    used = 0
    index = from_message
    while index < len(messages):
        size = len(json.dumps(messages[index]))
        if budget and kept and used + size > budget:
            break
        kept.append(messages[index])
        used += size
        index += 1
    data["messages"] = kept
    data["transcript"] = {
        "limit_chars": budget or None,
        "messages_total": len(messages),
        "from_message": from_message,
        "messages_returned": len(kept),
        "next_message": index if index < len(messages) else None,
        "one_message_exceeds_limit": bool(budget and used > budget),
    }
    return data


def call_tool(name: str, arguments: dict[str, Any], session: Session) -> dict[str, Any]:
    """Run one tool. Returns the structured payload, or ``{"error": ...}``, which the served
    tool turns into an MCP tool error."""
    limits = get_limits()

    if name == "list_runs":
        where = [RunRecord.tenant == arguments["tenant"]]
        if arm := arguments.get("arm"):
            where.append(RunRecord.arm == arm)
        total = session.exec(
            select(func.count()).select_from(RunRecord).where(*where)
        ).one()
        cap = min(
            int(arguments.get("limit") or limits.mcp_max_rows), limits.mcp_max_rows
        )
        rows = session.exec(
            select(RunRecord)
            .where(*where)
            .order_by(col(RunRecord.created_at).desc())
            .limit(cap)
        ).all()
        return {
            "total": int(total),
            "returned": len(rows),
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
                for r in rows
            ],
        }

    if name == "get_run":
        record = session.get(RunRecord, arguments["run_id"])
        if record is None:
            return {"error": f"run not found: {arguments['run_id']}"}
        from_message = int(arguments.get("from_message") or 0)
        max_chars = int(arguments.get("max_chars") or 0)
        if from_message < 0 or max_chars < 0:
            return {"error": "from_message and max_chars must not be negative"}
        return _transcript_page(
            record, from_message, max_chars, limits.mcp_max_transcript_chars
        )

    if name == "validity_report":
        return report_as_dict(check_comparison(_runs_for(session, arguments["tenant"])))

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
            # A client may read the structured copy instead of the text, so a rewrite that
            # reached only the text would hand the original to exactly those clients.
            result = _with_structured(_with_first_text(result, seen), seen)
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
            payload = call_tool(name, arguments, session)
        if set(payload) == {"error"}:
            # Returned as a value it would read as a successful call to the model and to the
            # observer alike; raised, the SDK sends it with isError set.
            raise ToolError(payload["error"])
        return payload

    @server.tool(name="list_runs")
    def list_runs(tenant: str, arm: str = "", limit: int = 0) -> dict[str, Any]:
        """List run records for a tenant, newest first, with the provenance of each outcome."""
        return _call("list_runs", tenant=tenant, arm=arm or None, limit=limit or None)

    @server.tool(name="get_run")
    def get_run(
        run_id: str, from_message: int = 0, max_chars: int = 0
    ) -> dict[str, Any]:
        """One run: the environment it ran in and its transcript, a page at a time.

        A long transcript comes in pages. transcript.next_message is where the next page starts;
        call again with from_message set to it until it is null. max_chars asks for smaller pages
        than the server's limit; 0 means the server's limit.
        """
        return _call(
            "get_run", run_id=run_id, from_message=from_message, max_chars=max_chars
        )

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


def main() -> None:
    """The ``agentic-base-mcp`` command: the corpus at ``DATABASE_URL``, over stdio.

    It reads the same settings as the service, so pointed at the service's database it serves
    the records the service wrote.
    """
    from agentic_base.db import get_engine, init_db

    init_db()
    engine = get_engine()
    serve_stdio(lambda: Session(engine))


if __name__ == "__main__":
    main()


def _with_structured(result: Any, text: str) -> Any:
    """Replace the structured copy with the rewritten text: parsed when it is still a JSON
    object, otherwise wrapped as ``{"result": text}``. Dropping it is not an option, because a
    client refuses a result without structured content when the tool declares an output schema.
    """
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    structured = parsed if isinstance(parsed, dict) else {"result": text}
    if isinstance(result, CallToolResult):
        if result.structured_content is None:
            return result
        return result.model_copy(update={"structured_content": structured})
    if isinstance(result, dict) and result.get("structuredContent") is not None:
        return {**result, "structuredContent": structured}
    return result
