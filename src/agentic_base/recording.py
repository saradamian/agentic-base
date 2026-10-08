"""The seam between a served tool call and whatever records it.

Serving tools over a protocol bypasses an application's own runtime, so journal recording, trace
capture and injection defence do not happen unless something puts them back. In the predecessor
framework that something is a single chokepoint every call routes through, and it is the reason
served traffic becomes learnable corpus rather than requests that merely succeeded. Measured
there: 67 recorded calls carrying session, call index, tool name, journal identifier and input
threat level, one of them a failed thirty-second call, which is exactly the case a wrapper without
a chokepoint drops silently.

That chokepoint is not a primitive. It reaches into a journal, a trace store, a lineage recorder,
an OpenTelemetry bridge and two security modules. Importing it into a base layer would drag all of
that across and the layer would stop being thin.

So the layer declares the seam and the host fills it. An application with nothing to record gets
the no-op and pays nothing. An application with a journal supplies one object and gets its
telemetry back.

Two rules the no-op encodes, both learned expensively.

A failed call is recorded. A wrapper that records successes produces a corpus whose failure rate
is zero, which is the most confidently wrong number a corpus can contain.

Nothing here may raise. A telemetry failure that breaks a tool call has inverted the priority: the
call is the work and the record is the account of it.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

CALL_LOG_VARIABLE = "AP_CALL_LOG"
"""Names the file that `observer_from_environment` writes calls to."""


@runtime_checkable
class CallObserver(Protocol):
    """What a host implements to see served tool calls.

    Every method has a no-op default in `NullObserver`, so a host implements only what it has
    somewhere to put.
    """

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Called before dispatch. Returns the arguments to use.

        A host may scan for injected instructions here. It should not block on finding them: a
        wiki page that legitimately contains "ignore previous instructions" is a security runbook,
        and refusing to read it is a worse failure than reading it as data.
        """
        ...

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        """Called after dispatch. Returns the result to hand back.

        A host may wrap external content in a data boundary here, so the model receives it as data
        rather than as instruction. What it returns replaces every copy the client receives: the
        text, and the structured content, parsed from the new text when it is still a JSON object
        and wrapped as ``{"result": ...}`` when it is not.
        """
        ...

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        elapsed_ms: float,
        **extra: Any,
    ) -> None:
        """Called once per call, successful or not."""
        ...


class NullObserver:
    """The default. Sees everything, keeps nothing, never raises."""

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return arguments

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        return result

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        elapsed_ms: float,
        **extra: Any,
    ) -> None:
        return None


class SafeObserver:
    """Wraps a host's observer so its failures cannot reach the caller.

    A host's recorder touches a database, a network exporter, or a model. Any of those can fail,
    and none of those failures should turn a working tool call into an error. On failure the
    wrapper degrades to the no-op behaviour and counts it, so a recorder that is quietly broken is
    visible as a count rather than as an absence.
    """

    def __init__(self, inner: CallObserver) -> None:
        self._inner = inner
        self.failures = 0

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._inner.inspect_arguments(tool, arguments)
        except Exception:
            self.failures += 1
            return arguments

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        try:
            return self._inner.inspect_result(tool, result, success)
        except Exception:
            self.failures += 1
            return result

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        elapsed_ms: float,
        **extra: Any,
    ) -> None:
        try:
            self._inner.record(tool, arguments, result, success, elapsed_ms, **extra)
        except Exception:
            self.failures += 1


class JsonLinesObserver:
    """Appends one JSON object per call to a file.

    The recorder for a server with nowhere else to put its calls. Several servers can name the
    same file, and the `server` field (with `server_version` when given) says which one wrote a
    line. It keeps the arguments and the length of the result, and leaves the result itself out: a
    result can be a whole document, and the arguments are what says what an agent asked for. What
    `ObservingMiddleware` adds lands here too: the request id, the protocol version, the client's
    name and version, the caller's `_meta` keys (an agent's run id among them), the trace and span
    ids, and, for a failed call, the error text the client got, cut at `call_log_error_chars`. A
    host that handles personal data wraps this in its own observer and redacts first.
    """

    def __init__(
        self, path: str | Path, *, server: str = "", version: str = ""
    ) -> None:
        self._path = Path(path)
        self._server = server
        self._version = version

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return arguments

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        return result

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        elapsed_ms: float,
        **extra: Any,
    ) -> None:
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "server": self._server,
            **({"server_version": self._version} if self._version else {}),
            "tool": tool,
            "arguments": arguments,
            "success": success,
            "elapsed_ms": round(elapsed_ms, 1),
            "result_chars": len(result),
            **extra,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, default=str) + "\n")


def observer_from_environment(server: str = "", version: str = "") -> CallObserver:
    """The observer the environment asks for: a call log when `AP_CALL_LOG` names a file.

    *server* and *version* name the server in every line, so a log several servers share still says
    which build answered.

    Read when called, never at import, so a variable set after import still counts. Wrapped in
    `SafeObserver`: a log that cannot be written must not fail the call it describes.
    """
    path = os.environ.get(CALL_LOG_VARIABLE, "").strip()
    if not path:
        return NullObserver()
    return SafeObserver(JsonLinesObserver(path, server=server, version=version))


