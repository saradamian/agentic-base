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

import contextlib
import json
import math
import os
import statistics
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

CALL_LOG_VARIABLE = "AP_CALL_LOG"
"""Says where `observer_from_environment` writes calls: a file, ``off``, or unset for the default."""

CALL_LOG_OFF = "off"
"""The value of `CALL_LOG_VARIABLE` that records nothing."""


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

    With *monthly*, *path* is a directory and each call goes to the file of its month,
    ``2026-10.jsonl``, so no file grows without end and an old month is removed by its name. A new
    file is readable by its owner only.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        server: str = "",
        version: str = "",
        monthly: bool = False,
    ) -> None:
        self._path = Path(path)
        self._server = server
        self._version = version
        self._monthly = monthly

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
        now = datetime.now(timezone.utc)
        entry = {
            "time": now.isoformat(timespec="milliseconds"),
            "server": self._server,
            **({"server_version": self._version} if self._version else {}),
            "tool": tool,
            "arguments": arguments,
            "success": success,
            "elapsed_ms": round(elapsed_ms, 1),
            "result_chars": len(result),
            **extra,
        }
        target = self._path / f"{now:%Y-%m}.jsonl" if self._monthly else self._path
        new_month = self._monthly and not target.exists()
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        line = (json.dumps(entry, default=str) + "\n").encode("utf-8")
        # One write to a file opened for appending, so the lines of servers sharing a file do not
        # interleave.
        fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
        if new_month:
            # Once a month, by whichever server writes first. The call is written already, so a
            # file that cannot be deleted costs nothing.
            with contextlib.suppress(OSError):
                prune_call_log(self._path, now)


def prune_call_log(
    directory: str | Path, now: datetime | None = None, keep_days: int | None = None
) -> list[Path]:
    """Delete the month files (``2026-03.jsonl``) whose month ended more than *keep_days* ago.

    *keep_days* defaults to `call_log_retention_days`, and 0 or less keeps every month. Files with
    other names are not touched. Returns what it deleted.
    """
    from agentic_base.limits import get_limits

    days = get_limits().call_log_retention_days if keep_days is None else keep_days
    if days <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    deleted = []
    for path in sorted(Path(directory).glob("*.jsonl")):
        try:
            month = datetime.strptime(path.stem, "%Y-%m").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        ended = month.replace(
            year=month.year + month.month // 12, month=month.month % 12 + 1
        )
        if (now - ended).days > days:
            path.unlink()
            deleted.append(path)
    return deleted


def default_call_log_directory() -> Path:
    """Where calls are written when nobody said otherwise.

    ``$XDG_STATE_HOME/agentic-base/calls``, which is ``~/.local/state/agentic-base/calls`` on most
    machines: the place the XDG convention keeps what a program records and a person may want
    later. A relative ``XDG_STATE_HOME`` is ignored, as the convention says.
    """
    state = os.environ.get("XDG_STATE_HOME", "").strip()
    root = (
        Path(state)
        if state and Path(state).is_absolute()
        else Path.home() / ".local" / "state"
    )
    return root / "agentic-base" / "calls"


def observer_from_environment(server: str = "", version: str = "") -> CallObserver:
    """The observer the environment asks for. `AP_CALL_LOG` says where calls go.

    * Unset or empty: one file a month in `default_call_log_directory`.
    * ``off``: nowhere.
    * Anything else: the file it names.

    Recording is the default because the people who need the record, the person an agent worked
    for and whoever answers for the agent later, are not the people who configure the client.

    *server* and *version* name the server in every line, so a log several servers share still says
    which build answered.

    Read when called, never at import, so a variable set after import still counts. Wrapped in
    `SafeObserver`: a log that cannot be written must not fail the call it describes.
    """
    setting = os.environ.get(CALL_LOG_VARIABLE, "").strip()
    if setting.lower() == CALL_LOG_OFF:
        return NullObserver()
    if setting:
        return SafeObserver(JsonLinesObserver(setting, server=server, version=version))
    try:
        directory = default_call_log_directory()
    except RuntimeError:
        # No home directory to find, as for some service accounts: nowhere to put the default.
        return NullObserver()
    return SafeObserver(
        JsonLinesObserver(directory, server=server, version=version, monthly=True)
    )


@dataclass(frozen=True)
class CallLog:
    """Calls read back from call log files, oldest first."""

    calls: list[dict[str, Any]]
    files: list[Path]
    unreadable_lines: int = 0


@dataclass(frozen=True)
class ToolSummary:
    """How one tool of one server was used: how often, how often it failed, how long it took."""

    server: str
    tool: str
    calls: int
    failed: int
    median_ms: float
    p95_ms: float
    last_error: str = ""


@dataclass(frozen=True)
class CallSummary:
    """What a call log says at a glance."""

    tools: list[ToolSummary]
    clients: dict[str, int] = field(default_factory=dict)
    first: str = ""
    last: str = ""

    @property
    def calls(self) -> int:
        return sum(t.calls for t in self.tools)

    @property
    def failed(self) -> int:
        return sum(t.failed for t in self.tools)


def read_call_log(
    paths: Iterable[str | Path] = (),
    *,
    since: datetime | None = None,
    server: str | None = None,
) -> CallLog:
    """The calls in *paths*, or in `default_call_log_directory` when there are none.

    A directory stands for every ``*.jsonl`` file in it. A line that is not a JSON object, or has no
    time when *since* asks for one, is counted in ``unreadable_lines`` and skipped: a server killed
    mid-write leaves half a line, and that must not hide the rest. A path that does not exist
    raises `FileNotFoundError`, except the default directory, which only means nothing was recorded
    yet.
    """
    named = [Path(p) for p in paths]
    files: list[Path] = []
    for path in named or [default_call_log_directory()]:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        elif named or path.exists():
            files.append(path)
    calls: list[dict[str, Any]] = []
    unreadable = 0
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as log:
            for line in log:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    unreadable += 1
                    continue
                if not isinstance(entry, dict):
                    unreadable += 1
                    continue
                if server is not None and entry.get("server") != server:
                    continue
                if since is not None:
                    when = _when(entry)
                    if when is None:
                        unreadable += 1
                        continue
                    if when < since:
                        continue
                calls.append(entry)
    calls.sort(key=lambda entry: str(entry.get("time", "")))
    return CallLog(calls=calls, files=files, unreadable_lines=unreadable)


def summarise_calls(calls: Iterable[dict[str, Any]]) -> CallSummary:
    """Per server and tool: calls, failures, median and 95th percentile duration, latest error.

    The busiest tool comes first. Clients are counted by name and version, as the handshake gave
    them.
    """
    by_tool: dict[tuple[str, str], list[dict[str, Any]]] = {}
    clients: Counter[str] = Counter()
    times: list[str] = []
    for entry in calls:
        key = (str(entry.get("server", "")), str(entry.get("tool", "")))
        by_tool.setdefault(key, []).append(entry)
        client = entry.get("client")
        if isinstance(client, dict) and client.get("name"):
            clients[
                " ".join(str(client[k]) for k in ("name", "version") if client.get(k))
            ] += 1
        if entry.get("time"):
            times.append(str(entry["time"]))
    tools = []
    for (server, tool), entries in by_tool.items():
        durations = sorted(float(e.get("elapsed_ms", 0.0)) for e in entries)
        failures = [e for e in entries if not e.get("success")]
        tools.append(
            ToolSummary(
                server=server,
                tool=tool,
                calls=len(entries),
                failed=len(failures),
                median_ms=statistics.median(durations),
                p95_ms=durations[max(0, math.ceil(0.95 * len(durations)) - 1)],
                last_error=str(failures[-1].get("error", "")) if failures else "",
            )
        )
    tools.sort(key=lambda t: (-t.calls, t.server, t.tool))
    return CallSummary(
        tools=tools,
        clients=dict(clients.most_common()),
        first=min(times, default=""),
        last=max(times, default=""),
    )