class ObservingMiddleware:
    """The recording seam as MCP SDK middleware, for any server built on the SDK.

    ``MCPServer(name, middleware=[ObservingMiddleware(observer_from_environment(server=name))])``
    passes every ``tools/call`` through the observer's three hooks: arguments before dispatch, the
    result after, and one record per call whether it succeeded or not. A failure that reaches the
    middleware as an exception is recorded and re-raised. Wrapped in ``SafeObserver`` so a host's
    recorder cannot break a call.

    It reads the request and the result by their shape and imports nothing from the SDK, so it
    lives in the library half: a server that never uses it pays nothing.
    """

    def __init__(self, observer: CallObserver) -> None:
        self.observer = SafeObserver(observer)

    async def __call__(
        self, ctx: Any, call_next: Callable[[Any], Awaitable[Any]]
    ) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        params = dict(ctx.params or {})
        tool = str(params.get("name", ""))
        arguments = self.observer.inspect_arguments(
            tool, dict(params.get("arguments") or {})
        )
        context = _call_context(ctx, params)
        started = time.perf_counter()
        try:
            result = await call_next(
                replace(ctx, params={**params, "arguments": arguments})
            )
        except Exception as exc:
            self.observer.record(
                tool,
                arguments,
                str(exc),
                False,
                (time.perf_counter() - started) * 1000,
                method=ctx.method,
                error=_capped(str(exc)),
                **context,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        success = not _is_error(result)
        text = _first_text(result)
        seen = self.observer.inspect_result(tool, text, success)
        if seen != text:
            # A client may read the structured copy instead of the text, so a rewrite that reached
            # only the text would hand the original to exactly those clients.
            result = _with_structured(_with_first_text(result, seen), seen)
        if not success:
            context["error"] = _capped(seen)
        self.observer.record(
            tool, arguments, seen, success, elapsed_ms, method=ctx.method, **context
        )
        return result


#: Keys the protocol itself puts in a request's ``_meta``; the session already says what they say.
_PROTOCOL_META_PREFIX = "io.modelcontextprotocol/"


def _call_context(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    """What joins a call to the rest of the story: who called, which request, which trace, which run.

    The request id and protocol version from the request; the client's name and version from the
    handshake; the caller's own ``_meta`` keys, where an agent can pass its run id (base names it
    ``agentic_base.run_id``, the tag its MLflow export uses); and the ids of the current
    OpenTelemetry span, which is the SDK's span for this call. A field that is unknown is left out.
    """
    context: dict[str, Any] = {}
    request_id = getattr(ctx, "request_id", None)
    if request_id is not None:
        context["request_id"] = request_id
    protocol = getattr(ctx, "protocol_version", None)
    if protocol:
        context["protocol_version"] = protocol
    client = _client(ctx)
    if client:
        context["client"] = client
    meta = params.get("_meta") or getattr(ctx, "meta", None) or {}
    caller_meta = {
        k: v
        for k, v in dict(meta).items()
        if not str(k).startswith(_PROTOCOL_META_PREFIX)
    }
    if caller_meta:
        context["meta"] = caller_meta
    context.update(_trace_ids())
    return context


def _client(ctx: Any) -> dict[str, str]:
    session = getattr(ctx, "session", None)
    info = getattr(getattr(session, "client_params", None), "client_info", None)
    pairs = (
        ("name", getattr(info, "name", None)),
        ("version", getattr(info, "version", None)),
    )
    return {key: str(value) for key, value in pairs if value}


def _trace_ids() -> dict[str, str]:
    """The current span's ids, when OpenTelemetry is installed and a span is recording.

    The MCP SDK depends on OpenTelemetry and opens a span for every request, so on a server this is
    that span. The import is here so the library half does not need OpenTelemetry to be imported.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return {}
    span = trace.get_current_span().get_span_context()
    if not span.is_valid:
        return {}
    return {
        "trace_id": format(span.trace_id, "032x"),
        "span_id": format(span.span_id, "016x"),
    }


def _capped(text: str) -> str:
    from agentic_base.limits import get_limits

    limit = get_limits().call_log_error_chars
    return text if len(text) <= limit else f"{text[:limit]}… [{len(text)} characters]"


# At the middleware tier a result is the wire form, a dict with camelCase keys; a later SDK may hand
# the model through instead. Both are read by shape, the model through its attributes.


def _is_error(result: Any) -> bool:
    if isinstance(result, dict):
        return bool(result.get("isError"))
    return bool(getattr(result, "is_error", False))


def _blocks(result: Any) -> list[Any]:
    content = (
        result.get("content")
        if isinstance(result, dict)
        else getattr(result, "content", None)
    )
    return list(content or [])


def _is_text(block: Any) -> bool:
    kind = (
        block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
    )
    return kind == "text"


def _first_text(result: Any) -> str:
    for block in _blocks(result):
        if _is_text(block):
            return str(
                block.get("text", "")
                if isinstance(block, dict)
                else getattr(block, "text", "")
            )
    return ""


def _with_first_text(result: Any, text: str) -> Any:
    content = [dict(b) if isinstance(b, dict) else b for b in _blocks(result)]
    for i, block in enumerate(content):
        if _is_text(block):
            content[i] = (
                {**block, "text": text}
                if isinstance(block, dict)
                else block.model_copy(update={"text": text})
            )
            break
    if isinstance(result, dict):
        return {**result, "content": content}
    if hasattr(result, "model_copy"):
        return result.model_copy(update={"content": content})
    return result


def _with_structured(result: Any, text: str) -> Any:
    """Replace the structured copy with the rewritten text: parsed when it is still a JSON object,
    otherwise wrapped as ``{"result": text}``. Dropping it is not an option, because a client refuses
    a result without structured content when the tool declares an output schema.
    """
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    structured = parsed if isinstance(parsed, dict) else {"result": text}
    if isinstance(result, dict):
        if result.get("structuredContent") is None:
            return result
        return {**result, "structuredContent": structured}
    if getattr(result, "structured_content", None) is None or not hasattr(
        result, "model_copy"
    ):
        return result
    return result.model_copy(update={"structured_content": structured})