def _when(entry: dict[str, Any]) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(entry["time"]))
    except (KeyError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


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
        context = call_context(
            params,
            request_id=getattr(ctx, "request_id", None),
            protocol_version=getattr(ctx, "protocol_version", None) or "",
            client=_client_info(ctx),
            meta=params.get("_meta") or getattr(ctx, "meta", None),
        )
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
                error=capped_error(str(exc)),
                **context,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        text, success = call_outcome(result)
        seen = self.observer.inspect_result(tool, text, success)
        if seen != text:
            # A client may read the structured copy instead of the text, so a rewrite that reached
            # only the text would hand the original to exactly those clients.
            result = _with_structured(_with_first_text(result, seen), seen)
        if not success:
            context["error"] = capped_error(seen)
        self.observer.record(
            tool, arguments, seen, success, elapsed_ms, method=ctx.method, **context
        )
        return result


PROTOCOL_META_PREFIX = "io.modelcontextprotocol/"
"""Keys the protocol itself puts in a request's ``_meta``; the session already says what they say."""

CALL_LOG_SCHEMA = "call_log_line.schema.json"
"""The JSON Schema of one line of the call log, shipped beside this module (`call_log_schema`)."""


def call_context(
    params: Mapping[str, Any],
    *,
    request_id: Any = None,
    protocol_version: str = "",
    client: Any = None,
    meta: Mapping[str, Any] | None = None,
    span_context: Any = None,
) -> dict[str, Any]:
    """What joins a call to the rest of the story: who called, which request, which trace, which run.

    The one definition of these fields of a call record. `ObservingMiddleware` uses it inside a
    server built on the MCP SDK; a relay in front of any other server uses it with what it read
    off the wire. *client* is the handshake's client info, a mapping or an object with ``name``
    and ``version``. The caller's ``_meta`` keys are kept, where an agent passes its run id (base
    names it ``agentic_base.run_id``, the tag its MLflow export uses). The trace and span ids are
    those of *span_context*, or of the current OpenTelemetry span. A field that is unknown is left
    out.
    """
    context: dict[str, Any] = {}
    if request_id is not None:
        context["request_id"] = request_id
    if protocol_version:
        context["protocol_version"] = protocol_version
    pairs = (
        ("name", _field(client, "name")),
        ("version", _field(client, "version")),
    )
    named = {key: str(value) for key, value in pairs if value}
    if named:
        context["client"] = named
    raw = meta if meta is not None else params.get("_meta")
    caller_meta = {
        k: v
        for k, v in dict(raw or {}).items()
        if not str(k).startswith(PROTOCOL_META_PREFIX)
    }
    if caller_meta:
        context["meta"] = caller_meta
    context.update(_trace_ids(span_context))
    return context


def call_outcome(
    result: Any = None, error: Mapping[str, Any] | None = None
) -> tuple[str, bool]:
    """The text the client got and whether the call succeeded.

    From a result, in its wire form or as the SDK's model: its first text block, failed when it
    says ``isError``. Or from a JSON-RPC error object, which is always a failure.
    """
    if error is not None:
        return str(error.get("message", "")), False
    return _first_text(result), not _is_error(result)


def capped_error(text: str) -> str:
    """A failed call's error text as a record keeps it: cut at `call_log_error_chars`."""
    from agentic_base.limits import get_limits

    limit = get_limits().call_log_error_chars
    return text if len(text) <= limit else f"{text[:limit]}… [{len(text)} characters]"


def call_log_schema() -> dict[str, Any]:
    """The JSON Schema one line of the call log satisfies, whoever wrote it."""
    from importlib.resources import files

    schema: dict[str, Any] = json.loads(
        files("agentic_base").joinpath(CALL_LOG_SCHEMA).read_text(encoding="utf-8")
    )
    return schema


def _field(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _client_info(ctx: Any) -> Any:
    session = getattr(ctx, "session", None)
    return getattr(getattr(session, "client_params", None), "client_info", None)


def _trace_ids(span_context: Any = None) -> dict[str, str]:
    """The ids of *span_context*, or of the current span when OpenTelemetry is installed.

    The MCP SDK depends on OpenTelemetry and opens a span for every request, so on a server the
    current span is that span. The import is here so the library half does not need
    OpenTelemetry to be imported.
    """
    if span_context is None:
        try:
            from opentelemetry import trace
        except ImportError:
            return {}
        span_context = trace.get_current_span().get_span_context()
    if not getattr(span_context, "is_valid", False):
        return {}
    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


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
